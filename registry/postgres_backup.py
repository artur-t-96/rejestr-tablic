"""Spójny pg_dump z manifestem; odtworzenie wyłącznie do nowej bazy."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from pathlib import Path

import psycopg
from django.conf import settings
from django.core.management.base import CommandError
from django.utils import timezone
from psycopg import sql

from .backup_integrity import verify_document_hashes


def connection_parameters(database=None):
    db = settings.DATABASES["default"]
    if db["ENGINE"] != "django.db.backends.postgresql":
        raise CommandError("Ustaw konfigurację PostgreSQL dla tego polecenia.")
    parameters = {
        "host": db["HOST"],
        "port": db.get("PORT") or "5432",
        "user": db["USER"],
        "dbname": database or db["NAME"],
        "connect_timeout": 5,
    }
    if db.get("PASSWORD"):
        parameters["password"] = db["PASSWORD"]
    for name in ("sslmode", "sslrootcert", "sslcert", "sslkey", "options"):
        if name in db.get("OPTIONS", {}):
            parameters[name] = db["OPTIONS"][name]
    return parameters


def tool_path(name, directory=None):
    directory = directory or os.environ.get("DYNA_POSTGRES_BIN")
    if directory:
        path = Path(directory).resolve() / name
    elif shutil.which(name):
        path = Path(shutil.which(name))
    elif settings.LOCAL:
        path = settings.BASE_DIR / "var/runtimes/postgresapp/Postgres.app/Contents/Versions/18/bin" / name
    else:
        raise CommandError(f"Brak {name}. Wskaż --pg-bin-directory.")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise CommandError(f"Nie znaleziono narzędzia {name}.")
    return str(path)


def run_tool(name, arguments, parameters, directory=None):
    environment = dict(os.environ)
    environment.pop("PGSERVICE", None)
    for key, value in parameters.items():
        if key != "connect_timeout":
            environment["PG" + key.upper().replace("DBNAME", "DATABASE")] = str(value)
    environment["PGCONNECT_TIMEOUT"] = "5"
    try:
        result = subprocess.run(
            [tool_path(name, directory), *map(str, arguments)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CommandError(f"{name} nie zakończył operacji. Nie opublikowano poprawnej kopii.") from exc
    if result.returncode or result.stderr.strip():
        # Nie wypisujemy SQL, danych ani sekretów ze stderr programu zewnętrznego.
        raise CommandError(f"{name} zwrócił błąd lub ostrzeżenie. Operacja wymaga sprawdzenia.")
    return result.stdout


def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def database_properties(conn):
    encoding, values = conn.execute(
        "SELECT pg_encoding_to_char(encoding),to_jsonb(d) FROM pg_database d WHERE datname=current_database()"
    ).fetchone()
    return {
        "encoding": encoding,
        "collate": values["datcollate"],
        "ctype": values["datctype"],
        "provider": values.get("datlocprovider", "c"),
        "locale": values.get("datlocale", values.get("daticulocale")),
        "icu_rules": values.get("daticurules"),
        "version": values.get("datcollversion"),
    }


def create_database_sql(database, properties):
    if not isinstance(properties, dict) or not all(
        isinstance(properties.get(k), str) for k in ("encoding", "collate", "ctype", "provider")
    ):
        raise CommandError("Kopia nie zawiera poprawnych parametrów kodowania i sortowania bazy.")
    provider = {"c": "libc", "i": "icu", "b": "builtin"}.get(properties["provider"])
    if not provider:
        raise CommandError("Nieobsługiwany dostawca sortowania bazy.")
    query = sql.SQL(
        "CREATE DATABASE {} TEMPLATE template0 ENCODING {} LC_COLLATE {} LC_CTYPE {} LOCALE_PROVIDER {}"
    ).format(
        sql.Identifier(database),
        sql.Literal(properties["encoding"]),
        sql.Literal(properties["collate"]),
        sql.Literal(properties["ctype"]),
        sql.SQL(provider),
    )
    if provider in {"icu", "builtin"}:
        if not isinstance(properties.get("locale"), str):
            raise CommandError("Brak ustawienia locale w kopii.")
        query += sql.SQL(" {} {}").format(
            sql.SQL("ICU_LOCALE" if provider == "icu" else "BUILTIN_LOCALE"),
            sql.Literal(properties["locale"]),
        )
    if provider == "icu" and properties.get("icu_rules") is not None:
        if not isinstance(properties["icu_rules"], str):
            raise CommandError("Niepoprawne reguły sortowania ICU.")
        query += sql.SQL(" ICU_RULES {}").format(sql.Literal(properties["icu_rules"]))
    return query


def registry_schema(conn):
    description = {}
    for table, column in conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'"
    ):
        description.setdefault(table, set()).add(column)
    required = {
        "registry_letter",
        "registry_request",
        "django_migrations",
        "django_session",
        "registry_logincode",
    }
    if not required <= set(description):
        raise CommandError("Brak wymaganych tabel aplikacji w schemacie public.")
    return description


def verify_postgres_documents(conn, description):
    class StreamingQueries:
        def execute(self, query):
            # Nazwany kursor pobiera partie, zamiast całej kolumny bytea do RAM.
            with conn.cursor(name="dyna_hash_" + uuid.uuid4().hex) as cursor:
                cursor.itersize = 8
                cursor.execute(query)
                yield from cursor

    verify_document_hashes(
        StreamingQueries(), tables=set(description), columns=lambda table: description.get(table, set())
    )


def registry_state(conn):
    description = registry_schema(conn)
    verify_postgres_documents(conn, description)
    counts = {}
    for table in sorted(description):
        counts[table] = conn.execute(
            sql.SQL("SELECT COUNT(*) FROM public.{}").format(sql.Identifier(table))
        ).fetchone()[0]
    migrations = [
        list(row) for row in conn.execute("SELECT app,name FROM django_migrations ORDER BY app,name")
    ]
    return {"counts": counts, "migrations": migrations}


def backup_postgres(destination, directory=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise CommandError("Plik docelowy już istnieje; wybierz nową nazwę.")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parameters = connection_parameters()
    try:
        with tempfile.TemporaryDirectory(dir=settings.DATA_DIR) as temporary:
            dump = Path(temporary) / "database.dump"
            with psycopg.connect(**parameters) as conn, conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                conn.execute("SET LOCAL idle_in_transaction_session_timeout='310s'")
                if conn.execute("SELECT current_schema()").fetchone()[0] != "public":
                    raise CommandError("Kopia wymaga dedykowanej bazy aplikacji ze schematem public.")
                conn.execute("SET LOCAL search_path=public,pg_catalog")
                state = registry_state(conn)
                properties = database_properties(conn)
                snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
                version = conn.execute("SHOW server_version_num").fetchone()[0]
                client_version = run_tool("pg_dump", ["--version"], parameters, directory).strip()
                run_tool(
                    "pg_dump",
                    [
                        "--format=custom",
                        "--no-owner",
                        "--no-acl",
                        "--schema=public",
                        "--lock-wait-timeout=5s",
                        f"--snapshot={snapshot}",
                        f"--file={dump}",
                    ],
                    parameters,
                    directory,
                )
            dump.chmod(0o600)
            manifest = {
                "format": 2,
                "engine": "postgresql",
                "schema": "public",
                "created_at": timezone.now().isoformat(),
                "source_database": parameters["dbname"],
                "server_version_num": version,
                "database_properties": properties,
                "client_version": client_version,
                "database_sha256": digest_file(dump),
                **state,
                "configuration_secrets_included": False,
                "authentication_data_included": True,
                "pdf_storage": "database",
                "snapshot_consistent": True,
            }
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as out, zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:
                    archive.write(dump, "database.dump")
                    archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            except Exception:
                destination.unlink(missing_ok=True)
                raise
    except (psycopg.Error, OSError) as exc:
        raise CommandError(
            "Nie utworzono kopii PostgreSQL. Sprawdź połączenie, uprawnienia i spójność dokumentów."
        ) from exc
    return manifest


def restore_postgres(backup, target, database, directory=None):
    target = Path(target).resolve()
    if target.exists():
        raise CommandError("Katalog docelowy musi być nowy.")
    if not database or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", database):
        raise CommandError(
            "Podaj --target-database: nowa nazwa PostgreSQL (małe litery, cyfry, podkreślenia)."
        )
    parameters = connection_parameters(database)
    source_name = str(settings.DATABASES["default"]["NAME"])
    created = False
    try:
        with tempfile.TemporaryDirectory(dir=settings.DATA_DIR) as temporary:
            dump = Path(temporary) / "database.dump"
            with zipfile.ZipFile(backup) as archive:
                if sorted(archive.namelist()) != ["database.dump", "manifest.json"]:
                    raise CommandError("Niepoprawna zawartość archiwum PostgreSQL.")
                if archive.getinfo("manifest.json").file_size > 1_000_000:
                    raise CommandError("Manifest przekracza limit rozmiaru.")
                if (
                    archive.getinfo("database.dump").file_size
                    > shutil.disk_usage(temporary).free - 64_000_000
                ):
                    raise CommandError("Za mało miejsca na odtworzenie archiwum PostgreSQL.")
                manifest = json.loads(archive.read("manifest.json"))
                with archive.open("database.dump") as source, dump.open("xb") as out:
                    shutil.copyfileobj(source, out, length=1_048_576)
            if (
                not isinstance(manifest, dict)
                or manifest.get("format") != 2
                or manifest.get("engine") != "postgresql"
                or manifest.get("schema") != "public"
            ):
                raise CommandError("Nieobsługiwany format kopii PostgreSQL.")
            if (
                not isinstance(manifest.get("source_database"), str)
                or not isinstance(manifest.get("counts"), dict)
                or any(
                    not isinstance(k, str) or type(v) is not int or v < 0
                    for k, v in manifest["counts"].items()
                )
                or not isinstance(manifest.get("migrations"), list)
            ):
                raise CommandError("Niepoprawny manifest kopii PostgreSQL.")
            if digest_file(dump) != manifest.get("database_sha256"):
                raise CommandError("Niepoprawna suma kontrolna kopii PostgreSQL.")
            if database in {
                source_name,
                manifest.get("source_database"),
                "postgres",
                "template0",
                "template1",
            }:
                raise CommandError("Odtworzenie wymaga odrębnej nowej bazy.")
            create_sql = create_database_sql(database, manifest.get("database_properties"))
            # Narzędzie i archiwum sprawdzamy przed utworzeniem nowej bazy.
            run_tool("pg_restore", ["--list", dump], parameters, directory)
            with psycopg.connect(**connection_parameters("postgres"), autocommit=True) as admin:
                if admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", [database]).fetchone():
                    raise CommandError("Baza docelowa już istnieje. Nie zostanie nadpisana.")
                admin.execute(create_sql)
                created = True
            # template0 zawiera pusty public; zrzut zawiera CREATE SCHEMA public.
            # Usuwamy tylko pusty schemat NOWO utworzonej bazy, bez CASCADE.
            with psycopg.connect(**parameters) as empty:
                if database_properties(empty) != manifest["database_properties"]:
                    raise CommandError("Parametry kodowania lub sortowania bazy nie odpowiadają kopii.")
                empty.execute("DROP SCHEMA public")
            run_tool(
                "pg_restore",
                [
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-acl",
                    f"--dbname={database}",
                    dump,
                ],
                parameters,
                directory,
            )
            with psycopg.connect(**parameters) as conn, conn.transaction():
                conn.execute("SET LOCAL search_path=public,pg_catalog")
                state = registry_state(conn)
                if state != {"counts": manifest["counts"], "migrations": manifest["migrations"]}:
                    raise CommandError("Liczby rekordów lub migracje nie odpowiadają manifestowi.")
                sessions = conn.execute("DELETE FROM django_session").rowcount
                codes = conn.execute("UPDATE registry_logincode SET used=TRUE WHERE NOT used").rowcount
                if "registry_publicchallenge" in registry_schema(conn):
                    conn.execute(
                        "UPDATE registry_publicchallenge SET consumed_at=CURRENT_TIMESTAMP WHERE consumed_at IS NULL"
                    )
                conn.execute(
                    "UPDATE registry_integrationjob SET result=result || "
                    "'{\"restore_requires_reconciliation\": true}'::jsonb WHERE provider='EDOR'"
                )
                jobs = conn.execute(
                    "UPDATE registry_integrationjob SET status='REVIEW_REQUIRED', claimed_until=NULL, "
                    "error='Odtworzona kolejka: sprawdź wynik u operatora przed wznowieniem.' "
                    "WHERE status IN ('QUEUED','PROCESSING','RETRY','RETRY_EXHAUSTED','MONITORING')"
                ).rowcount
                invitations = 0
                if "registry_accountinvitation" in registry_schema(conn):
                    invitations = conn.execute(
                        "UPDATE registry_accountinvitation SET status='REVIEW_REQUIRED', claimed_until=NULL, "
                        "updated_at=CURRENT_TIMESTAMP, error='Odtworzona kolejka: sprawdź wynik SMTP przed wznowieniem.' "
                        "WHERE status IN ('QUEUED','SENDING','CONFIG_ERROR','REVIEW_REQUIRED')"
                    ).rowcount
                links = conn.execute(
                    "UPDATE registry_ezdcaselink SET state='REVIEW_REQUIRED' WHERE state='CREATING'"
                ).rowcount
                verify_postgres_documents(conn, registry_schema(conn))
            target.mkdir(parents=True, mode=0o700)
            report = {
                "backup": manifest,
                "target_database": database,
                "verified_at": timezone.now().isoformat(),
                "sessions_invalidated": sessions,
                "codes_invalidated": codes,
                "jobs_held": jobs,
                "account_invitations_held": invitations,
                "case_links_held": links,
                "verified": True,
            }
            fd = os.open(target / "restore-manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as out:
                json.dump(report, out, ensure_ascii=False, indent=2)
            return report
    except (psycopg.Error, OSError, ValueError, KeyError, zipfile.BadZipFile, CommandError) as exc:
        if created:
            try:
                with psycopg.connect(**connection_parameters("postgres"), autocommit=True) as admin:
                    admin.execute(
                        sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(sql.Identifier(database))
                    )
            except psycopg.Error:
                raise CommandError(
                    f"Odtworzenie nie powiodło się i nie zablokowano połączeń do nowej bazy {database}. Wymagana izolacja przez administratora."
                ) from exc
        suffix = (
            f" Nowa baza {database} pozostaje do kontroli; nie uruchamiaj na niej aplikacji ani workerów."
            if created
            else " Nie nadpisano istniejącej bazy."
        )
        message = str(exc) if isinstance(exc, CommandError) else "Nie odtworzono poprawnej kopii PostgreSQL."
        raise CommandError(message + suffix) from exc
