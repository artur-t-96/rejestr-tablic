import hashlib

from django.core.management.base import CommandError


def verify_document_hashes(db, *, tables=None, columns=None):
    """Kontrola bajtów dokumentów, kolejki i dowodów również w starszej kopii."""
    if tables is None:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if columns is None:
        columns = lambda table: {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    for payload, sha in db.execute("SELECT pdf, sha256 FROM registry_letter"):
        if hashlib.sha256(payload).hexdigest() != sha:
            raise CommandError("Uszkodzony dokument PDF w bazie kopii zapasowej.")
    letter_columns = columns("registry_letter")
    if "signed_sha256" in letter_columns:
        for payload, sha in db.execute(
            "SELECT signed_pdf, signed_sha256 FROM registry_letter WHERE signed_pdf IS NOT NULL"
        ):
            if hashlib.sha256(payload).hexdigest() != sha:
                raise CommandError("Uszkodzony podpisany PDF w bazie kopii zapasowej.")
    if "registry_integrationjob" in tables:
        job_columns = columns("registry_integrationjob")
        if {"payload", "payload_sha256"} <= job_columns:
            for payload, sha in db.execute(
                "SELECT payload, payload_sha256 FROM registry_integrationjob WHERE payload IS NOT NULL"
            ):
                if hashlib.sha256(payload).hexdigest() != sha:
                    raise CommandError("Uszkodzony dokument kolejki w bazie kopii zapasowej.")
    if "registry_deliveryevidence" in tables:
        for content, sha in db.execute("SELECT content, sha256 FROM registry_deliveryevidence"):
            if hashlib.sha256(content).hexdigest() != sha:
                raise CommandError("Uszkodzony dowód doręczenia w bazie kopii zapasowej.")
    if "registry_ezdincomingdocument" in tables:
        for content, sha in db.execute(
            "SELECT content,sha256 FROM registry_ezdincomingdocument WHERE content IS NOT NULL"
        ):
            if hashlib.sha256(content).hexdigest() != sha:
                raise CommandError("Uszkodzony dokument wpływu EZD w kopii zapasowej.")
    if "registry_numbersequence" in tables:
        maximums = {}
        for reference, year, ordinal in db.execute(
            "SELECT reference_number,reference_year,reference_ordinal FROM registry_request "
            "WHERE reference_year IS NOT NULL"
        ):
            if reference != f"W/{year}/{ordinal:05d}":
                raise CommandError("Niespójny identyfikator wniosku w kopii zapasowej.")
            key = ("REQUEST", year)
            maximums[key] = max(maximums.get(key, 0), ordinal)
        for number, office, year, ordinal in db.execute(
            "SELECT number,office_id,number_year,number_ordinal FROM registry_letter "
            "WHERE number_year IS NOT NULL"
        ):
            if number != f"DRT/{office}/{year}/{ordinal:06d}":
                raise CommandError("Niespójny numer pisma w kopii zapasowej.")
            key = (f"LETTER.{office}", year)
            maximums[key] = max(maximums.get(key, 0), ordinal)
        sequences = {
            (scope, year): value
            for scope, year, value in db.execute("SELECT scope,year,last_value FROM registry_numbersequence")
        }
        if any(sequences.get(key, 0) < value for key, value in maximums.items()):
            raise CommandError("Liczniki w kopii zapasowej są cofnięte względem zapisanych dokumentów.")
