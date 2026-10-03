"""Syntetyczne pakiety OOXML i kontrola rzeczywistych importów CSV/XLSX."""

import hashlib
from datetime import date, datetime
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .imports import FIELDS, apply_source_import, preview_source_import
from .models import AuditLog, PlateRecord, Pool, PoolSlot
from .pool_imports import FIELDS as POOL_FIELDS
from .pool_imports import apply_pool_import, preview_pool_source
from .record_import_views import SESSION_KEY
from .tabular_sources import read_source
from .test_record_imports import csv_text, row
from .tests import fixtures

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def xlsx_bytes(headers, rows, *, extra_sheets=None, change=None):
    """Minimalny pakiet testowy: dane tekstowe i natywne komórki daty OOXML."""

    def cells(values, line):
        result = []
        for i, value in enumerate(values):
            ref = chr(65 + i) + str(line)
            if isinstance(value, (date, datetime)):
                result.append(f'<c r="{ref}" t="d"><v>{value.isoformat()}</v></c>')
            elif isinstance(value, (int, float)):
                result.append(f'<c r="{ref}" t="n"><v>{value}</v></c>')
            elif value is not None:
                result.append(
                    f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'
                )
        return f'<row r="{line}">' + "".join(result) + "</row>"

    tables = [("Ewidencja", headers, rows), *(extra_sheets or [])]
    parts = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(tables) + 1)
        )
        + "</Types>",
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        + "".join(
            f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, (name, _, _) in enumerate(tables, 1)
        )
        + "</sheets></workbook>",
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(tables) + 1)
        )
        + "</Relationships>",
    }
    for i, (_, cols, data) in enumerate(tables, 1):
        parts[f"xl/worksheets/sheet{i}.xml"] = (
            f'<worksheet xmlns="{NS}"><dimension ref="A1:A1"/><sheetData>'
            + cells(cols, 1)
            + "".join(cells(v, r) for r, v in enumerate(data, 2))
            + "</sheetData></worksheet>"
        )
    if change:
        change(parts)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            info = ZipInfo(name, (2025, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, content)
    return output.getvalue()


def workbook(records, **options):
    return xlsx_bytes(FIELDS, [[r[f] for f in FIELDS] for r in records], **options)


class ExcelImportTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_original_bytes_sheet_and_native_dates_preserved_and_replay_blocked(self):
        record = row(
            "M9HIST",
            status="SOLD",
            vin="WVWZZZ1JZXW000009",
            registration_date=date(2025, 1, 1),
            sale_date=date(2025, 2, 1),
            buyer="Fikcyjny nabywca",
            letter_number="00009",
            note="Źródło żółw",
        )
        data = workbook([record])
        checked = preview_source_import(data, "historia.xlsx")
        self.assertEqual(checked["errors"], [])
        self.assertEqual(checked["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(checked["source_sheet"], "Ewidencja")
        self.assertEqual(checked["rows"][0]["registration_date"], "2025-01-01")
        self.assertEqual(
            apply_source_import(self.ump, data, checked["sha256"], "TEST/XLSX", "historia.xlsx"), 1
        )
        saved = PlateRecord.objects.get()
        self.assertEqual(saved.letter_number, "00009")
        self.assertEqual(saved.sale_date, date(2025, 2, 1))
        event = AuditLog.objects.get(action="plate.imported")
        self.assertEqual(event.after["source_format"], "XLSX")
        self.assertEqual(event.after["source_sheet"], "Ewidencja")
        self.assertEqual(event.after["source_sha256"], checked["sha256"])
        with self.assertRaises(ValidationError):
            apply_source_import(self.ump, data, checked["sha256"], "Duplikat", "inna-nazwa.xlsx")
        self.assertEqual(PlateRecord.objects.count(), 1)

    def test_all_thirteen_fields_match_csv_and_excel(self):
        record = row("P3HIST", note="Tekst =SUM(A1:A2); średnik\nnowy wiersz", address="Fikcyjny adres 1")
        excel = preview_source_import(workbook([record]), "plik.xlsx")
        plain = preview_source_import(csv_text([record]), "plik.csv")
        self.assertEqual(excel["rows"], plain["rows"])
        self.assertEqual(excel["errors"], plain["errors"])

    def test_sheet_selection_is_explicit_and_different_sheets_can_be_imported(self):
        first, second = row("P2PAST", status="RELEASED"), row("P3PAST", status="RELEASED")
        data = workbook([first], extra_sheets=[("Archiwum", FIELDS, [[second[f] for f in FIELDS]])])
        with self.assertRaisesMessage(ValidationError, "kilka arkuszy"):
            preview_source_import(data, "plik.xlsx")
        for name in ["Ewidencja", "Archiwum"]:
            checked = preview_source_import(data, "plik.xlsx", name)
            self.assertEqual(
                apply_source_import(self.ump, data, checked["sha256"], "TEST", "plik.xlsx", sheet_name=name),
                1,
            )
        self.assertEqual(PlateRecord.objects.count(), 2)
        with self.assertRaises(ValidationError):
            preview_source_import(data, "plik.xlsx", "Nie istnieje")

    def test_changed_bytes_and_changed_active_database_reject_whole_file(self):
        old = workbook([row("P2TEST"), row("P3TEST")])
        new = workbook([row("P2TEST"), row("P4TEST")])
        checksum = preview_source_import(old, "plik.xlsx")["sha256"]
        with self.assertRaisesMessage(ValidationError, "zmienił się"):
            apply_source_import(self.ump, new, checksum, "TEST", "plik.xlsx")
        apply_source_import(
            self.ump,
            workbook([row("P3TEST")]),
            hashlib.sha256(workbook([row("P3TEST")])).hexdigest(),
            "TEST",
            "plik.xlsx",
        )
        with self.assertRaises(ValidationError):
            apply_source_import(self.ump, old, checksum, "TEST", "plik.xlsx")
        self.assertFalse(PlateRecord.objects.filter(number="P2TEST").exists())

    def test_formula_cached_result_is_not_imported(self):
        def formula(parts):
            path = "xl/worksheets/sheet1.xml"
            parts[path] = parts[path].replace(
                '<c r="A2" t="inlineStr"><is><t xml:space="preserve">P2HIST</t></is></c>',
                '<c r="A2"><f>CONCAT("P2","HIST")</f><v>P2HIST</v></c>',
            )

        with self.assertRaisesMessage(ValidationError, "formułę"):
            preview_source_import(workbook([row()], change=formula), "plik.xlsx")
        self.assertFalse(PlateRecord.objects.exists())

    def test_serial_dates_epochs_and_excel_phantom_day(self):
        def serial(number, mac_epoch=False):
            def change(parts):
                parts["xl/styles.xml"] = (
                    f'<styleSheet xmlns="{NS}"><fonts count="1"><font><name val="Calibri"/><sz val="11"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
                )
                parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
                    "</Relationships>",
                    '<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
                )
                parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].replace(
                    '<c r="H2" t="inlineStr"><is><t xml:space="preserve"></t></is></c>',
                    f'<c r="H2" t="n" s="1"><v>{number}</v></c>',
                )
                if mac_epoch:
                    parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
                        "<sheets>", '<workbookPr date1904="1"/><sheets>'
                    )

            return workbook([row()], change=change)

        checked = preview_source_import(serial(45658), "serial.xlsx")
        self.assertEqual(checked["rows"][0]["registration_date"], "2025-01-01")
        checked = preview_source_import(serial(1, True), "serial.xlsx")
        self.assertEqual(checked["rows"][0]["registration_date"], "1904-01-02")
        with self.assertRaisesMessage(ValidationError, "1900-02-29"):
            preview_source_import(serial(60), "serial.xlsx")

    def test_numeric_identifiers_and_non_midnight_dates_are_rejected(self):
        for record in [
            row(letter_number=123),
            row(vin=12345678901234567),
            row(registration_date=datetime(2025, 1, 1, 12)),
        ]:
            with self.subTest(record=record), self.assertRaises(ValidationError):
                preview_source_import(workbook([record]), "plik.xlsx")

    def test_hidden_rows_columns_merged_cells_and_external_relationships_are_rejected(self):
        changes = [
            lambda p: p.__setitem__(
                "xl/worksheets/sheet1.xml",
                p["xl/worksheets/sheet1.xml"].replace('<row r="2">', '<row r="2" hidden="1">'),
            ),
            lambda p: p.__setitem__(
                "xl/worksheets/sheet1.xml",
                p["xl/worksheets/sheet1.xml"].replace(
                    "<sheetData>", '<cols><col min="1" max="1" hidden="1"/></cols><sheetData>'
                ),
            ),
            lambda p: p.__setitem__(
                "xl/worksheets/sheet1.xml",
                p["xl/worksheets/sheet1.xml"].replace(
                    "</worksheet>", '<mergeCells><mergeCell ref="A2:B2"/></mergeCells></worksheet>'
                ),
            ),
            lambda p: p.__setitem__(
                "xl/_rels/workbook.xml.rels",
                p["xl/_rels/workbook.xml.rels"].replace(
                    'Target="worksheets/sheet1.xml"',
                    'Target="https://example.invalid/file" TargetMode="External"',
                ),
            ),
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                preview_source_import(workbook([row()], change=change), "plik.xlsx")

    def test_malformed_and_active_archive_parts_xml_entities_and_size_are_rejected(self):
        for name in [
            "xl/vbaProject.bin",
            "xl/activeX/activeX1.xml",
            "xl/embeddings/object.bin",
            "xl/externalLinks/link.xml",
            "../escape.xml",
        ]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                preview_source_import(
                    workbook([row()], change=lambda p: p.__setitem__(name, "x")), "plik.xlsx"
                )
        for data in [
            b"not-a-zip",
            workbook(
                [row()],
                change=lambda p: p.__setitem__(
                    "xl/workbook.xml", '<!DOCTYPE x [<!ENTITY a "boom">]><x>&a;</x>'
                ),
            ),
            workbook([row()], change=lambda p: p.__setitem__("xl/large.bin", "0" * 8_000_001)),
        ]:
            with self.assertRaises(ValidationError):
                preview_source_import(data, "plik.xlsx")

    def test_headers_sparse_rows_and_bounds_never_silently_drop_data(self):
        cases = [
            xlsx_bytes(["number", "owner", "owner"], [["P2HIST", "A", "a"]]),
            xlsx_bytes(["number", "owner", "office_id", "unknown"], [["P2HIST", "A", "a", "x"]]),
            workbook(
                [row()],
                change=lambda p: p.__setitem__(
                    "xl/worksheets/sheet1.xml", p["xl/worksheets/sheet1.xml"].replace('r="M2"', 'r="N2"')
                ),
            ),
            workbook(
                [row()],
                change=lambda p: p.__setitem__(
                    "xl/worksheets/sheet1.xml", p["xl/worksheets/sheet1.xml"].replace('r="A2"', 'r="A502"')
                ),
            ),
        ]
        for data in cases:
            with self.subTest(size=len(data)):
                try:
                    checked = preview_source_import(data, "plik.xlsx")
                except ValidationError:
                    continue
                self.assertTrue(checked["errors"])
        self.assertFalse(PlateRecord.objects.exists())

    def test_pool_import_preserves_holes_dates_and_source(self):
        common = {
            "pool_ref": "HIST/01",
            "kind": "II",
            "office_id": "a",
            "prefix": "P",
            "valid_from": date(2025, 1, 1),
            "source_reference": "FIKCYJNE/01",
        }
        rows = [
            {**common, "number": "P030", "issued_on": date(2025, 2, 1), "case_number": "00001"},
            {**common, "number": "P031"},
        ]
        data = xlsx_bytes(POOL_FIELDS, [[r.get(f, "") for f in POOL_FIELDS] for r in rows])
        checked = preview_pool_source(data, "pule.xlsx")
        self.assertEqual(checked["errors"], [])
        self.assertEqual(len(apply_pool_import(self.ump, data, checked["sha256"], "TEST", "pule.xlsx")), 1)
        self.assertEqual(
            list(PoolSlot.objects.order_by("number").values_list("number", flat=True)), ["P030", "P031"]
        )
        self.assertEqual(timezone.localdate(PoolSlot.objects.get(number="P030").issued_at), date(2025, 2, 1))
        self.assertEqual(
            AuditLog.objects.get(action="pool.imported").after["source_sha256"],
            hashlib.sha256(data).hexdigest(),
        )
        self.assertEqual(Pool.objects.count(), 1)

    def test_browser_preview_stores_original_bytes_confirm_and_stale_tab_guard(self):
        self.client.force_login(self.ump)
        url = reverse("import_records")

        def preview(data):
            return self.client.post(
                url, {"file": SimpleUploadedFile("historia.xlsx", data), "action": "preview"}
            )

        data = workbook([row()])
        page = preview(data)
        self.assertContains(page, "Ewidencja")
        self.assertEqual(self.client.session[SESSION_KEY]["source_format"], "XLSX")
        old = self.client.session[SESSION_KEY]["token"]
        preview(workbook([row("P3HIST")]))
        result = self.client.post(
            url, {"action": "confirm", "preview_token": old, "reason": "TEST", "acknowledged": "on"}
        )
        self.assertContains(result, "zastąpiony")
        token = self.client.session[SESSION_KEY]["token"]
        self.assertRedirects(
            self.client.post(
                url, {"action": "confirm", "preview_token": token, "reason": "TEST", "acknowledged": "on"}
            ),
            reverse("records_list"),
        )
        self.assertEqual(PlateRecord.objects.get().number, "P3HIST")

    def test_bad_source_invalidates_old_preview_and_denies_roles_and_csrf(self):
        url = reverse("import_records")
        self.client.force_login(self.ump)
        self.client.post(url, {"file": SimpleUploadedFile("historia.xlsx", workbook([row()]))})
        self.client.post(url, {"file": SimpleUploadedFile("bad.xlsx", b"bad")})
        self.assertNotIn(SESSION_KEY, self.client.session)
        for user in [self.admin, self.a, self.b]:
            self.client.force_login(user)
            self.assertEqual(
                self.client.post(
                    url, {"file": SimpleUploadedFile("historia.xlsx", workbook([row()]))}
                ).status_code,
                403,
            )
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.ump)
        self.assertEqual(
            client.post(url, {"file": SimpleUploadedFile("historia.xlsx", workbook([row()]))}).status_code,
            403,
        )

    def test_long_source_filename_keeps_extension_through_preview_and_confirmation(self):
        self.client.force_login(self.ump)
        filename = "h" * 230 + ".xlsx"
        self.client.post(
            reverse("import_records"),
            {"action": "preview", "file": SimpleUploadedFile(filename, workbook([row()]))},
        )
        self.assertEqual(self.client.session[SESSION_KEY]["filename"], filename)
        token = self.client.session[SESSION_KEY]["token"]
        result = self.client.post(
            reverse("import_records"),
            {"action": "confirm", "preview_token": token, "reason": "TEST", "acknowledged": "on"},
        )
        self.assertRedirects(result, reverse("records_list"))
        event = AuditLog.objects.get(action="plate.imported")
        self.assertEqual(event.after["source_filename"], filename)
        self.assertContains(
            self.client.get(reverse("record_detail", args=[PlateRecord.objects.get().uuid])), "SHA-256 pliku"
        )

    def test_pool_iii_excel_view_confirmation_and_source_details(self):
        from .pool_import_views import SESSION_KEY as POOL_SESSION_KEY
        from .test_pool_imports import row as pool_row

        record = pool_row("P00001", kind="III", prefix="P0", issued_on=date(2025, 2, 1), case_number="00017")
        data = xlsx_bytes(POOL_FIELDS, [[record.get(f, "") for f in POOL_FIELDS]])
        filename = "p" * 230 + ".xlsx"
        self.client.force_login(self.ump)
        url = reverse("import_pools")
        checked = self.client.post(url, {"action": "preview", "file": SimpleUploadedFile(filename, data)})
        self.assertContains(checked, "P00001")
        self.assertFalse(Pool.objects.exists())
        saved = self.client.session[POOL_SESSION_KEY]
        self.assertEqual(saved["filename"], filename)
        result = self.client.post(
            url,
            {"action": "confirm", "preview_token": saved["token"], "reason": "TEST", "acknowledged": "on"},
        )
        self.assertRedirects(result, reverse("pools_list"))
        pool = Pool.objects.get()
        self.assertEqual(pool.kind, "III")
        self.assertEqual(pool.valid_until, date(2025, 12, 31))
        self.assertEqual(PoolSlot.objects.get().case_number, "00017")
        event = AuditLog.objects.get(action="pool.imported")
        self.assertEqual(event.after["source_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(event.after["source_filename"], filename)
        self.assertContains(self.client.get(reverse("pool_detail", args=[pool.uuid])), "Ewidencja")

    def test_malformed_row_and_cell_coordinates_cannot_silently_drop_values(self):
        replacements = [
            ('<row r="2">', '<row r="1">'),
            ('r="B2"', 'r="A2"'),
            ('r="B2"', 'r="B3"'),
            ('<row r="2">', '<row r="502">'),
        ]
        for old, new in replacements:
            with self.subTest(replacement=new):
                data = workbook(
                    [row()],
                    change=lambda p: p.__setitem__(
                        "xl/worksheets/sheet1.xml", p["xl/worksheets/sheet1.xml"].replace(old, new)
                    ),
                )
                with self.assertRaises(ValidationError):
                    preview_source_import(data, "plik.xlsx")
        self.assertFalse(PlateRecord.objects.exists())

    def test_corrupt_saved_source_returns_form_error_instead_of_500(self):
        self.client.force_login(self.ump)
        url = reverse("import_records")
        self.client.post(url, {"file": SimpleUploadedFile("historia.xlsx", workbook([row()]))})
        session = self.client.session
        saved = session[SESSION_KEY]
        saved["source_base64"] = "?"
        session[SESSION_KEY] = saved
        session.save()
        self.assertContains(self.client.get(url), "Źródło podglądu jest niepoprawne")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_csv_bytes_bom_and_sheet_name_validation(self):
        content = ("\ufeff" + csv_text([row()])).encode()
        self.assertEqual(
            preview_source_import(content, "hist.csv")["sha256"], hashlib.sha256(content).hexdigest()
        )
        for filename, sheet in [("hist.xls", ""), ("hist.xlsm", ""), ("hist.csv", "Ewidencja")]:
            with self.assertRaises(ValidationError):
                read_source(content, filename, sheet, fields=FIELDS, date_fields=set(), max_rows=500)
