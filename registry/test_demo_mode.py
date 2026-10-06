"""Tryb demonstracyjny: wejście kodem demo, konta fikcyjne, ograniczony administrator, poczta demo."""

import tempfile
from pathlib import Path

from django.core import mail, signing
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.mail import EmailMessage
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from config.onprem import build_settings as build_onprem
from config.render import build_settings as build_render

from .account_invitations import process_invitation
from .accounts import remove_account
from .demo import DOMAIN
from .demo_mail import deliver
from .demo_setup import ensure_access_code, ensure_accounts, prepare
from .forms import account_settings_snapshot
from .models import (
    AccountInvitation,
    AuditLog,
    DemoAccessCode,
    DemoMessage,
    LoginCode,
    Office,
    PlateRecord,
    Pool,
    Request,
    User,
)
from .services import create_request, decide_request, send_request
from .test_onprem import OnPremConfigurationTests
from .test_render import RenderSettingsTests
from .tests import data, fixtures

LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


class DemoBase(TestCase):
    def setUp(self):
        self.admin, self.ump, self.a, self.b = fixtures()
        Office.objects.create(id="gni", name="Starostwo Powiatowe w Gnieźnie", kind="COUNTY", city="Gniezno")
        Office.objects.create(id="pil", name="Starostwo Powiatowe w Pile", kind="COUNTY", city="Piła")
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(
            override_settings(
                DEMO_MODE=True,
                DEMO_DIR=directory,
                EZDRP_CONFIG_FILE=str(directory / "ezdrp.json"),
                EDOR_CONFIG_FILE=str(directory / "edor.json"),
                SIGNING_CONFIG_FILE=str(directory / "signing.json"),
                EDOR_FIRST_CHECK_SECONDS=0,
                EMAIL_BACKEND=LOCMEM,
            )
        )
        self.demo = ensure_accounts()
        self.code = ensure_access_code().code

    def enter(self, key, client=None):
        client = client or self.client
        client.post(reverse("demo_login"), {"code": self.code})
        return client.post(reverse("demo_login"), {"account": key})


