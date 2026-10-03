"""Kontrole HTML i walidacji; nie zastępują testów klawiatury i czytników."""

from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from .forms import RequestForm
from .models import Request
from .services import allocate_pool, create_request
from .tests import data, fixtures


class Markup(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.elements = []
        self.title = ""
        self.in_title = False
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, content):
        if self.in_title:
            self.title += content


class AccessibilityTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def markup(self, response):
        self.assertEqual(response.status_code, 200)
        return Markup(response.content.decode())

    def test_titles_landmarks_unique_ids_and_labels_for_all_roles(self):
        for user, pages in [
            (None, [("public", "Sprawdź dostępność"), ("login_email", "Logowanie")]),
            (
                self.a,
                [
                    ("dashboard", "Przegląd"),
                    ("requests_list", "Wnioski"),
                    ("request_new", "Nowy wniosek"),
                    ("records_list", "Ewidencja urzędu"),
                    ("pools_list", "Pule"),
                    ("letters_list", "Pisma"),
                    ("integrations", "Integracje"),
                    ("audit_list", "Dziennik"),
                ],
            ),
            (
                self.ump,
                [
                    ("records_list", "Ewidencja województwa"),
                    ("import_records", "Import"),
                    ("pool_new", "Przydział"),
                    ("ezd_incoming", "Wpływy"),
                    ("edor_search", "Wyszukiwanie"),
                ],
            ),
            (self.admin, [("admin_panel", "Urzędy, konta"), ("integrations", "Integracje")]),
        ]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for route, title in pages:
                with self.subTest(role=user.role if user else "PUBLIC", route=route):
                    page = self.markup(self.client.get(reverse(route)))
                    self.assertIn(title, page.title)
                    ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
                    self.assertEqual(len(ids), len(set(ids)))
                    self.assertEqual(sum(tag == "h1" for tag, _ in page.elements), 1)
                    self.assertEqual(sum(tag == "main" for tag, _ in page.elements), 1)
                    labels = {attrs.get("for") for tag, attrs in page.elements if tag == "label"}
                    for tag, attrs in page.elements:
                        if tag in {"input", "select", "textarea"} and attrs.get("type") != "hidden":
                            self.assertTrue(
                                attrs.get("id") in labels
                                or attrs.get("aria-label")
                                or attrs.get("aria-labelledby"),
                                (route, attrs),
                            )

    def test_public_input_description_includes_rules_and_validation_error(self):
        for response, invalid in (
            (self.client.get(reverse("public")), False),
            (self.client.post(reverse("public"), {"part": "Q12", "prefix": "P", "digit": ""}), True),
        ):
            page = self.markup(response)
            elements = {attrs["id"]: attrs for _, attrs in page.elements if "id" in attrs}
            descriptions = elements["id_part"]["aria-describedby"].split()
            self.assertIn("id_part_helptext", descriptions)
            self.assertTrue(all(identifier in elements for identifier in descriptions))
            self.assertContains(
                response, "Cyfry mogą wystąpić wyłącznie na dwóch ostatnich pozycjach.", count=1
            )
            if invalid:
                self.assertIn("id_part_error", descriptions)
                self.assertEqual(elements["id_part"]["aria-invalid"], "true")
            else:
                self.assertNotIn("id_part_error", descriptions)

    def test_invalid_number_and_vin_are_linked_to_actual_fields_and_do_not_reserve(self):
        self.client.force_login(self.a)
        response = self.client.post(
            reverse("request_new"),
            {
                **data("INVALID"),
                "owner": "",
                "vin": "BAD",
                "count": "",
            },
        )
        page = self.markup(response)
        self.assertFalse(Request.objects.exists())
        elements = {attrs["id"]: attrs for _, attrs in page.elements if "id" in attrs}
        self.assertEqual(elements["form-errors"]["tabindex"], "-1")
        links = {attrs.get("href") for tag, attrs in page.elements if tag == "a"}
        for name in ["number", "vin", "owner"]:
            self.assertIn("#id_" + name, links)
            self.assertEqual(elements["id_" + name]["aria-invalid"], "true")
            self.assertIn("id_" + name + "_error", elements["id_" + name]["aria-describedby"])

    def test_individual_form_does_not_require_unused_pool_count(self):
        form = RequestForm(data={**data(), "count": ""})
        self.assertTrue(form.is_valid(), form.errors)
        self.client.force_login(self.a)
        response = self.client.post(reverse("request_new"), {**data(), "count": ""})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Request.objects.count(), 1)

    def test_pool_forms_still_require_valid_count_and_justification(self):
        for kind in ["II", "III"]:
            for count in ["", "0", "10001", "abc"]:
                with self.subTest(kind=kind, count=count):
                    form = RequestForm(data={"kind": kind, "case_number": "TEST", "count": count})
                    self.assertFalse(form.is_valid())
                    self.assertIn("count", form.errors)
                    self.assertIn("justification", form.errors)
            valid = RequestForm(
                data={
                    "kind": kind,
                    "case_number": "TEST",
                    "count": 2,
                    "justification": "Fikcyjne zapotrzebowanie",
                }
            )
            self.assertTrue(valid.is_valid(), valid.errors)

    def test_pool_confirmation_does_not_claim_individual_number_reservation(self):
        self.client.force_login(self.a)
        for kind in ["II", "III"]:
            response = self.client.post(
                reverse("request_new"),
                {
                    "kind": kind,
                    "case_number": "TEST/" + kind,
                    "count": 2,
                    "justification": "Fikcyjne zapotrzebowanie",
                },
                follow=True,
            )
            self.assertContains(response, "Wniosek o pulę zapisany; pismo PDF jest gotowe.")
            self.assertNotContains(response, "Wyróżnik zarezerwowany")
            req = Request.objects.get(kind=kind)
            self.assertIsNone(req.record_id)
            self.assertEqual(req.count, 2)

    def test_titles_of_request_record_pool_and_signature_identify_document_without_owner(self):
        req = create_request(self.a, data())
        pool = allocate_pool(
            self.ump,
            {"kind": "II", "office": "a", "prefix": "P", "start": 1, "end": 2, "valid_from": "2026-10-03"},
        )
        self.client.force_login(self.a)
        for route, identifier, expected in [
            ("request_detail", req.uuid, req.reference),
            ("record_detail", req.record.uuid, req.record.display_number),
            ("pool_detail", pool.uuid, pool.slots.first().number),
            ("letter_sign", req.letters.get().uuid, req.letters.get().number),
        ]:
            page = self.markup(self.client.get(reverse(route, args=[identifier])))
            self.assertIn(expected, page.title)
            self.assertNotIn(req.record.owner, page.title)

    def test_error_summary_is_absent_on_initial_form_and_html_is_escaped(self):
        self.client.force_login(self.a)
        self.assertNotContains(self.client.get(reverse("request_new")), 'id="form-errors"')
        response = self.client.post(
            reverse("request_new"),
            {
                **data("INVALID"),
                "owner": '<script>alert("fictional")</script>',
            },
        )
        self.assertNotContains(response, '<script>alert("fictional")</script>')
        self.assertFalse(Request.objects.exists())
