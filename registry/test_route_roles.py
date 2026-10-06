"""Role checks on existing objects, with real positive data and rollback per case."""

import hashlib
from datetime import timedelta
from types import SimpleNamespace

from django.apps import apps
from django.db import transaction
from django.db.models import Max
from django.test import Client, TestCase
from django.urls import resolve
from django.utils import timezone

from config.urls import urlpatterns

from .account_invitations import enqueue_invitation
from .authentication import session_owner
from .documents import DEFAULT_TEMPLATES
from .models import DeliveryEvidence, EZDIncomingDocument, IntegrationJob, LetterTemplate, Pool
from .services import allocate_pool, create_request, decide_request, send_request
from .test_http_methods import METHODS
from .tests import data, fixtures

ROLE_ORDER = ("anonymous", "admin", "main", "county", "other")


def role_objects(admin, main, county, other):
    for kind, (title, body) in DEFAULT_TEMPLATES.items():
        LetterTemplate.objects.get_or_create(kind=kind, defaults={"title": title, "body": body})
    draft = create_request(county, data("P6ROLE"))
    sent = create_request(county, data("P7ROLE"))
    send_request(county, sent.uuid)
    approved = create_request(county, data("P8ROLE"))
    send_request(county, approved.uuid)
    decide_request(main, approved.uuid, True, "Fikcyjna decyzja macierzy ról")
    approved.refresh_from_db()
    approved.record.refresh_from_db()
    start = (Pool.objects.filter(kind="II", prefix="P").aggregate(end=Max("end"))["end"] or 0) + 1
    pool = allocate_pool(
        main,
        {
            "kind": "II",
            "office": county.office_id,
            "prefix": "P",
            "start": start,
            "end": start + 1,
            "valid_from": timezone.localdate(),
        },
    )
    req3 = create_request(
        county,
        {
            "kind": "III",
            "count": 2,
            "case_number": "ROLE/III",
            "station": "Fikcyjna stacja macierzy",
            "justification": "Fikcyjny test ról",
        },
    )
    send_request(county, req3.uuid)
    decide_request(
        main,
        req3.uuid,
        True,
        pool_data={
            "prefix": "P3",
            "start": 1,
            "end": 2,
            "valid_from": timezone.localdate(),
            "valid_until": timezone.localdate() + timedelta(days=30),
        },
    )
    application = draft.letters.get(kind="APPLICATION")
    approval = approved.letters.get(kind="APPROVAL")
    job = IntegrationJob.objects.create(
        letter=approval, provider="EDOR", operation="SEND", key="ROLE-MATRIX-EDOR", status="CONFIG_ERROR"
    )
    content = b"Synthetic local evidence; not an operator delivery proof."
    evidence = DeliveryEvidence.objects.create(
        job=job,
        remote_id="ROLE-LOCAL",
        kind="LOCAL_TEST",
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    incoming = EZDIncomingDocument.objects.create(
        office=county.office,
        target_hash="0" * 64,
        rpw_number=1,
        rpw_year=2026,
        document_id="ROLE-LOCAL",
        version_id="ROLE-V1",
        workspace_id="ROLE-W1",
        letter=approval,
        sha256=approval.sha256,
        content=approval.pdf,
        status="MATCHED",
    )
    invitation = enqueue_invitation(admin, county.pk, "Fikcyjny test macierzy ról")
    return SimpleNamespace(
        admin=admin,
        main=main,
        county=county,
        other=other,
        draft=draft,
        sent=sent,
        approved=approved,
        pool=pool,
        req3=req3,
        application=application,
        approval=approval,
        job=job,
        evidence=evidence,
        incoming=incoming,
        invitation=invitation,
    )


def role_cases(obj):
    """Status vector is anonymous/admin/main/own county/foreign county."""
    rows = []

    def add(path, statuses, method="GET", payload=None, label="", json=False):
        rows.append(
            {
                "path": path,
                "statuses": dict(zip(ROLE_ORDER, statuses, strict=True)),
                "method": method,
                "payload": payload or {},
                "json": json,
                "label": label or path,
            }
        )

    public = (200, 200, 200, 200, 200)
    business_list = (302, 403, 200, 200, 200)
    business_object = (302, 403, 200, 200, 404)
    admin_only = (302, 200, 403, 403, 403)
    sender = (302, 403, 403, 200, 404)
    add("/", public)
    add("/logowanie/", (200, 302, 302, 302, 302))
    add("/logowanie/kod/", public)
    # Tryb demonstracyjny jest domyślnie wyłączony: jego trasy nie istnieją dla nikogo.
    add("/logowanie/demo/", (404, 404, 404, 404, 404))
    add("/panel/demo/poczta/", (302, 404, 404, 404, 404))
    add("/panel/administracja/demo/kod/", (302, 404, 403, 403, 403), "POST")
    add("/wyloguj/", (302, 302, 302, 302, 302), "POST")
    add("/panel/", (302, 302, 200, 200, 200))
    add("/panel/wnioski/", business_list)
    add("/panel/wnioski/nowy/", business_list)
    add(f"/panel/wnioski/{obj.sent.uuid}/", business_object)
    add(
        f"/panel/wnioski/{obj.draft.uuid}/withdraw/",
        (302, 403, 302, 302, 404),
        "POST",
        {"reason": "Fikcyjne wycofanie macierzy"},
    )
    add("/panel/ewidencja/", business_list)
    add(f"/panel/ewidencja/{obj.approved.record.uuid}/", business_object)
    add(
        f"/panel/ewidencja/{obj.draft.record.uuid}/przedluz/",
        (302, 403, 302, 403, 403),
        "POST",
        {"days": 7, "reason": "Fikcyjne przedłużenie"},
    )
    add(
        f"/panel/ewidencja/{obj.approved.record.uuid}/przeniesienie/",
        (302, 403, 302, 403, 403),
        "POST",
        {
            "transfer-office": obj.other.office_id,
            "transfer-owner": "Fikcyjny nabywca",
            "transfer-reason": "Fikcyjne przeniesienie",
            "transfer-version": obj.approved.record.version,
        },
    )
    add(
        f"/panel/ewidencja/{obj.approved.record.uuid}/zwolnienie/",
        (302, 403, 302, 403, 403),
        "POST",
        {"release-reason": "Fikcyjne zwolnienie", "release-version": obj.approved.record.version},
    )
    add("/panel/eksport/", business_list)
    for scope in ("wnioski", "pule"):
        add(f"/panel/eksport/?co={scope}", business_list)
    add("/panel/eksport/?co=urzedy", (302, 403, 200, 403, 403))
    add("/panel/urzedy/", (302, 403, 200, 403, 403))
    add("/panel/import/", (302, 403, 200, 403, 403))
    add("/panel/import/pule/", (302, 403, 200, 403, 403))
    add("/panel/pule/", business_list)
    add("/panel/pule/nowa/", (302, 403, 200, 403, 403))
    add(f"/panel/pule/{obj.pool.uuid}/", business_object)
    add("/panel/pisma/", business_list)
    add(f"/panel/pisma/{obj.application.uuid}/pdf/", business_object)
    add(f"/panel/pisma/{obj.application.uuid}/podpis/", sender)
    add(f"/panel/pisma/{obj.application.uuid}/wersja/", sender)
    add(
        f"/panel/pisma/{obj.application.uuid}/wyslij/",
        (302, 403, 403, 302, 404),
        "POST",
        {"provider": "SMTP"},
    )
    add(f"/panel/pisma/{obj.application.uuid}/ezd/", sender)
    add("/panel/audyt/", (302, 200, 200, 200, 200))
    add("/panel/integracje/", (302, 200, 200, 200, 200))
    add("/panel/integracje/ezd/wplywy/", business_list)
    add(
        f"/panel/integracje/ezd/wplywy/{obj.incoming.uuid}/link/",
        (302, 403, 404, 302, 404),
        "POST",
        {"reason": "Fikcyjne sprawdzenie"},
    )
    add(f"/panel/integracje/ezd/wplywy/{obj.incoming.uuid}/pdf/", (302, 403, 404, 200, 404))
    add("/panel/integracje/adresy/", business_list)
    add(f"/panel/integracje/edor/{obj.job.uuid}/wznow/", admin_only)
    add(f"/panel/pisma/{obj.approval.uuid}/dowody/{obj.evidence.pk}/", business_object)
    add("/panel/administracja/", admin_only)
    add(f"/panel/administracja/konta/{obj.county.pk}/zaproszenia/", admin_only)
    add(f"/panel/administracja/konta/{obj.county.pk}/zaproszenia/{obj.invitation.uuid}/", admin_only)
    for kind, pk in (("user", obj.county.pk), ("office", obj.county.office_id), ("template", "1")):
        add(f"/panel/administracja/{kind}/nowy/", admin_only)
        # Template IDs are assigned to generated built-ins by create_request.
        if kind == "template":
            pk = LetterTemplate.objects.first().pk
        add(f"/panel/administracja/{kind}/{pk}/", admin_only)
    add("/api/health/", public)
    add("/api/session/", (401, 200, 200, 200, 200))
    add("/api/session/extend/", (401, 200, 200, 200, 200), "POST")
    add("/api/availability/?part=ROLE", public)
    add("/api/public-challenge/", public)
    add("/api/requests/", (401, 403, 200, 200, 200))
    add(
        f"/api/requests/{obj.draft.uuid}/withdraw/",
        (401, 403, 200, 200, 404),
        "POST",
        {"reason": "Fikcyjne wycofanie API"},
        json=True,
    )
    add(f"/api/records/{obj.approved.record.uuid}/", (401, 403, 200, 200, 404))
    add("/api/pools/", (401, 403, 200, 200, 200))
    add(
        f"/api/pools/{obj.pool.uuid}/issue/",
        (401, 403, 200, 200, 404),
        "POST",
        {"slot": obj.pool.slots.first().pk, "case_number": "ROLE/ISSUE"},
        json=True,
    )
    # Opposite sender direction and the third module use the same routes, new objects.
    for action in ("podpis", "wersja", "ezd"):
        add(
            f"/panel/pisma/{obj.approval.uuid}/{action}/",
            (302, 403, 200, 403, 404),
            label="UMP sender " + action,
        )
    add(f"/panel/pule/{obj.req3.pool.uuid}/", business_object, label="module III pool")
    add(f"/panel/wnioski/{obj.req3.uuid}/", business_object, label="module III request")
    # Cover every allowed method at every route. Empty forms prove access to
    # validation, not successful submission or an external operator call.
    original = list(rows)
    for row in original:
        route = resolve(row["path"].split("?")[0])
        if row["method"] != "GET" or "POST" not in METHODS[route.func.__name__]:
            continue
        expected = dict(row["statuses"])
        if route.func.__name__ == "request_detail":
            expected["county"] = 403
        elif route.func.__name__ == "api_requests":
            expected.update(main=400, county=400, other=400)
        elif route.func.__name__ == "api_pools":
            expected.update(main=400, county=403, other=403)
        add(
            row["path"],
            tuple(expected[r] for r in ROLE_ORDER),
            "POST",
            json=route.func.__name__.startswith("api_"),
            label="validation boundary: " + row["label"],
        )
    add(
        f"/api/records/{obj.approved.record.uuid}/",
        (401, 403, 200, 200, 404),
        "PATCH",
        {
            "fields": {"vin": "WVWZZZ1JZXW000001", "registration_date": timezone.localdate().isoformat()},
            "reason": "Fikcyjna rejestracja API",
            "version": obj.approved.record.version,
        },
        json=True,
    )
    add(
        "/panel/wnioski/nowy/",
        (302, 403, 302, 302, 302),
        "POST",
        {**data("P9ROLE"), "case_number": "ROLE/NEW"},
        label="valid new request",
    )
    add(
        f"/panel/wnioski/{obj.sent.uuid}/",
        (302, 403, 302, 403, 404),
        "POST",
        {"decision": "approve", "reason": "Fikcyjna decyzja"},
        label="valid decision",
    )
    add(
        f"/panel/wnioski/{obj.draft.uuid}/submit/",
        (302, 403, 302, 302, 404),
        "POST",
        label="valid HTML submit",
    )
    add(
        f"/api/requests/{obj.draft.uuid}/submit/",
        (401, 403, 200, 200, 404),
        "POST",
        json=True,
        label="valid API submit",
    )
    add(
        f"/api/requests/{obj.sent.uuid}/decide/",
        (401, 403, 200, 403, 403),
        "POST",
        {"approve": True, "reason": "Fikcyjna decyzja API"},
        json=True,
        label="valid API decision",
    )
    add(
        f"/panel/pisma/{obj.application.uuid}/wersja/",
        (302, 403, 403, 302, 404),
        "POST",
        {"reason": "Fikcyjna nowa wersja"},
        label="valid letter revision",
    )
    add(
        f"/panel/pisma/{obj.application.uuid}/dowody/{obj.evidence.pk}/",
        (302, 403, 404, 404, 404),
        label="evidence belongs to a different letter",
    )
    add(
        f"/panel/administracja/konta/{obj.other.pk}/zaproszenia/{obj.invitation.uuid}/",
        (302, 404, 403, 403, 403),
        label="invitation belongs to a different account",
    )
    return rows


def business_snapshot():
    return {
        model._meta.label: list(model.objects.order_by("pk").values())
        for model in apps.get_app_config("registry").get_models()
        if model.__name__ not in {"LoginCode", "RateBucket", "PublicChallenge"}
    }


class RouteRoleMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.objects = role_objects(*fixtures())

    def test_all_routes_existing_objects_and_roles(self):
        cases = role_cases(self.objects)
        self.assertEqual(
            {resolve(c["path"].split("?")[0]).route for c in cases}, {p.pattern._route for p in urlpatterns}
        )
        self.assertEqual(
            {(resolve(c["path"].split("?")[0]).route, c["method"]) for c in cases},
            {(p.pattern._route, method) for p in urlpatterns for method in METHODS[p.callback.__name__]},
        )
        for case in cases:
            matched = resolve(case["path"].split("?")[0])
            self.assertIn(case["method"], METHODS[matched.func.__name__])
            for role in ROLE_ORDER:
                with self.subTest(role=role, case=case["label"]):
                    client = Client()
                    user = None if role == "anonymous" else getattr(self.objects, role)
                    if user:
                        client.force_login(user)
                    headers = {
                        "HTTP_ACCEPT": "application/json",
                        "HTTP_X_DYNA_SESSION_OWNER": session_owner(user) if user else "",
                    }
                    before = business_snapshot()
                    with transaction.atomic():
                        if case["method"] == "GET":
                            response = client.get(case["path"], **headers)
                        elif case["json"]:
                            sender = client.patch if case["method"] == "PATCH" else client.post
                            response = sender(
                                case["path"], case["payload"], content_type="application/json", **headers
                            )
                        else:
                            response = client.post(case["path"], case["payload"], **headers)
                        self.assertEqual(response.status_code, case["statuses"][role], response.content[:200])
                        if response.status_code in (401, 403, 404) or (
                            role == "anonymous" and case["path"].startswith("/panel/")
                        ):
                            self.assertEqual(business_snapshot(), before)
                        transaction.set_rollback(True)

    def test_foreign_lists_export_and_api_never_contain_objects(self):
        self.client.force_login(self.objects.other)
        for path in (
            "/panel/wnioski/",
            "/panel/ewidencja/",
            "/panel/pule/",
            "/panel/pisma/",
            "/panel/eksport/",
            "/panel/integracje/",
            "/panel/integracje/ezd/wplywy/",
            "/api/requests/",
            "/api/pools/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                for needle in (
                    str(self.objects.draft.uuid),
                    str(self.objects.approved.record.uuid),
                    str(self.objects.pool.uuid),
                    str(self.objects.application.uuid),
                    self.objects.approval.number,
                    self.objects.approved.record.owner,
                    str(self.objects.job.uuid),
                ):
                    self.assertNotContains(response, needle)
