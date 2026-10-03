import hashlib
from datetime import datetime
from datetime import timezone as datetime_timezone
from importlib import import_module
from io import BytesIO
from unittest.mock import patch

from django.apps import apps
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from pypdf import PdfReader

from .documents import DEFAULT_TEMPLATES, document_link, render_pdf
from .forms import TemplateForm
from .models import AuditLog, LetterTemplate, NumberSequence, Request
from .services import allocate_pool, create_request
from .tests import data, fixtures


def text(payload):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(payload)).pages)


class DocumentTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_new_pdf_has_one_exact_link_without_period_and_no_personal_data_in_uri(self):
        req = create_request(self.a, data())
        letter = req.letters.get()
        reader = PdfReader(BytesIO(bytes(letter.pdf)))
        uris = [
            str(annotation.get_object()["/A"]["/URI"])
            for page in reader.pages
            for annotation in page.get("/Annots", [])
            if annotation.get_object().get("/A", {}).get("/S") == "/URI"
        ]
        self.assertEqual(uris, [document_link(letter)])
        self.assertTrue(uris[0].endswith("/"))
        self.assertNotIn(req.record.owner, uris[0])
        self.assertIn(str(req.uuid), text(bytes(letter.pdf)))
        self.assertNotIn("Uzasadnienie: .", letter.body)
        self.assertNotIn("Urząd Urząd", letter.body)

    def test_generated_date_is_archival_date_not_today(self):
        letter = create_request(self.a, data()).letters.get()
        letter.created_at = datetime(2020, 12, 31, 23, 30, tzinfo=datetime_timezone.utc)
        with patch("registry.documents.timezone.localdate", return_value=timezone.localdate()):
            contents = text(render_pdf(letter))
        self.assertIn("01.01.2021", contents)

    def test_body_markup_is_printed_as_text_without_remote_annotations(self):
        req = create_request(
            self.a,
            {
                **data(),
                "owner": "Fikcyjny <b>Żółw & Łąka</b>",
                "justification": '<link href="https://foreign.invalid">literalny tekst</link>',
            },
        )
        reader = PdfReader(BytesIO(bytes(req.letters.get().pdf)))
        self.assertIn("Fikcyjny <b>Żółw & Łąka</b>", text(bytes(req.letters.get().pdf)))
        uris = [
            str(a.get_object().get("/A", {}).get("/URI", ""))
            for page in reader.pages
            for a in page.get("/Annots", [])
        ]
        self.assertFalse(any("foreign.invalid" in url for url in uris))

    def test_custom_template_errors_are_detected_before_saving_or_reserving(self):
        for body in ["${unknown}", "Niepoprawny ${owner", "Koszt $5"]:
            form = TemplateForm(data={"title": "Tytuł", "body": body})
            self.assertFalse(form.is_valid())
        self.assertTrue(TemplateForm(data={"title": "Tytuł", "body": "${owner}; dosłownie $$"}).is_valid())
        LetterTemplate.objects.create(kind="APPLICATION", title="Własny", body="${unknown}")
        with self.assertRaises(ValidationError):
            create_request(self.a, data())
        self.assertFalse(Request.objects.exists())
        self.assertFalse(NumberSequence.objects.exists())

    @override_settings(APP_URL="javascript:alert(1)")
    def test_unsafe_application_url_rolls_back_request_and_numbering(self):
        with self.assertRaises(ValidationError):
            create_request(self.a, data())
        self.assertFalse(Request.objects.exists())
        self.assertFalse(NumberSequence.objects.exists())

    def test_direct_pool_pdf_links_to_pool_instead_of_fake_request(self):
        pool = allocate_pool(
            self.ump,
            {
                "kind": "II",
                "office": "a",
                "prefix": "P",
                "start": 1,
                "end": 2,
                "valid_from": timezone.localdate(),
            },
        )
        letter = pool.letters.get()
        self.assertIn(f"/panel/pule/{pool.uuid}/", document_link(letter))
        contents = text(bytes(letter.pdf))
        self.assertIn(str(pool.uuid), contents)
        self.assertIn("Powiązanie ze sprawą: Przydzielona pula", contents)

    def test_long_paragraph_splits_over_pages_and_keeps_complete_text(self):
        phrase = "Fikcyjne uzasadnienie z polskimi znakami: Żółć, Łódź i Poznań. "
        req = create_request(self.a, {**data(), "justification": phrase * 80 + "ZNACZNIK-KONCA"})
        letter = req.letters.get()
        reader = PdfReader(BytesIO(bytes(letter.pdf)))
        self.assertGreater(len(reader.pages), 1)
        self.assertIn("ZNACZNIK-KONCA", text(bytes(letter.pdf)))
        for number, page in enumerate(reader.pages, 1):
            self.assertIn(f"Strona {number}", page.extract_text())

    def test_migration_updates_only_exact_unchanged_defaults_and_keeps_archival_bytes(self):
        migration = import_module("registry.migrations.0008_refresh_builtin_templates")
        for kind, (title, body) in migration.LEGACY.items():
            LetterTemplate.objects.create(kind=kind, title=title, body=body)
        LetterTemplate.objects.filter(kind="APPROVAL").update(title="Własny tytuł urzędu")
        LetterTemplate.objects.filter(kind="POOL").update(revision=3)
        req = create_request(self.a, data())
        letter = req.letters.get()
        archived = bytes(letter.pdf)
        digest = hashlib.sha256(archived).hexdigest()
        migration.update_defaults(apps, None)
        migration.update_defaults(apps, None)
        self.assertEqual(
            LetterTemplate.objects.get(kind="APPLICATION").body, DEFAULT_TEMPLATES["APPLICATION"][1]
        )
        self.assertEqual(LetterTemplate.objects.get(kind="APPLICATION").revision, 2)
        self.assertEqual(LetterTemplate.objects.get(kind="APPROVAL").title, "Własny tytuł urzędu")
        self.assertEqual(LetterTemplate.objects.get(kind="POOL").revision, 3)
        self.assertEqual(AuditLog.objects.filter(action="template.default.updated").count(), 2)
        letter.refresh_from_db()
        self.assertEqual((bytes(letter.pdf), letter.sha256), (archived, digest))
        migration.restore_defaults(apps, None)
        self.assertEqual(
            LetterTemplate.objects.get(kind="APPLICATION").body, migration.LEGACY["APPLICATION"][1]
        )
        letter.refresh_from_db()
        self.assertEqual(bytes(letter.pdf), archived)
