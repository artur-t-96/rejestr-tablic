"""Pełny obieg przez wbudowane symulatory tymi samymi funkcjami, których używa produkcja."""

from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .connectors.edor import load_profile as load_edor
from .connectors.ezdrp import ConnectorError
from .connectors.ezdrp import load_profile as load_ezd
from .demo import DOMAIN
from .demo_setup import write_profiles
from .ezd_incoming import publish_incoming_link, sync_incoming
from .integrations import SIMULATOR_MODE, configuration_status, enqueue, enqueue_ezd, process_job
from .models import DemoMessage, EZDIncomingDocument, IntegrationJob, Letter, SimulatorObject
from .services import create_request, decide_request, send_request
from .signatures import load_profile as load_signing
from .signatures import sign_letter
from .test_demo_mode import DemoBase
from .tests import data


class SimulatorFlowTests(DemoBase):
    def setUp(self):
        super().setUp()
        write_profiles()
        self.county, self.ump_demo = self.demo["powiat-gniezno"], self.demo["ump"]

    def run_job(self, job):
        """Kolejka: przyjęcie zadania, a po odstępie obserwatora status i dowody."""
        job = process_job(job)
        while job.status == "MONITORING":
            IntegrationJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now())
            job = process_job(IntegrationJob.objects.get(pk=job.pk))
        return job

    def test_application_goes_to_ump_and_decision_returns_with_evidence(self):
        req = create_request(self.county, data("P3SYM"))
        application = req.letters.get(kind="APPLICATION")
        sign_letter(self.county, application, reason="Podpis demonstracyjny")
        application.refresh_from_db()
        self.assertEqual(application.signature_status, "TEST_SIGNED")
        send_request(self.county, req.uuid)

        job = self.run_job(enqueue(self.county, application, "EDOR"))
        self.assertEqual(job.status, "EDOR_DELIVERED")
        self.assertEqual(job.result["environment"], "SYMULATOR")
        evidence = {item.kind: bytes(item.content).decode() for item in job.evidence.all()}
        self.assertEqual(set(evidence), {"A.1", "E.1"})
        self.assertTrue(all("SYMULACJA" in content for content in evidence.values()))

        # Pismo „wpłynęło” do EZD w UMP; urzędnik odczytuje nowe wpływy bez wpisywania numeru.
        found, rows = sync_incoming(self.ump_demo, reason="Odczyt testowy")
        self.assertEqual((found, len(rows)), (1, 1))
        row = rows[0]
        self.assertEqual((row.status, row.letter_id), ("MATCHED", application.pk))
        self.assertTrue(row.request_url.endswith(reverse("request_detail", args=[req.uuid])))
        self.assertEqual(sync_incoming(self.ump_demo, reason="Ponownie")[0], 0)
        self.assertEqual(
            publish_incoming_link(self.ump_demo, row.uuid, reason="Link").link_status, "PUBLISHED"
        )

        decide_request(self.ump_demo, req.uuid, True)
        approval = req.letters.get(kind="APPROVAL")
        ezd_job = self.run_job(enqueue_ezd(self.ump_demo, approval, case_number=1, reason="Nowa sprawa demo"))
        self.assertEqual(ezd_job.status, "REGISTERED")
        self.assertTrue(Letter.objects.get(pk=approval.pk).ezd_id.startswith("SIM-DOK-"))
        self.assertEqual(self.run_job(enqueue(self.ump_demo, approval, "EDOR")).status, "EDOR_DELIVERED")
        found, rows = sync_incoming(self.county, reason="Odczyt w powiecie")
        self.assertEqual((found, rows[0].status, rows[0].letter_id), (1, "MATCHED", approval.pk))

        notice = IntegrationJob.objects.get(operation="DECISION_NOTICE")
        self.assertEqual(self.run_job(notice).status, "LOCAL_SAVED")
        self.assertTrue(DemoMessage.objects.filter(recipient=f"powiat-gniezno@{DOMAIN}").exists())

    def test_screens_drive_the_same_flow_and_label_the_simulator(self):
        req = create_request(self.county, data("P4SYM"))
        application = req.letters.get(kind="APPLICATION")
        send_request(self.county, req.uuid)
        self.enter("powiat-gniezno")
        self.assertContains(self.client.get(reverse("integrations")), SIMULATOR_MODE)
        response = self.client.post(
            reverse("letter_send", args=[application.uuid]), {"provider": "EDOR"}, follow=True
        )
        self.assertContains(response, "Operacja zapisana w kolejce integracji.")
        self.run_job(IntegrationJob.objects.get(provider="EDOR"))
        self.assertContains(self.client.get(reverse("integrations")), "Środowisko: SYMULATOR")
        self.assertContains(
            self.client.post(reverse("edor_search"), {"entity_name": "UMP", "offset": 0}), "(symulator)"
        )
        self.enter("ump")
        response = self.client.post(reverse("ezd_incoming"), {"action": "sync"}, follow=True)
        self.assertContains(response, "Nowych przesyłek w RPW: 1")
        self.assertContains(response, req.reference)
        response = self.client.post(reverse("ezd_incoming"), {"action": "sync"}, follow=True)
        self.assertContains(response, "Brak nowych przesyłek")

    def test_offices_only_see_their_own_simulated_register(self):
        req = create_request(self.county, data("P5SYM"))
        send_request(self.county, req.uuid)
        self.run_job(enqueue(self.county, req.letters.get(kind="APPLICATION"), "EDOR"))
        self.assertEqual(sync_incoming(self.demo["powiat-pila"], reason="Obcy urząd")[0], 0)
        self.assertEqual(SimulatorObject.objects.filter(kind="EZD_RPW", office_id="ump").count(), 1)
        self.assertFalse(EZDIncomingDocument.objects.filter(office_id="pil").exists())

    def test_simulator_profiles_fail_closed_outside_demo_mode(self):
        self.assertTrue(all(item["configured"] for item in configuration_status("gni")[:2]))
        with override_settings(DEMO_MODE=False):
            for loader in (load_ezd, load_edor):
                with (
                    self.subTest(loader=loader.__module__),
                    self.assertRaisesRegex(ConnectorError, "demonstracyjnym"),
                ):
                    loader("gni")
            self.assertFalse(any(item["configured"] for item in configuration_status("gni")[:2]))
            # Poza trybem demo i lokalnym podpis DEMO jest odrzucany.
            with override_settings(LOCAL=False), self.assertRaisesRegex(ValidationError, "DEMO"):
                load_signing("gni")
