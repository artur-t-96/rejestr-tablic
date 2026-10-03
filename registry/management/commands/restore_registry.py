import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from registry.backup_integrity import verify_document_hashes


class Command(BaseCommand):
    help = "Odtwarza SQLite do nowego katalogu lub PostgreSQL do nowej bazy. Unieważnia sesje i wstrzymuje kolejkę."

    def add_arguments(self, parser):
        parser.add_argument("backup")
        parser.add_argument("--target", required=True)
        parser.add_argument("--target-database")
        parser.add_argument("--pg-bin-directory")

    def handle(self, backup, target, **options):
        target = Path(target).resolve()
        if target.exists():
            raise CommandError("Katalog docelowy musi być nowy. Odtworzenie nie nadpisuje istniejącej pracy.")
        try:
            with zipfile.ZipFile(backup) as archive:
                if archive.getinfo("manifest.json").file_size > 1_000_000:
                    raise CommandError("Manifest przekracza limit rozmiaru.")
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict):
                    raise CommandError("Niepoprawny manifest kopii zapasowej.")
                engine = manifest.get("engine")
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            raise CommandError("Niepoprawny manifest kopii zapasowej.") from exc
        if engine == "postgresql":
            from registry.postgres_backup import restore_postgres

            report = restore_postgres(
                backup, target, options.get("target_database"), options.get("pg_bin_directory")
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Odtworzono i sprawdzono PostgreSQL: {report['target_database']}. Sesje unieważnione; kolejka wstrzymana."
                )
            )
            return
        if engine not in {None, "sqlite"} or options.get("target_database"):
            raise CommandError("Niepoprawny format lub opcje odtworzenia SQLite.")
        try:
            with zipfile.ZipFile(backup) as archive:
                if set(archive.namelist()) != {"registry.sqlite3", "manifest.json"}:
                    raise CommandError("Niepoprawna zawartość archiwum.")
                if any(info.file_size > 2_000_000_000 for info in archive.infolist()):
                    raise CommandError("Archiwum przekracza limit 2 GB na plik.")
                manifest = json.loads(archive.read("manifest.json"))
                payload = archive.read("registry.sqlite3")
            if (
                manifest.get("format") != 1
                or hashlib.sha256(payload).hexdigest() != manifest["database_sha256"]
            ):
                raise CommandError("Niepoprawny format lub suma kontrolna backupu.")
            with tempfile.TemporaryDirectory() as temporary:
                candidate = Path(temporary) / "registry.sqlite3"
                candidate.write_bytes(payload)
                with sqlite3.connect(candidate) as db:
                    if (
                        db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                        or db.execute("PRAGMA foreign_key_check").fetchall()
                    ):
                        raise CommandError("Baza nie przeszła kontroli spójności.")
                    for table, expected in manifest["counts"].items():
                        if not table.startswith("registry_") or not table.replace("_", "").isalnum():
                            raise CommandError("Niepoprawny manifest tabel.")
                        count = db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        if count != expected:
                            raise CommandError("Liczba rekordów nie odpowiada manifestowi.")
                    verify_document_hashes(db)
                    db.execute("DELETE FROM django_session")
                    db.execute("UPDATE registry_logincode SET used=1")
                    tables = {
                        row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }
                    if "registry_publicchallenge" in tables:
                        db.execute(
                            "UPDATE registry_publicchallenge SET consumed_at=CURRENT_TIMESTAMP WHERE consumed_at IS NULL"
                        )
                    if "registry_integrationjob" in tables:
                        db.execute(
                            "UPDATE registry_integrationjob SET result="
                            "json_set(result, '$.restore_requires_reconciliation', json('true')) "
                            "WHERE provider='EDOR'"
                        )
                        db.execute(
                            "UPDATE registry_integrationjob SET status='REVIEW_REQUIRED', "
                            "error='Odtworzona kolejka: sprawdź wynik u operatora przed wznowieniem.' "
                            "WHERE status IN ('QUEUED','PROCESSING','RETRY','RETRY_EXHAUSTED','MONITORING')"
                        )
                    if "registry_accountinvitation" in tables:
                        db.execute(
                            "UPDATE registry_accountinvitation SET status='REVIEW_REQUIRED', claimed_until=NULL, "
                            "updated_at=CURRENT_TIMESTAMP, error='Odtworzona kolejka: sprawdź wynik SMTP przed wznowieniem.' "
                            "WHERE status IN ('QUEUED','SENDING','CONFIG_ERROR','REVIEW_REQUIRED')"
                        )
                    if "registry_ezdcaselink" in tables:
                        db.execute(
                            "UPDATE registry_ezdcaselink SET state='REVIEW_REQUIRED' WHERE state='CREATING'"
                        )
                    db.commit()
                target.mkdir(parents=True, mode=0o700)
                fd = os.open(target / "registry.sqlite3", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as out:
                    out.write(candidate.read_bytes())
                (target / "restore-manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2)
                )
        except (OSError, ValueError, zipfile.BadZipFile, sqlite3.DatabaseError, KeyError) as exc:
            raise CommandError("Nie udało się odtworzyć poprawnego backupu.") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Odtworzono bazę do: {target}. Spójność, liczby rekordów i PDF: OK. Sesje unieważnione; kolejka wstrzymana do uzgodnienia wyników."
            )
        )
