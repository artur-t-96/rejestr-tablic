from datetime import timedelta

from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Request
from .services import allocate_pool, create_request, decide_request, send_request
from .tests import data, fixtures


class PoolRequestRoleTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.county, self.other = fixtures()

    def pool_data(self, kind):
        return {
            "kind": kind,
            "count": 2,
            "case_number": f"ROLE/{kind}",
            "justification": "Fikcyjny odbiór uprawnień do wniosku o pulę",
        }

    def snapshot(self):
        return {
            model._meta.label: list(model.objects.order_by("pk").values())
            for model in apps.get_app_config("registry").get_models()
        }

    def add_expired_reservation(self):
        req = create_request(self.county, data("P0STARY"))
        req.record.reservation_until = timezone.now() - timedelta(days=1)
        req.record.save(update_fields=["reservation_until"])

    def test_main_pool_service_denies_before_expiry_numbering_or_documents(self):
        self.add_expired_reservation()
        before = self.snapshot()
        for kind in ("II", "III"):
            with self.subTest(kind=kind), self.assertRaises(PermissionDenied):
                create_request(self.ump, self.pool_data(kind))
            self.assertEqual(self.snapshot(), before)

    def test_main_pool_api_and_forged_html_posts_are_forbidden_without_writes(self):
        self.add_expired_reservation()
        self.client.force_login(self.ump)
        before = self.snapshot()
        for kind in ("II", "III"):
            for path, content_type in (
                ("/api/requests/", "application/json"),
                (reverse("request_new"), "multipart/form-data"),
            ):
                with self.subTest(kind=kind, path=path):
                    kwargs = {"content_type": content_type} if content_type == "application/json" else {}
                    response = self.client.post(path, self.pool_data(kind), **kwargs)
                    self.assertEqual(response.status_code, 403, response.content)
                    self.assertEqual(self.snapshot(), before)

    def test_main_form_offers_individual_only_even_with_pool_query_parameter(self):
        self.client.force_login(self.ump)
        for kind in ("I", "II", "III"):
            with self.subTest(kind=kind):
                response = self.client.get(reverse("request_new"), {"kind": kind})
                self.assertEqual(response.status_code, 200)
                form = response.context["form"]
                self.assertEqual([value for value, _label in form.fields["kind"].choices], ["I"])
                self.assertEqual(form["kind"].value(), "I")
                self.assertNotIn("count", form.fields)
                self.assertNotIn("station", form.fields)

    def test_county_form_keeps_all_modules_and_pool_link(self):
        self.client.force_login(self.county)
        response = self.client.get(reverse("request_new"), {"kind": "III"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [value for value, _label in response.context["form"].fields["kind"].choices],
            ["I", "II", "III"],
        )
        self.assertEqual(response.context["form"]["kind"].value(), "III")
        response = self.client.get(reverse("pools_list"))
        self.assertContains(response, "Wniosek o pulę")

    def test_main_pool_list_has_allocation_without_pool_application_link(self):
        self.client.force_login(self.ump)
        response = self.client.get(reverse("pools_list"))
        self.assertNotContains(response, "Wniosek o pulę")
        self.assertContains(response, "Przydziel pulę")

    def test_main_individual_html_and_api_still_create_for_main_office(self):
        self.client.force_login(self.ump)
        for index, path in enumerate((reverse("request_new"), "/api/requests/")):
            with self.subTest(path=path):
                values = data(f"P{index}WLASN")
                kwargs = {"content_type": "application/json"} if index else {}
                response = self.client.post(path, values, **kwargs)
                self.assertEqual(response.status_code, 201 if index else 302, response.content)
                req = Request.objects.get(record__number=values["number"])
                self.assertEqual((req.office_id, req.author_id), (self.ump.office_id, self.ump.pk))
                self.assertEqual(req.letters.get(kind="APPLICATION").office_id, self.ump.office_id)

    def test_county_pool_html_and_api_still_create_and_main_can_decide(self):
        for kind, prefix in (("II", "P"), ("III", "P0")):
            for api in (False, True):
                with self.subTest(kind=kind, api=api):
                    self.client.force_login(self.county)
                    values = self.pool_data(kind)
                    values["case_number"] += f"/{api}"
                    response = self.client.post(
                        "/api/requests/" if api else reverse("request_new"),
                        values,
                        **({"content_type": "application/json"} if api else {}),
                    )
                    self.assertEqual(response.status_code, 201 if api else 302, response.content)
                    req = Request.objects.get(case_number=values["case_number"])
                    self.assertEqual((req.office_id, req.author_id), (self.county.office_id, self.county.pk))
                    send_request(self.county, req.uuid)
                    start = 3 if api else 1
                    decide_request(
                        self.ump,
                        req.uuid,
                        True,
                        pool_data={
                            "prefix": prefix,
                            "start": start,
                            "end": start + 1,
                            "valid_from": timezone.localdate(),
                            "valid_until": timezone.localdate() + timedelta(days=30),
                        },
                    )
                    req.refresh_from_db()
                    self.assertEqual(req.status, "APPROVED")
                    self.assertEqual(req.letters.get(kind="POOL").pool.office_id, self.county.office_id)

    def test_main_direct_module_ii_allocation_remains_allowed(self):
        pool = allocate_pool(
            self.ump,
            {
                "kind": "II",
                "office": self.county.office_id,
                "prefix": "P",
                "start": 1,
                "end": 2,
                "valid_from": timezone.localdate(),
            },
        )
        self.assertEqual(pool.office_id, self.county.office_id)
        self.assertEqual(pool.slots.count(), 2)

    def test_main_cannot_submit_existing_pool_drafts_including_legacy_main_draft(self):
        for kind in ("II", "III"):
            for author in (self.county, self.ump):
                with self.subTest(kind=kind, author=author.role):
                    req = Request.objects.create(office=author.office, author=author, **self.pool_data(kind))
                    before = self.snapshot()
                    with self.assertRaises(PermissionDenied):
                        send_request(self.ump, req.uuid)
                    self.assertEqual(self.snapshot(), before)

    def test_main_cannot_submit_pool_draft_via_html_or_api_and_button_is_hidden(self):
        self.client.force_login(self.ump)
        for kind in ("II", "III"):
            req = create_request(self.county, self.pool_data(kind))
            response = self.client.get(reverse("request_detail", args=[req.uuid]))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Złóż wniosek do UMP")
            before = self.snapshot()
            for path in (
                reverse("request_action", args=[req.uuid, "submit"]),
                f"/api/requests/{req.uuid}/submit/",
            ):
                with self.subTest(kind=kind, path=path):
                    kwargs = {"content_type": "application/json"} if path.startswith("/api/") else {}
                    response = self.client.post(path, {}, **kwargs)
                    self.assertEqual(response.status_code, 403, response.content)
                    self.assertEqual(self.snapshot(), before)
