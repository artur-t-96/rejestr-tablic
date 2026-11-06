"""Uwagi UMP z 06.11.2026: nazwa, wniosek bez zbędnych pól, bez rezerwacji, wyszukiwarka,
administrator powiatu i funkcje w przygotowaniu."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .accounts import remove_account
from .forms import account_settings_snapshot
from .models import Office, PlateRecord, Pool, Request, User
from .services import allocate_block, create_request, decide_request, send_request, withdraw_request
from .test_demo_mode import DemoBase
from .tests import data, fixtures


class NameAndTextTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_new_name_everywhere_and_no_old_slogan(self):
        public = self.client.get("/")
        self.assertContains(public, "<title>Sprawdź dostępność tablicy · Sprawdź Tablicę</title>", html=False)
        self.client.force_login(self.a)
        pages = [public, self.client.get(reverse("dashboard")), self.client.get(reverse("request_new"))]
        for page in pages:
            text = page.content.decode()
            self.assertIn("Sprawdź Tablicę", text)
            for old in ("Dyna Rejestr", "Wielkopolska · serwis publiczny", "Rejestr Tablic · Wielkopolska"):
                self.assertNotIn(old, text)
        letter = create_request(self.a, data()).letters.get()
        self.assertNotIn("Dyna", letter.body)

    def test_request_form_has_no_removed_fields(self):
        self.client.force_login(self.a)
        page = self.client.get(reverse("request_new"))
        for name in ("owner", "address", "vin", "case_number", "station"):
            self.assertNotContains(page, f'name="{name}"')
        for label in ("Właściciel", "Adres właściciela", "VIN", "Numer sprawy", "Stacja"):
            self.assertNotContains(page, label)

    def test_individual_request_without_owner_data_is_saved(self):
        self.client.force_login(self.a)
        response = self.client.post(reverse("request_new"), {"kind": "I", "number": "P0NOWY"})
        self.assertEqual(response.status_code, 302)
        req = Request.objects.get()
        self.assertEqual((req.case_number, req.record.owner, req.record.vin), ("", "", ""))
        detail = self.client.get(reverse("request_detail", args=[req.uuid]))
        for label in ("Właściciel", "VIN", "Rezerwacja", "rezerwac"):
            self.assertNotContains(detail, label)
        listing = self.client.get(reverse("requests_list"))
        self.assertNotContains(listing, "rezerwacja do")
        export = self.client.get(reverse("export_records"), {"co": "wnioski"}).content.decode()
        self.assertNotIn("case_number", export.splitlines()[0])


class NoReservationTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_number_stays_taken_until_decision_without_deadline(self):
        req = create_request(self.a, data())
        self.assertIsNone(req.record.reservation_until)
        with self.assertRaisesMessage(ValidationError, "zajęty"):
            create_request(self.b, data())
        send_request(self.a, req.uuid)
        decide_request(self.ump, req.uuid, False, "Odmowa testowa")
        # Po odmowie numer jest wolny dla kolejnego wniosku.
        self.assertTrue(create_request(self.b, data()).record_id)

    def test_withdrawal_frees_number(self):
        req = create_request(self.a, data())
        withdraw_request(self.a, req.uuid, "Rezygnacja")
        self.assertEqual(PlateRecord.objects.get(pk=req.record_id).status, "RELEASED")
        self.assertTrue(create_request(self.b, data()).record_id)

    def test_new_request_page_does_not_mention_reservation(self):
        self.client.force_login(self.a)
        page = self.client.get(reverse("request_new"))
        self.assertNotContains(page, "14 dni")
        self.assertNotContains(page, "rezerw")
        response = self.client.post(reverse("request_new"), data(), follow=True)
        self.assertNotContains(response, "rezerw")


class NumberSearchTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        self.mine = create_request(self.a, data("P0SZUK"))
        self.foreign = create_request(self.b, data("P1SZUK"))
        self.pool_req = create_request(self.a, {"kind": "II", "count": 10, "justification": "Test"})
        send_request(self.a, self.pool_req.uuid)
        decide_request(self.ump, self.pool_req.uuid, True)
        self.foreign_pool = allocate_block(self.ump, "III", "b", 10)

    def search(self, user, q):
        self.client.force_login(user)
        return self.client.get(reverse("number_search"), {"q": q})

    def test_county_finds_own_individual_and_pool_numbers_by_fragment(self):
        page = self.search(self.a, "szuk")
        self.assertContains(page, "P0 SZUK")
        self.assertContains(page, reverse("request_detail", args=[self.mine.uuid]))
        self.assertNotContains(page, "P1 SZUK")
        page = self.search(self.a, "M00")
        self.assertContains(page, "M005")
        self.assertContains(page, "Pula tablic zmniejszonych")
        self.assertContains(page, reverse("request_detail", args=[self.pool_req.uuid]))
        self.assertNotContains(page, "M00005")

    def test_foreign_numbers_never_appear_for_county_but_ump_sees_all(self):
        page = self.search(self.a, "M0000")
        self.assertNotContains(page, "M00001")
        page = self.search(self.ump, "M0000")
        self.assertContains(page, "M00001")
        self.assertContains(page, reverse("pool_detail", args=[self.foreign_pool.uuid]))
        self.assertContains(self.search(self.ump, "P1 SZUK"), "P1 SZUK")

    def test_admin_and_anonymous_have_no_access(self):
        self.assertEqual(self.client.get(reverse("number_search")).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("number_search")).status_code, 403)

    def test_empty_and_unknown_queries(self):
        self.assertNotContains(self.search(self.a, ""), "Brak numerów")
        self.assertContains(self.search(self.a, "QQQ"), "Brak numerów pasujących")


class CountyAdminTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        Office.objects.filter(pk__in=["a", "b"]).update(allowed_domains=["test.invalid"])
        self.a.county_admin = True
        self.a.save()
        self.clerk = User.objects.create_user(
            username="clerk@test.invalid", email="clerk@test.invalid", role="COUNTY", office_id="a"
        )

    def test_only_one_county_admin_per_office(self):
        self.clerk.county_admin = True
        with self.assertRaisesMessage(ValidationError, "tylko jeden"):
            self.clerk.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.clerk.pk).update(county_admin=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.ump.pk).update(county_admin=True)

    def test_central_admin_assigns_role_in_admin_form(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("admin_edit", args=["user", self.b.pk]))
        self.assertContains(page, "Administrator powiatu")
        values = {
            "email": self.b.email,
            "first_name": "",
            "last_name": "",
            "role": "COUNTY",
            "office": "b",
            "county_admin": "on",
            "is_active": "on",
            "reason": "Nadanie roli",
            "account_version": page.context["form"].initial["account_version"],
        }
        self.assertEqual(self.client.post(reverse("admin_edit", args=["user", self.b.pk]), values).status_code, 302)
        self.b.refresh_from_db()
        self.assertTrue(self.b.county_admin)

    def test_county_admin_creates_edits_blocks_and_removes_own_clerks(self):
        self.client.force_login(self.a)
        listing = self.client.get(reverse("county_accounts"))
        self.assertContains(listing, "clerk@test.invalid")
        self.assertNotContains(listing, self.b.email)
        self.assertContains(self.client.get(reverse("dashboard")), "Użytkownicy powiatu")
        response = self.client.post(
            reverse("county_account_new"),
            {"email": "nowy@test.invalid", "first_name": "Nowy", "last_name": "Urzędnik", "is_active": "on",
             "reason": "Nowy pracownik"},
        )
        self.assertEqual(response.status_code, 302, response.content)
        created = User.objects.get(email="nowy@test.invalid")
        self.assertEqual((created.role, created.office_id, created.county_admin), ("COUNTY", "a", False))
        page = self.client.get(reverse("county_account_edit", args=[self.clerk.pk]))
        version = page.context["form"].initial["account_version"]
        response = self.client.post(
            reverse("county_account_edit", args=[self.clerk.pk]),
            {"email": self.clerk.email, "first_name": "Zablokowany", "last_name": "", "reason": "Blokada",
             "account_version": version},
        )
        self.assertEqual(response.status_code, 302, response.content)
        self.clerk.refresh_from_db()
        self.assertFalse(self.clerk.is_active)
        remove_account(self.a, created.pk, account_settings_snapshot(created), "Pomyłka")
        self.assertFalse(User.objects.filter(email="nowy@test.invalid").exists())

    def test_county_admin_cannot_touch_other_offices_or_central_settings(self):
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(reverse("county_account_edit", args=[self.b.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("county_account_edit", args=[self.ump.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("admin_panel")).status_code, 403)
        with self.assertRaises(PermissionDenied):
            remove_account(self.a, self.b.pk, account_settings_snapshot(self.b), "Cudze konto")
        # Pole roli i urzędu nie istnieje w formularzu powiatu; próba podmiany zostaje zignorowana.
        self.client.post(
            reverse("county_account_new"),
            {"email": "obcy@test.invalid", "role": "MAIN", "office": "b", "county_admin": "on",
             "is_active": "on", "reason": "Próba"},
        )
        created = User.objects.get(email="obcy@test.invalid")
        self.assertEqual((created.role, created.office_id, created.county_admin), ("COUNTY", "a", False))

    def test_regular_clerk_and_ump_have_no_county_accounts(self):
        for user in (self.clerk, self.ump):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("county_accounts")).status_code, 403)
            self.assertNotContains(self.client.get(reverse("dashboard")), "Użytkownicy powiatu")

    def test_county_admin_keeps_clerk_work(self):
        self.client.force_login(self.a)
        self.assertEqual(self.client.post(reverse("request_new"), data()).status_code, 302)

    def test_county_admin_cannot_block_self(self):
        self.client.force_login(self.a)
        page = self.client.get(reverse("county_account_edit", args=[self.a.pk]))
        self.assertNotContains(page, "Usuń konto")
        self.client.post(
            reverse("county_account_edit", args=[self.a.pk]),
            {"email": self.a.email, "first_name": "", "last_name": "", "reason": "Blokada",
             "account_version": page.context["form"].initial["account_version"]},
        )
        self.a.refresh_from_db()
        self.assertTrue(self.a.is_active)


class PreparingFeatureTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()

    def test_orders_tile_and_disabled_order_button(self):
        self.client.force_login(self.a)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, "Zamówienia")
        self.assertNotContains(dashboard, "Wysyłka tablic")
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        decide_request(self.ump, req.uuid, True)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertContains(page, "Zamów u producenta")
        self.assertContains(page, 'disabled aria-disabled="true"')
        self.assertContains(page, "Funkcja w przygotowaniu")

    def test_services_plates_are_visible_but_refused(self):
        self.client.force_login(self.a)
        page = self.client.get(reverse("request_new"))
        self.assertContains(page, "Tablice dla służb")
        response = self.client.post(reverse("request_new"), {"kind": "SLUZBY", "count": "10", "justification": "x"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "w przygotowaniu")
        api = self.client.post(
            "/api/requests/", {"kind": "SLUZBY", "justification": "x"}, content_type="application/json"
        )
        self.assertEqual(api.status_code, 400)
        with self.assertRaises(ValidationError):
            create_request(self.a, {"kind": "SLUZBY", "count": 10, "justification": "x"})
        self.assertFalse(Request.objects.exists())
        self.assertFalse(Pool.objects.exists())


class DecisionNoticeTextTests(TestCase):
    def test_status_label_has_no_local_mailbox_wording(self):
        from .models import IntegrationJob

        label = IntegrationJob(status="LOCAL_SAVED").status_label
        self.assertNotIn("lokaln", label)
        job = IntegrationJob(payload=b'{"to": "autor@test.invalid"}')
        self.assertEqual(job.notice_recipient, "autor@test.invalid")
        self.assertEqual(IntegrationJob(payload=b"[]").notice_recipient, "")


class DemoCountyAdminTests(DemoBase):
    def test_demo_county_admin_never_sees_or_changes_real_accounts(self):
        admin = self.demo["admin-gniezno"]
        self.assertTrue(admin.county_admin)
        real = User.objects.create_user(
            username="real@example.invalid", email="real@example.invalid", role="COUNTY", office_id="gni"
        )
        self.enter("admin-gniezno")
        listing = self.client.get(reverse("county_accounts"))
        self.assertEqual(listing.status_code, 200)
        self.assertNotContains(listing, real.email)
        self.assertContains(listing, "powiat-gniezno@demo.invalid")
        self.assertEqual(self.client.get(reverse("county_account_edit", args=[real.pk])).status_code, 404)
        seeded = self.demo["powiat-gniezno"]
        self.assertEqual(self.client.get(reverse("county_account_edit", args=[seeded.pk])).status_code, 404)
        response = self.client.post(
            reverse("county_account_new"),
            {"email": "zewn@example.invalid", "is_active": "on", "reason": "Próba"},
        )
        self.assertContains(response, "@demo.invalid")
        self.assertFalse(User.objects.filter(email="zewn@example.invalid").exists())