class DemoLoginTests(DemoBase):
    def test_flag_off_removes_entry_and_access_of_demo_accounts(self):
        user = self.demo["ump"]
        with override_settings(DEMO_MODE=False):
            self.assertEqual(self.client.get(reverse("demo_login")).status_code, 404)
            self.assertFalse(User.objects.get(pk=user.pk).access_allowed)
            self.client.force_login(user)
            response = self.client.get(reverse("dashboard"))
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("login_email"), response["Location"])

    def test_code_then_role_logs_in_and_role_can_be_switched(self):
        page = self.client.get(reverse("demo_login"))
        self.assertContains(page, "Kod dostępu demo")
        self.assertNotContains(page, "Urzędnik UMP")
        self.assertContains(self.client.post(reverse("demo_login"), {"code": "zly"}), "Niepoprawny kod")
        # Bez kodu wybór roli nie loguje.
        self.client.post(reverse("demo_login"), {"account": "ump"})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(
            self.client.post(reverse("demo_login"), {"code": self.code}), reverse("demo_login")
        )
        self.assertContains(self.client.get(reverse("demo_login")), "Urzędnik UMP")
        self.assertRedirects(
            self.client.post(reverse("demo_login"), {"account": "ump"}), reverse("dashboard")
        )
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "Instancja demonstracyjna")
        self.assertContains(page, "Skrzynka demo")
        self.assertTrue(AuditLog.objects.filter(action="auth.demo_login", actor=self.demo["ump"]).exists())
        self.client.post(reverse("demo_login"), {"account": "powiat-gniezno"})
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.demo["powiat-gniezno"].pk)

    def test_code_guessing_is_rate_limited_per_client(self):
        statuses = [
            self.client.post(reverse("demo_login"), {"code": f"zly-{n}"}).status_code for n in range(11)
        ]
        self.assertEqual(statuses, [200] * 10 + [429])
        self.assertEqual(self.client.post(reverse("demo_login"), {"code": self.code}).status_code, 429)
        other = Client(REMOTE_ADDR="203.0.113.5")
        self.assertRedirects(other.post(reverse("demo_login"), {"code": self.code}), reverse("demo_login"))

    def test_only_seeded_demo_accounts_can_be_entered_and_otp_ignores_them(self):
        self.client.post(reverse("demo_login"), {"code": self.code})
        for key in ("a", "admin", "nieznane"):
            self.client.post(reverse("demo_login"), {"account": key})
            self.assertNotIn("_auth_user_id", self.client.session)
        self.client.post(reverse("login_email"), {"email": f"ump@{DOMAIN}"})
        self.assertFalse(LoginCode.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_real_account_is_not_offered_demo_entry_and_keeps_otp(self):
        self.client.force_login(self.a)
        self.assertRedirects(self.client.get(reverse("demo_login")), reverse("dashboard"))
        # Konto rzeczywiste na instancji demo też czyta swoją korespondencję obiegu w skrzynce.
        DemoMessage.objects.create(recipient=self.a.email, subject="Dla konta rzeczywistego", body="x")
        self.assertContains(self.client.get(reverse("demo_inbox")), "Dla konta rzeczywistego")

    def test_changing_the_code_ends_unlocked_and_logged_in_demo_sessions(self):
        waiting, working = Client(), Client()
        waiting.post(reverse("demo_login"), {"code": self.code})
        self.enter("ump", working)
        self.assertEqual(working.get(reverse("dashboard")).status_code, 200)
        DemoAccessCode.objects.create(code="nowy-kod-po-pokazie")
        waiting.post(reverse("demo_login"), {"account": "ump"})
        self.assertNotIn("_auth_user_id", waiting.session)
        self.assertContains(waiting.get(reverse("demo_login")), "Kod dostępu demo")
        response = working.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login_email"), response["Location"])


class DemoAdminTests(DemoBase):
    def payload(self, user=None, **changes):
        values = {
            "email": f"nowy@{DOMAIN}",
            "first_name": "Nowy",
            "last_name": "Pokazowy",
            "role": "COUNTY",
            "office": "gni",
            "is_active": "on",
            "reason": "Fikcyjne konto demo",
        }
        if user:
            values["account_version"] = signing.dumps(
                account_settings_snapshot(user), salt="admin-account-version"
            )
        return {**values, **changes}

    def test_demo_admin_sees_and_changes_only_demo_accounts(self):
        self.enter("administrator")
        panel = self.client.get(reverse("admin_panel"))
        self.assertContains(panel, f"ump@{DOMAIN}")
        for hidden in ("admin@test.invalid", "a@test.invalid", self.code):
            self.assertNotContains(panel, hidden)
        forbidden = [
            reverse("admin_edit", args=["user", self.a.pk]),
            reverse("admin_edit", args=["user", self.demo["ump"].pk]),
            reverse("admin_edit", args=["office", "ump"]),
            reverse("admin_new", args=["office"]),
            reverse("admin_new", args=["template"]),
            reverse("admin_new", args=["flag"]),
            reverse("account_invitations", args=[self.a.pk]),
        ]
        for url in forbidden:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, self.payload()).status_code, 403)
        self.assertEqual(self.client.post(reverse("demo_code_rotate")).status_code, 404)
        job_uuid = "00000000-0000-0000-0000-000000000001"
        self.assertEqual(self.client.get(reverse("edor_resume", args=[job_uuid])).status_code, 403)
        url = reverse("admin_new", args=["user"])
        self.assertContains(self.client.post(url, self.payload(email="obcy@test.invalid")), "@demo.invalid")
        self.assertFalse(User.objects.filter(email="obcy@test.invalid").exists())

    def test_demo_admin_creates_and_removes_extra_demo_account(self):
        self.enter("administrator")
        self.assertRedirects(
            self.client.post(reverse("admin_new", args=["user"]), self.payload()), reverse("admin_panel")
        )
        user = User.objects.get(email=f"nowy@{DOMAIN}")
        process_invitation(AccountInvitation.objects.get(user=user).pk)
        self.assertEqual(AccountInvitation.objects.get(user=user).status, "LOCAL_SAVED")
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(self.client.get(reverse("demo_inbox")), f"nowy@{DOMAIN}")
        response = self.client.post(
            reverse("admin_edit", args=["user", user.pk]),
            {**self.payload(user), "action": "remove", "reason": "Koniec pokazu"},
            follow=True,
        )
        self.assertContains(response, "Konto usunięte")
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_real_admin_reads_and_rotates_access_code(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("admin_panel")), self.code)
        self.assertRedirects(self.client.post(reverse("demo_code_rotate")), reverse("admin_panel"))
        new = DemoAccessCode.objects.first().code
        self.assertNotEqual(new, self.code)
        visitor = Client()
        self.assertContains(visitor.post(reverse("demo_login"), {"code": self.code}), "Niepoprawny kod")
        self.assertRedirects(visitor.post(reverse("demo_login"), {"code": new}), reverse("demo_login"))
        self.client.force_login(self.ump)
        self.assertEqual(self.client.post(reverse("demo_code_rotate")).status_code, 403)


