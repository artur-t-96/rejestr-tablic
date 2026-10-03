import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.db import DatabaseError, connection
from django.db.models.query import QuerySet
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from .models import (
    AuditLog,
    IntegrationJob,
    Letter,
    LoginCode,
    NumberSequence,
    PlateRecord,
    Pool,
    PoolSlot,
    PublicChallenge,
    RateBucket,
    Request,
)
from .services import create_request
from .tests import data, fixtures


class SecurityRetentionTests(TestCase):
    def setUp(self):
        self.admin, self.ump, self.county, self.other = fixtures()
        self.now = timezone.now()
        self.cutoff = self.now - timedelta(hours=24)
        self.request = create_request(self.county, {**data(), "owner": "PRIVATE_OWNER_SENTINEL"})
        self.tokens = {}
        self.sessions = {}
        for name, expiry, used in (
            ("old_unused", self.cutoff - timedelta(seconds=1), False),
            ("old_used", self.cutoff, True),
            ("recent_expired", self.cutoff + timedelta(seconds=1), False),
            ("active", self.now + timedelta(minutes=10), False),
            ("active_used", self.now + timedelta(minutes=10), True),
        ):
            self.tokens[name] = LoginCode.objects.create(
                user=self.county, digest="PRIVATE_DIGEST_SENTINEL", expires_at=expiry, used=used
            )
            self.sessions[name] = Session.objects.create(
                session_key=name, session_data="PRIVATE_SESSION_SENTINEL", expire_date=expiry
            )
        self.old_challenge = PublicChallenge.objects.create(
            binding="private", challenge={}, expires_at=self.cutoff
        )
        self.recent_challenge = PublicChallenge.objects.create(
            binding="private", challenge={}, expires_at=self.now + timedelta(minutes=5)
        )
        self.old_bucket = RateBucket.objects.create(key="old", start=self.cutoff, count=9)
        self.recent_bucket = RateBucket.objects.create(key="recent", start=self.now, count=2)

    def state(self, *, include_security=False):
        models = [Request, PlateRecord, Letter, Pool, PoolSlot, NumberSequence, IntegrationJob, AuditLog]
        if include_security:
            models += [LoginCode, Session, PublicChallenge, RateBucket]
        return [list(model.objects.order_by("pk").values()) for model in models]

    def purge(self, **options):
        output = StringIO()
        with patch("registry.management.commands.purge_security_state.timezone.now", return_value=self.now):
            call_command("purge_security_state", stdout=output, **options)
        return output.getvalue()

    def test_preview_is_read_only_even_with_auth_opt_in(self):
        before = self.state(include_security=True)
        report = json.loads(self.purge(include_auth=True, json=True))
        self.assertEqual(report["mode"], "preview")
        self.assertEqual(
            report["candidates"], {"captcha": 1, "rate_buckets": 1, "login_codes": 2, "sessions": 2}
        )
        self.assertEqual(report["deleted"], {})
        self.assertEqual(self.state(include_security=True), before)
        self.assertNotIn("PRIVATE_", json.dumps(report))

    def test_existing_apply_scope_does_not_start_auth_deletion(self):
        before = self.state()
        auth_before = list(LoginCode.objects.values()), list(Session.objects.values())
        report = json.loads(self.purge(apply=True, json=True))
        self.assertFalse(report["include_auth"])
        self.assertEqual(report["deleted"], {"captcha": 1, "rate_buckets": 1})
        self.assertEqual((list(LoginCode.objects.values()), list(Session.objects.values())), auth_before)
        self.assertEqual(self.state(), before)

    def test_expiry_boundary_preserves_current_auth_and_business_history(self):
        before = self.state()
        report = json.loads(self.purge(apply=True, include_auth=True, json=True))
        self.assertEqual(
            report["deleted"], {"captcha": 1, "rate_buckets": 1, "login_codes": 2, "sessions": 2}
        )
        remaining = {"recent_expired", "active", "active_used"}
        self.assertEqual(set(Session.objects.values_list("session_key", flat=True)), remaining)
        self.assertEqual(
            set(LoginCode.objects.values_list("pk", flat=True)), {self.tokens[name].pk for name in remaining}
        )
        self.assertTrue(PublicChallenge.objects.filter(pk=self.recent_challenge.pk).exists())
        self.assertTrue(RateBucket.objects.filter(pk=self.recent_bucket.pk).exists())
        self.assertEqual(self.state(), before)
        second = json.loads(self.purge(apply=True, include_auth=True, json=True))
        self.assertEqual(set(second["deleted"].values()), {0})

    def test_database_failure_rolls_back_all_cleanup_categories(self):
        before = self.state(include_security=True)
        original = QuerySet.delete

        def fail_on_sessions(rows):
            if rows.model is Session:
                raise DatabaseError("Injected cleanup failure")
            return original(rows)

        with patch.object(QuerySet, "delete", fail_on_sessions):
            with self.assertRaises(DatabaseError):
                self.purge(apply=True, include_auth=True)
        self.assertEqual(self.state(include_security=True), before)

    def test_inventory_reports_aggregates_without_loading_contents_or_mutating_data(self):
        output = StringIO()
        # Nawet nietypowa wartość z dawnego/importowanego źródła nie jest drukowana.
        PlateRecord.objects.filter(pk=self.request.record_id).update(status="PRIVATE_STATE_SENTINEL")
        before = self.state(include_security=True)
        with CaptureQueriesContext(connection) as queries:
            call_command("retention_inventory", stdout=output)
        report = json.loads(output.getvalue())
        self.assertEqual(report["mode"], "read_only")
        self.assertEqual(report["classes"]["requests"]["count"], 1)
        self.assertEqual(report["classes"]["requests"]["offices_with_data"], 1)
        self.assertEqual(
            report["classes"]["plate_records"]["categories"], [{"category": "UNKNOWN", "count": 1}]
        )
        self.assertEqual(report["classes"]["login_codes"]["count"], 5)
        self.assertEqual(report["classes"]["sessions"]["count"], 5)
        self.assertEqual(len(report["classes"]), 19)
        for sensitive in ("PRIVATE_", self.county.email, str(self.request.uuid), self.request.reference):
            self.assertNotIn(sensitive, output.getvalue())
        sql = "\n".join(q["sql"] for q in queries.captured_queries)
        for column in ('"pdf"', '"signed_pdf"', '"digest"', '"session_data"', '"before"', '"after"'):
            self.assertNotIn(column, sql)
        self.assertTrue(all(q["sql"].lstrip().startswith("SELECT") for q in queries.captured_queries))
        self.assertEqual(self.state(include_security=True), before)
