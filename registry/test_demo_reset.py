"""Czyszczenie danych instancji demonstracyjnej: przycisk administratora i reset przy starcie."""

from io import StringIO

from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse

from .demo import DOMAIN
from .demo_setup import reset_data
from .models import (
    AccountInvitation,
    AuditLog,
    DemoAccessCode,
    DemoMessage,
    FlaggedWord,
    NumberSequence,
    Office,
    PlateRecord,
    Pool,
    Request,
    User,
)
from .services import allocate_block, create_request, decide_request, send_request
from .test_demo_mode import DemoBase
from .tests import data


class DemoResetTests(DemoBase):
    def dirty(self):
        req = create_request(self.demo["powiat-gniezno"], data("P1RAFAL"))
        send_request(self.demo["powiat-gniezno"], req.uuid)
        decide_request(self.demo["ump"], req.uuid, True)
        allocate_block(self.demo["ump"], "II", "gni")
        DemoMessage.objects.create(recipient=f"ump@{DOMAIN}", subject="Stara", body="Treść")
        FlaggedWord.objects.create(word="ABC")
        extra = User.objects.create_user(
            username=f"dodatkowe@{DOMAIN}", email=f"dodatkowe@{DOMAIN}", role="COUNTY", office_id="gni"
        )
        AccountInvitation.objects.create(
            user=extra,
            created_by=self.demo["administrator"],
            email=extra.email,
            account_context={},
            subject="Konto",
            body="Treść",
            content_sha256="0" * 64,
        )
        return extra

    def test_reset_removes_cases_and_history_and_reseeds_demo_data(self):
        extra = self.dirty()
        code = DemoAccessCode.objects.first()
        counts = reset_data(self.admin, "Przed prezentacją", "192.0.2.9")
        self.assertGreater(counts["requests"], 0)
        self.assertFalse(PlateRecord.objects.filter(number="P1RAFAL").exists())
        self.assertFalse(DemoMessage.objects.filter(subject="Stara").exists())
        self.assertFalse(User.objects.filter(pk=extra.pk).exists())
        # Liczniki od nowa: pierwsza pula automatyczna po resecie znów zaczyna się od M001.
        self.assertFalse(Pool.objects.filter(prefix="M").exists())
        self.assertFalse(NumberSequence.objects.filter(scope__startswith="POOL.").exists())
        self.assertEqual(allocate_block(self.demo["ump"], "II", "gni").slots.first().number, "M001")
        # Dane pokazowe są wgrane ponownie, a pierwszy wpis dziennika opisuje reset.
        self.assertTrue(Request.objects.exists())
        self.assertTrue(Pool.objects.filter(prefix="P").exists())
        event = AuditLog.objects.filter(action="demo.reset").get()
        self.assertEqual(
            (event.actor, event.reason, event.ip), (self.admin, "Przed prezentacją", "192.0.2.9")
        )
        self.assertFalse(AuditLog.objects.filter(created_at__lt=event.created_at).exists())
        # Zostaje konfiguracja i konta rzeczywiste.
        self.assertEqual(DemoAccessCode.objects.first(), code)
        self.assertTrue(FlaggedWord.objects.filter(word="ABC").exists())
        self.assertTrue(User.objects.filter(pk__in=[self.admin.pk, self.ump.pk, self.a.pk]).count() == 3)
        self.assertTrue(Office.objects.filter(pk="a").exists())
        self.assertTrue(all(User.objects.filter(email=f"{key}@{DOMAIN}").exists() for key in self.demo))

    def test_real_admin_resets_from_panel_with_reason_and_confirmation(self):
        self.dirty()
        url = reverse("demo_reset")
        self.client.force_login(self.admin)
        panel = self.client.get(reverse("admin_panel"))
        self.assertContains(panel, "Wyczyść dane demo")
        for payload in ({"reason": "Test"}, {"confirm": "1"}, {"reason": " ", "confirm": "1"}):
            with self.subTest(payload=payload):
                response = self.client.post(url, payload, follow=True)
                self.assertContains(response, "Podaj powód i potwierdź")
                self.assertTrue(PlateRecord.objects.filter(number="P1RAFAL").exists())
        response = self.client.post(url, {"reason": "Przed prezentacją", "confirm": "1"}, follow=True)
        self.assertRedirects(response, reverse("admin_panel"))
        self.assertContains(response, "Dane demo wyczyszczone")
        self.assertFalse(PlateRecord.objects.filter(number="P1RAFAL").exists())

    def test_demo_admin_resets_but_other_roles_and_flag_off_cannot(self):
        self.dirty()
        url = reverse("demo_reset")
        payload = {"reason": "Próba", "confirm": "1"}
        self.client.force_login(self.ump)
        self.assertEqual(self.client.post(url, payload).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 405)
        with override_settings(DEMO_MODE=False):
            self.assertEqual(self.client.post(url, payload).status_code, 404)
        self.assertTrue(PlateRecord.objects.filter(number="P1RAFAL").exists())
        self.assertFalse(AuditLog.objects.filter(action="demo.reset").exists())
        visitor = Client()
        self.enter("administrator", visitor)
        panel = visitor.get(reverse("admin_panel"))
        self.assertContains(panel, "Wyczyść dane demo")
        self.assertNotContains(panel, self.code)
        response = visitor.post(url, {"reason": "Przed prezentacją", "confirm": "1"}, follow=True)
        self.assertContains(response, "Dane demo wyczyszczone")
        self.assertFalse(PlateRecord.objects.filter(number="P1RAFAL").exists())
        event = AuditLog.objects.get(action="demo.reset")
        self.assertEqual(event.actor, self.demo["administrator"])
        # Konto demo administratora zostaje, a sesja recenzenta działa dalej.
        self.assertEqual(visitor.get(reverse("admin_panel")).status_code, 200)

    def test_startup_token_resets_once(self):
        self.dirty()
        with override_settings(DEMO_RESET_TOKEN="2026-10-29"):
            out = StringIO()
            call_command("prepare_demo", stdout=out)
            self.assertIn("Dane demo wyczyszczone przy starcie", out.getvalue())
            self.assertFalse(PlateRecord.objects.filter(number="P1RAFAL").exists())
            event = AuditLog.objects.get(action="demo.reset")
            self.assertIsNone(event.actor)
            self.assertEqual(event.after["token"], "2026-10-29")
            create_request(self.demo["powiat-gniezno"], data("P1NOWY"))
            out = StringIO()
            call_command("prepare_demo", stdout=out)
            self.assertIn("Tryb demo gotowy", out.getvalue())
            self.assertTrue(PlateRecord.objects.filter(number="P1NOWY").exists())
        with override_settings(DEMO_RESET_TOKEN=""):
            call_command("prepare_demo", stdout=StringIO())
            self.assertEqual(AuditLog.objects.filter(action="demo.reset").count(), 1)
