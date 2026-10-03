import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from registry.backup_integrity import verify_document_hashes


class Command(BaseCommand):
    help = "Tworzy spójny snapshot SQLite lub PostgreSQL z manifestem SHA-256. Nie kopiuje konfiguracji sekretów."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)
        parser.add_argument("--pg-bin-directory")

    def handle(self, output, **options):
        db = settings.DATABASES["default"]
        if db["ENGINE"] == "django.db.backends.postgresql":
            from registry.postgres_backup import backup_postgres

            manifest = backup_postgres(output, options.get("pg_bin_directory"))
            self.stdout.write(
                self.style.SUCCESS(
                    f"Backup PostgreSQL utworzony: {output}. SHA-256: {manifest['database_sha256']}"
                )
            )
            return
        if db["ENGINE"] != "django.db.backends.sqlite3":
            raise CommandError("Nieobsługiwany silnik bazy danych.")
        destination = Path(output).resolve()
        if destination.exists():
            raise CommandError("Plik docelowy już istnieje; wybierz nową nazwę.")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(dir=settings.DATA_DIR) as temporary:
            snapshot = Path(temporary) / "registry.sqlite3"
            with sqlite3.connect(str(db["NAME"])) as source, sqlite3.connect(snapshot) as target:
                source.backup(target)
                if (
                    target.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or target.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise CommandError("Snapshot nie przeszedł kontroli spójności.")
                verify_document_hashes(target)
                counts = {
                    table: target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    for (table,) in target.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'registry_%'"
                    )
                }
            digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            manifest = {
                "format": 1,
                "created_at": timezone.now().isoformat(),
                "database_sha256": digest,
                "counts": counts,
                "secrets_included": False,
                "pdf_storage": "database",
            }
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, "registry.sqlite3")
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        self.stdout.write(
            self.style.SUCCESS(f"Backup utworzony: {destination}. Spójność OK; SHA-256: {digest}")
        )
