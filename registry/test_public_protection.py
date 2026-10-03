import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from altcha import Challenge, Payload, solve_challenge
from django.db import close_old_connections
from django.test import (
    Client,
    RequestFactory,
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.utils import timezone

from .models import PublicChallenge, RateBucket
from .public_protection import consume_proof


def solve(response):
    values = response.json()
    challenge = Challenge.from_dict(values)
    solution = solve_challenge(challenge, timeout=5)
    assert solution is not None
    return Payload(challenge, solution).to_base64()


@override_settings(PUBLIC_CAPTCHA_THRESHOLD=2, PUBLIC_QUERY_LIMIT=6, PUBLIC_CAPTCHA_COST=10)
class PublicProtectionTests(TestCase):
    def query(self, client=None, payload="", **headers):
        return (client or self.client).get(
            "/api/availability/", {"part": "TEST"}, HTTP_X_ALTCHA_PAYLOAD=payload, **headers
        )

    def trigger(self):
        self.assertEqual(self.query().status_code, 200)
        self.assertEqual(self.query().status_code, 200)
        self.assertEqual(self.query().status_code, 403)

    def test_initial_page_and_shared_html_api_budget(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertFalse(RateBucket.objects.exists())
        self.assertEqual(self.query().status_code, 200)
        self.assertEqual(self.client.post("/", {"part": "TEST", "prefix": "P"}).status_code, 200)
        with patch("registry.views.availability") as lookup:
            response = self.query()
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "CAPTCHA_REQUIRED")
            lookup.assert_not_called()
        page = self.client.post("/", {"part": "TEST", "prefix": "P"})
        self.assertContains(page, "altcha-widget", status_code=403)
        self.assertContains(page, 'auto="off"', status_code=403)
        self.assertEqual(page["Cache-Control"], "no-store")

    def test_real_pow_allows_one_lookup_and_replay_is_rejected(self):
        self.trigger()
        proof = solve(self.client.get("/api/public-challenge/"))
        self.assertEqual(self.query(payload=proof).status_code, 200)
        self.assertTrue(PublicChallenge.objects.get().consumed_at)
        self.assertEqual(self.query(payload=proof).status_code, 403)

    def test_html_post_with_real_solution_and_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        initial = csrf_client.get("/")
        self.assertEqual(initial.status_code, 200)
        csrf = csrf_client.cookies["csrftoken"].value
        self.query(csrf_client)
        self.query(csrf_client)
        proof = solve(csrf_client.get("/api/public-challenge/"))
        forbidden = csrf_client.post("/", {"part": "TEST", "prefix": "P", "altcha": proof})
        self.assertEqual(forbidden.status_code, 403)
        self.assertIsNone(PublicChallenge.objects.get().consumed_at)
        accepted = csrf_client.post(
            "/", {"part": "TEST", "prefix": "P", "altcha": proof, "csrfmiddlewaretoken": csrf}
        )
        self.assertContains(accepted, "Wynik sprawdzenia")
        self.assertTrue(PublicChallenge.objects.get().consumed_at)

    def test_proof_is_bound_to_session_and_ip_and_ignores_forwarded_headers(self):
        self.trigger()
        proof = solve(self.client.get("/api/public-challenge/"))
        foreign = Client()
        self.assertEqual(self.query(foreign, payload=proof).status_code, 403)
        self.assertIsNone(PublicChallenge.objects.get().consumed_at)
        request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.1", HTTP_X_FORWARDED_FOR="127.0.0.1")
        request.session = self.client.session
        self.assertFalse(consume_proof(request, proof))
        self.assertEqual(self.query(payload=proof).status_code, 200)

    def test_tampered_cost_signature_and_solution_are_rejected_before_expensive_work(self):
        proof = solve(self.client.get("/api/public-challenge/"))
        decoded = json.loads(base64.b64decode(proof))
        decoded["challenge"]["parameters"]["cost"] = 1000000000
        tampered = base64.b64encode(json.dumps(decoded).encode()).decode()
        request = RequestFactory().get("/")
        request.session = self.client.session
        with patch("registry.public_protection.verify_solution") as verify:
            self.assertFalse(consume_proof(request, tampered))
            verify.assert_not_called()
        decoded = json.loads(base64.b64decode(proof))
        decoded["solution"]["derivedKey"] = "0" * 64
        self.assertFalse(consume_proof(request, base64.b64encode(json.dumps(decoded).encode()).decode()))
        self.assertTrue(consume_proof(request, proof))

    def test_malformed_payloads_do_not_raise_or_consume_challenge(self):
        proof = solve(self.client.get("/api/public-challenge/"))
        request = RequestFactory().get("/")
        request.session = self.client.session
        invalid = [None, 123, "x" * 8193, "%%%"]
        for obj in [
            [],
            {},
            {"challenge": None},
            {
                "challenge": {"parameters": {"data": {"id": "z" * 36}}},
                "solution": {"counter": 0, "derivedKey": "a" * 64},
            },
        ]:
            invalid.append(base64.b64encode(json.dumps(obj).encode()).decode())
        values = json.loads(base64.b64decode(proof))
        values["solution"]["counter"] = True
        invalid.append(base64.b64encode(json.dumps(values).encode()).decode())
        for value in invalid:
            with self.subTest(value=str(value)[:30]):
                self.assertFalse(consume_proof(request, value))
        self.assertIsNone(PublicChallenge.objects.get().consumed_at)

    def test_expiration_and_hard_limit_cannot_be_bypassed_by_valid_proof(self):
        self.trigger()
        proof = solve(self.client.get("/api/public-challenge/"))
        PublicChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.query(payload=proof).status_code, 403)
        fresh = solve(self.client.get("/api/public-challenge/"))
        self.query()
        self.query()
        response = self.query(payload=fresh)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertIsNone(PublicChallenge.objects.latest("expires_at").consumed_at)

    def test_challenge_generation_limit_and_window_reset(self):
        for _ in range(10):
            self.assertEqual(self.client.get("/api/public-challenge/").status_code, 200)
        self.assertEqual(self.client.get("/api/public-challenge/").status_code, 429)
        self.assertEqual(PublicChallenge.objects.count(), 10)
        self.trigger()
        RateBucket.objects.update(start=timezone.now() - timedelta(minutes=2))
        self.assertEqual(self.query().status_code, 200)

    def test_purge_is_preview_by_default_and_preserves_recent_security_state(self):
        from io import StringIO

        from django.core.management import call_command

        self.client.get("/api/public-challenge/")
        old = PublicChallenge.objects.create(
            binding="0" * 64, challenge={}, expires_at=timezone.now() - timedelta(days=2)
        )
        call_command("purge_security_state", stdout=StringIO())
        self.assertTrue(PublicChallenge.objects.filter(pk=old.pk).exists())
        call_command("purge_security_state", apply=True, stdout=StringIO())
        self.assertFalse(PublicChallenge.objects.filter(pk=old.pk).exists())
        self.assertEqual(PublicChallenge.objects.count(), 1)
        self.assertEqual(RateBucket.objects.count(), 1)


@override_settings(PUBLIC_CAPTCHA_COST=10)
class PublicProtectionConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_same_proof_is_consumed_once_across_two_transactions(self):
        client = Client()
        proof = solve(client.get("/api/public-challenge/"))
        scope = dict(client.session)
        barrier = Barrier(2)

        def verify():
            close_old_connections()
            try:
                request = RequestFactory().get("/")
                request.session = scope
                barrier.wait(timeout=5)
                return consume_proof(request, proof)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: verify(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertTrue(PublicChallenge.objects.get().consumed_at)
