#!/usr/bin/env python3
"""Fikcyjne procesy do PDF, Poppler, kontrola granic i rzeczywisty odczyt QR.

Wymaga nowego katalogu SQLite i nowych katalogów wyników; nie dotyka głównej bazy.
Weryfikacja automatyczna nie zastępuje obejrzenia każdej wyrenderowanej strony.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--render-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if os.environ.get("DYNA_ENV", "local") != "local" or os.environ.get("PGHOST"):
        parser.error("Użyj lokalnego, osobnego SQLite bez PGHOST.")
    for path in (args.data_dir, args.output, args.render_dir, args.report):
        if path.exists():
            parser.error("Wyniki i baza muszą być nowe; istniejące pliki nie zostaną nadpisane.")
    os.environ["DYNA_DATA_DIR"] = str(args.data_dir.resolve())
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    os.environ["APP_URL"] = "http://127.0.0.1:8770"
    import django

    django.setup()
    import pdfplumber
    import zxingcpp
    from django.core.management import call_command
    from PIL import Image

    from registry.documents import document_link
    from registry.services import create_request, decide_request, send_request
    from registry.tests import data, fixtures

    call_command("migrate", interactive=False, verbosity=0)
    _admin, ump, county, _other = fixtures()
    county.office.name = "Starostwo Powiatowe w Gnieźnie - urząd testowy"
    county.office.city = "Gniezno"
    county.office.save()
    ump.office.name = "Urząd Miasta Poznania - Wydział Komunikacji (test)"
    ump.office.city = "Poznań"
    ump.office.save()
    samples = []
    req = create_request(
        county,
        {
            **data("P0ZOLW"),
            "owner": "Osoba Fikcyjna Żółć Łąka",
            "address": "ul. Testowa 12, 00-000 Miejscowość Fikcyjna",
        },
    )
    samples.append(("01-wniosek-indywidualny", req.letters.get()))
    send_request(county, req.uuid)
    decide_request(ump, req.uuid, True, reason="Pozytywna weryfikacja danych fikcyjnych.")
    samples.append(("02-zgoda-indywidualna", req.letters.get(kind="APPROVAL")))
    req = create_request(county, data("P1ZOLW"))
    send_request(county, req.uuid)
    decide_request(
        ump,
        req.uuid,
        False,
        reason="Fikcyjne uzasadnienie odmowy: zgłoszony wyróżnik nie został zaakceptowany.",
    )
    samples.append(("03-odmowa-indywidualna", req.letters.get(kind="REJECTION")))
    for kind, prefix, ordinal in [("II", "P", 4), ("III", "P0", 6)]:
        req = create_request(
            county,
            {
                "kind": kind,
                "count": 3,
                "case_number": "TEST/" + kind,
                "justification": "Fikcyjne zapotrzebowanie na trzy numery.",
                "station": "Stacja Testowa Żółw" if kind == "III" else "",
            },
        )
        samples.append((f"{ordinal:02d}-wniosek-modul-{kind}", req.letters.get()))
        send_request(county, req.uuid)
        decide_request(
            ump,
            req.uuid,
            True,
            pool_data={
                "prefix": prefix,
                "start": 1,
                "end": 3,
                "valid_from": date(2026, 10, 3),
                "valid_until": date(2027, 10, 3),
            },
        )
        samples.append((f"{ordinal + 1:02d}-przydzial-modul-{kind}", req.letters.get(kind="POOL")))
    req = create_request(
        county,
        {
            "kind": "III",
            "count": 2,
            "case_number": "TEST/III/ODM",
            "justification": "Fikcyjne zapotrzebowanie.",
            "station": "Stacja Testowa",
        },
    )
    send_request(county, req.uuid)
    decide_request(ump, req.uuid, False, reason="Fikcyjne uzasadnienie odmowy przydziału puli.")
    samples.append(("08-odmowa-modul-III", req.letters.get(kind="REJECTION")))
    county.office.name = "Testowy urząd o długiej nazwie " + "Żółć Łąka " * 14
    county.office.save()
    phrase = "To wyłącznie fikcyjne uzasadnienie testowe. Sprawdzamy polskie znaki: Żółć, Łódź, Poznań oraz łamanie tekstu na kolejnych stronach. "
    req = create_request(
        county,
        {
            **data("P2ZOLW"),
            "owner": "Fikcyjny Żółw i Łąka " * 8,
            "address": "Adres Fikcyjny " * 14,
            "justification": phrase * 28 + "ZNACZNIK-KONCA-DLUGIEGO-WNIOSKU",
        },
    )
    samples.append(("09-dlugie-dane-wniosku", req.letters.get()))
    send_request(county, req.uuid)
    decide_request(ump, req.uuid, False, reason=phrase * 18 + "ZNACZNIK-KONCA-DLUGIEJ-ODMOWY")
    samples.append(("10-dlugie-uzasadnienie-odmowy", req.letters.get(kind="REJECTION")))
    args.output.mkdir(parents=True)
    args.render_dir.mkdir(parents=True)
    report = {
        "synthetic_data": True,
        "database_separate_from_primary": True,
        "visual_review_completed": False,
        "pdf_accessibility_verified": False,
        "samples": [],
    }
    for name, letter in samples:
        payload = bytes(letter.pdf)
        path = args.output / (name + ".pdf")
        path.write_bytes(payload)
        subprocess.run(
            ["pdftoppm", "-r", "120", "-png", str(path), str(args.render_dir / name)],
            check=True,
            capture_output=True,
        )
        bounds_ok = True
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for char in page.chars:
                    if (
                        char["x0"] < 61
                        or char["x1"] > page.width - 61
                        or char["top"] < 54
                        or char["bottom"] > page.height - 24
                    ):
                        bounds_ok = False
            pages = len(pdf.pages)
        decoded = []
        for png in sorted(args.render_dir.glob(name + "-*.png")):
            with Image.open(png) as picture:
                decoded.extend(
                    code.text
                    for code in zxingcpp.read_barcodes(picture)
                    if code.format == zxingcpp.BarcodeFormat.QRCode
                )
        expected = document_link(letter)
        if not bounds_ok or decoded != [expected]:
            raise SystemExit(f"Layout or QR failed: {name}, bounds={bounds_ok}, QR={decoded}")
        report["samples"].append(
            {
                "name": name,
                "pdf": str(path),
                "pages": pages,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "letter_uuid": str(letter.uuid),
                "request_uuid": str(letter.request.uuid) if letter.request_id else None,
                "text_within_bounds": bounds_ok,
                "decoded_qr": expected,
                "letter_kind": letter.kind,
                "module": letter.request.kind if letter.request_id else letter.pool.kind,
            }
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"PASS: {len(samples)} PDF; {sum(row['pages'] for row in report['samples'])} stron; granice i QR. Pozostaje kontrola wizualna."
    )


if __name__ == "__main__":
    main()
