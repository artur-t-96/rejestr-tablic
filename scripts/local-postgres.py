#!/usr/bin/env python3
"""Osobny lokalny PostgreSQL, prywatny socket, bez TCP i bez kontenerów."""

import argparse
import getpass
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "start", "stop", "status"])
    parser.add_argument(
        "--bin-dir",
        default=os.environ.get(
            "DYNA_POSTGRES_BIN", str(ROOT / "var/runtimes/postgresapp/Postgres.app/Contents/Versions/18/bin")
        ),
    )
    parser.add_argument("--directory", default=str(ROOT / "var/postgres-native"))
    args = parser.parse_args()
    if os.environ.get("DYNA_ENV", "local") != "local":
        parser.error("Ten skrypt jest przeznaczony wyłącznie do lokalnej bazy testowej.")
    binaries, directory = Path(args.bin_dir).resolve(), Path(args.directory).resolve()
    data, socket = directory / "data", directory / "socket"
    marker = directory / "dyna-local.json"
    if len(str(socket).encode()) > 85:
        parser.error("Ścieżka prywatnego socketu jest zbyt długa. Wybierz krótszy katalog lokalny.")
    if not (binaries / "pg_ctl").is_file():
        parser.error("Nie znaleziono pg_ctl. Wskaż katalog narzędzi PostgreSQL przez --bin-dir.")
    admin = getpass.getuser()
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", admin):
        parser.error("Nazwa użytkownika systemowego wymaga ręcznej konfiguracji mapowania peer.")
    env = {**os.environ, "PGPASSFILE": str(directory / "unused-pgpass"), "PGSERVICEFILE": "/dev/null"}
    env.pop("PGSERVICE", None)

    def run(name, *values, check=True, capture=False):
        return subprocess.run(
            [str(binaries / name), *map(str, values)], env=env, check=check, capture_output=capture, text=True
        )

    def start():
        state = run("pg_ctl", "-D", data, "status", check=False, capture=True)
        if state.returncode == 0:
            print("Lokalny PostgreSQL już działa.")
        elif state.returncode == 3:
            run("pg_ctl", "-D", data, "-l", directory / "postgres.log", "-w", "-t", "10", "start")
        else:
            raise RuntimeError("Nie udało się potwierdzić stanu PostgreSQL; start nie został powtórzony.")

    if args.action == "init":
        if directory.exists():
            parser.error("Katalog już istnieje. Skrypt nie nadpisuje ani nie usuwa danych.")
        directory.mkdir(mode=0o700, parents=True)
        socket.mkdir(mode=0o700)
        run(
            "initdb",
            "-D",
            data,
            "--encoding=UTF8",
            "--locale=C",
            "--auth-local=peer",
            "--auth-host=scram-sha-256",
            "--data-checksums",
        )
        configuration = {
            "listen_addresses": "''",
            "port": "18765",
            "unix_socket_directories": "'" + str(socket).replace("'", "''") + "'",
            "unix_socket_permissions": "0700",
            "max_connections": "20",
            "shared_buffers": "'16MB'",
            "work_mem": "'1MB'",
            "maintenance_work_mem": "'16MB'",
            "max_parallel_workers": "0",
            "max_worker_processes": "2",
            "max_wal_senders": "0",
            "wal_level": "minimal",
            "max_wal_size": "'128MB'",
            "min_wal_size": "'32MB'",
            "fsync": "on",
            "synchronous_commit": "on",
            "statement_timeout": "'15s'",
            "lock_timeout": "'5s'",
            "idle_in_transaction_session_timeout": "'30s'",
            "timezone": "'Europe/Warsaw'",
        }
        with (data / "postgresql.conf").open("a") as out:
            out.write("\n# Dyna: osobny lokalny klaster, bez TCP\n")
            out.write("\n".join(f"{key} = {value}" for key, value in configuration.items()) + "\n")
        hba = data / "pg_hba.conf"
        hba.write_text("local all dyna_pgtest peer map=dyna_local\n" + hba.read_text())
        with (data / "pg_ident.conf").open("a") as out:
            out.write(f"\ndyna_local {admin} dyna_pgtest\n")
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as out:
            json.dump(
                {
                    "purpose": "dyna-local-test",
                    "port": 18765,
                    "role": "dyna_pgtest",
                    "database": "drt_pg_local",
                    "tcp": False,
                },
                out,
            )
        start()
        run(
            "psql",
            "-h",
            socket,
            "-p",
            "18765",
            "-U",
            admin,
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "CREATE ROLE dyna_pgtest LOGIN NOSUPERUSER NOCREATEROLE CREATEDB;",
        )
        run("createdb", "-h", socket, "-p", "18765", "-U", admin, "-O", "dyna_pgtest", "drt_pg_local")
    else:
        if not marker.is_file() or json.loads(marker.read_text()).get("purpose") != "dyna-local-test":
            parser.error("Brak znacznika klastra tego projektu. Operacja nie zostanie wykonana.")
        if args.action == "start":
            start()
        elif args.action == "stop":
            state = run("pg_ctl", "-D", data, "status", check=False, capture=True)
            if state.returncode == 0:
                run("pg_ctl", "-D", data, "-w", "-t", "10", "-m", "fast", "stop")
            elif state.returncode != 3:
                raise RuntimeError("Nie potwierdzono stanu klastra; nie wykonano zatrzymania.")
            else:
                print("Lokalny PostgreSQL jest zatrzymany.")
        else:
            state = run("pg_ctl", "-D", data, "status", check=False)
            if state.returncode not in {0, 3}:
                raise RuntimeError("Nie udało się odczytać stanu klastra.")
            return
    if args.action in {"init", "start"}:
        print(f"PGHOST={socket}\nPGPORT=18765\nPGUSER=dyna_pgtest\nPGDATABASE=drt_pg_local")
        print("Rola testowa ma CREATEDB dla testów Django; nie jest kontem produkcyjnym.")


if __name__ == "__main__":
    main()