class DemoPrivacyTests(DemoBase):
    def test_demo_viewers_do_not_see_real_account_identity(self):
        User.objects.filter(pk=self.a.pk).update(first_name="Realna", last_name="Osoba")
        self.a.refresh_from_db()
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        self.enter("ump")
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertContains(page, "Konto urzędowe")
        for hidden in ("a@test.invalid", "Realna Osoba"):
            self.assertNotContains(page, hidden)
        decide_request(self.demo["ump"], req.uuid, True)
        audit = self.client.get(reverse("audit_list"))
        self.assertContains(audit, "Zapisano stanowisko UMP")
        for hidden in ("a@test.invalid", "Realna Osoba", "Utworzono wniosek"):
            self.assertNotContains(audit, hidden)
        # Konto rzeczywiste nadal widzi autora w pełni.
        self.client.force_login(self.ump)
        self.assertContains(self.client.get(reverse("request_detail", args=[req.uuid])), "a@test.invalid")

    def test_workflow_mail_never_leaves_the_demo_instance(self):
        recipients = [f"ump@{DOMAIN}", "kontakt@prawdziwy-urzad.example.org"]
        message = EmailMessage("Temat", "Treść od konta demo", "rejestr@example.org", list(recipients))
        message.attach("pismo.pdf", b"%PDF-1.4", "application/pdf")
        self.assertEqual(deliver(message), 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(sorted(DemoMessage.objects.values_list("recipient", flat=True)), sorted(recipients))
        self.assertEqual(DemoMessage.objects.first().attachments, ["pismo.pdf"])

    def test_invitations_to_real_accounts_still_use_real_mail(self):
        message = EmailMessage(
            "Konto", "Treść", "rejestr@example.org", [f"nowy@{DOMAIN}", "real@example.org"]
        )
        self.assertEqual(deliver(message, workflow=False), 1)
        self.assertEqual(mail.outbox[0].to, ["real@example.org"])
        self.assertEqual(DemoMessage.objects.get().recipient, f"nowy@{DOMAIN}")
        with override_settings(DEMO_MODE=False):
            deliver(EmailMessage("T", "B", "rejestr@example.org", [f"ump@{DOMAIN}"]))
        self.assertEqual(len(mail.outbox), 2)

    def test_demo_viewers_do_not_see_import_author_origin_or_closed_real_account(self):
        User.objects.filter(pk=self.a.pk).update(first_name="Realna", last_name="Osoba")
        self.a.refresh_from_db()
        req = create_request(self.a, data())
        send_request(self.a, req.uuid)
        AuditLog.objects.filter(object_type="Request").update(ip="198.51.100.77")
        remove_account(self.admin, self.a.pk, account_settings_snapshot(self.a), "Odejście")
        self.enter("ump")
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        for hidden in ("Realna Osoba", "198.51.100.77", "Adres IP"):
            self.assertNotContains(page, hidden)
        self.assertContains(page, "Konto urzędowe")
        self.client.force_login(self.ump)
        page = self.client.get(reverse("request_detail", args=[req.uuid]))
        self.assertContains(page, "Realna Osoba (konto usunięte)")
        self.assertContains(page, "198.51.100.77")

    def test_daily_request_quota_applies_to_demo_accounts_only(self):
        with override_settings(DEMO_DAILY_REQUESTS=1):
            create_request(self.demo["powiat-gniezno"], data("P1DEMO"))
            with self.assertRaisesRegex(ValidationError, "limit wniosków"):
                create_request(self.demo["powiat-pila"], data("P2DEMO"))
            create_request(self.a, data("P3DEMO"))

    def test_inbox_shows_own_and_office_messages_only(self):
        DemoMessage.objects.create(recipient=f"ump@{DOMAIN}", subject="Dla UMP", body="x")
        DemoMessage.objects.create(recipient=f"kontakt-gni@{DOMAIN}", subject="Dla urzędu Gniezno", body="x")
        DemoMessage.objects.create(recipient=f"powiat-pila@{DOMAIN}", subject="Dla Piły", body="x")
        self.enter("powiat-gniezno")
        page = self.client.get(reverse("demo_inbox"))
        self.assertContains(page, "Dla urzędu Gniezno")
        for hidden in ("Dla UMP", "Dla Piły"):
            self.assertNotContains(page, hidden)


class DemoProvisioningTests(DemoBase):
    def test_prepare_is_idempotent_and_keeps_office_domains(self):
        Office.objects.filter(pk="ump").update(allowed_domains=["example.org"])
        first = prepare()
        self.assertGreater(first, 0)
        counts = (User.objects.count(), Request.objects.count(), DemoAccessCode.objects.count())
        self.assertEqual(prepare(), 0)
        self.assertEqual(
            (User.objects.count(), Request.objects.count(), DemoAccessCode.objects.count()), counts
        )
        # Dane pokazowe nie mnożą się także wtedy, gdy konta wejściowe trzeba było odtworzyć.
        for key in ("powiat-gniezno", "powiat-pila"):
            user = User.objects.get(email=f"{key}@{DOMAIN}")
            remove_account(self.admin, user.pk, account_settings_snapshot(user), "Odtworzenie konta")
        pools = Pool.objects.count()
        prepare()
        prepare()
        self.assertEqual(Pool.objects.count(), pools)
        self.assertTrue(User.objects.get(email=f"powiat-gniezno@{DOMAIN}").access_allowed)
        self.assertEqual(Office.objects.get(pk="ump").allowed_domains, ["example.org"])
        office = Office.objects.get(pk="gni")
        self.assertTrue(office.active and office.ade.startswith("AE:PL-") and office.email.endswith(DOMAIN))
        for name in ("ezdrp.json", "edor.json", "signing.json"):
            self.assertEqual((Path(self.settings_dir()) / name).stat().st_mode & 0o777, 0o600)

    def pool(self, user, office, start, end):
        from django.utils import timezone

        from .services import allocate_pool

        data = {"kind": "II", "office": office, "prefix": "P", "start": start, "end": end}
        return allocate_pool(user, {**data, "valid_from": timezone.localdate()})

    def test_legacy_demo_pool_is_merged_without_leaving_a_numbering_gap(self):
        from .integrations import enqueue
        from .number_checks import suggest_pool_range

        # Stan instancji Render: dawna pula 30, potem pule 1000 dołożone przez prepare_demo.
        legacy = self.pool(self.demo["ump"], "gni", 1, 30)
        enqueue(self.demo["ump"], legacy.letters.get(), "SMTP")
        big = self.pool(self.demo["ump"], "gni", 31, 1030)
        pila = self.pool(self.demo["ump"], "pil", 1031, 2030)
        prepare()
        self.assertFalse(Pool.objects.filter(pk__in=[legacy.pk, big.pk]).exists())
        merged = Pool.objects.get(office_id="gni", kind="II")
        self.assertEqual((merged.start, merged.end, merged.slots.count()), (1, 1030, 1030))
        self.assertEqual(merged.letters.filter(kind="POOL").count(), 1)
        self.assertTrue(Pool.objects.filter(pk=pila.pk).exists())
        self.assertEqual(AuditLog.objects.filter(action="pool.demo_removed").count(), 2)
        # UMP nadal przydziela kolejne pule modułu II bez blokady kolejności układów.
        span = suggest_pool_range("II", "P", 50)
        self.pool(self.demo["ump"], "pil", *span)
        prepare()
        self.assertEqual(AuditLog.objects.filter(action="pool.demo_removed").count(), 2)

    def test_last_legacy_pool_is_removed_and_real_pools_stay(self):
        real = self.pool(self.ump, "gni", 1, 30)
        legacy = self.pool(self.demo["ump"], "gni", 31, 60)
        prepare()
        self.assertFalse(Pool.objects.filter(pk=legacy.pk).exists())
        self.assertTrue(Pool.objects.filter(pk=real.pk).exists())

    def test_legacy_pool_followed_by_real_pool_is_left_alone(self):
        legacy = self.pool(self.demo["ump"], "gni", 1, 30)
        self.pool(self.ump, "pil", 31, 60)
        prepare()
        self.assertTrue(Pool.objects.filter(pk=legacy.pk).exists())
        self.assertFalse(AuditLog.objects.filter(action="pool.demo_removed").exists())

    def test_demo_pools_have_realistic_size_and_a_sold_vehicle_awaits_ump(self):
        from django.db.models import Count

        prepare()
        sizes = {
            (pool.office_id, pool.kind): pool.size for pool in Pool.objects.annotate(size=Count("slots"))
        }
        self.assertEqual(sizes, {("gni", "II"): 1000, ("pil", "II"): 1000, ("gni", "III"): 1000})
        sold = PlateRecord.objects.get(number="P7ZBYT")
        self.assertEqual((sold.status, sold.office_id), ("SOLD", "gni"))
        prepare()
        self.assertEqual(Pool.objects.count(), 3)

    def settings_dir(self):
        from django.conf import settings

        return settings.DEMO_DIR

    def test_existing_contact_and_address_are_not_overwritten(self):
        Office.objects.filter(pk="pil").update(ade="AE:PL-11111-22222-ABCDE-33", email="realny@example.org")
        ensure_accounts()
        office = Office.objects.get(pk="pil")
        self.assertEqual((office.ade, office.email), ("AE:PL-11111-22222-ABCDE-33", "realny@example.org"))


class DemoProfileFlagTests(RenderSettingsTests):
    def test_render_accepts_flag_only_when_it_names_this_host(self):
        demo = {**self.environment, "DYNA_DEMO": "rejestr.example.org"}
        build_render(demo, self.current)
        for name in ("EZDRP_CONFIG_FILE", "EDOR_CONFIG_FILE", "SIGNING_CONFIG_FILE"):
            with self.subTest(name=name), self.assertRaisesRegex(ImproperlyConfigured, "symulatorach"):
                build_render({**demo, name: "/var/data/prawdziwy.json"}, self.current)
        for value in ("1", "inna.example.org"):
            with self.subTest(value=value), self.assertRaises(ImproperlyConfigured):
                build_render({**self.environment, "DYNA_DEMO": value}, self.current)


class DemoOnPremFlagTests(OnPremConfigurationTests):
    def test_office_installation_refuses_demo_mode(self):
        with self.assertRaisesRegex(ImproperlyConfigured, "demonstracyjnego"):
            build_onprem({**self.environment, "DYNA_DEMO": "rejestr.example.org"}, self.current)
        with self.assertRaisesRegex(ImproperlyConfigured, "demonstracyjnego"):
            build_onprem(self.environment, {**self.current, "DEMO_MODE": True})
