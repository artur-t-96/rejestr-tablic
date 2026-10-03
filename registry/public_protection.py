"""Jednorazowe ALTCHA v2 i wspólny limit publicznego HTML/API."""

import base64
import json
import re
import secrets
from datetime import timedelta

from altcha import Challenge, Payload, Solution, create_challenge, verify_solution
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import PublicChallenge
from .security import rate_count


def proof_secret():
    return salted_hmac("dyna-public-captcha-signature", "ALTCHA-v2").hexdigest()


def binding(request):
    scope = request.session.get("public_challenge_scope", "")
    if not scope:
        return ""
    return salted_hmac(
        "dyna-public-captcha-binding", scope + ":" + request.META.get("REMOTE_ADDR", "")
    ).hexdigest()


def issue_challenge(request):
    count, retry = rate_count("captcha-issue:" + request.META.get("REMOTE_ADDR", ""), 60)
    if count > 10:
        return None, retry
    if "public_challenge_scope" not in request.session:
        request.session["public_challenge_scope"] = secrets.token_hex(32)
    row = PublicChallenge(binding=binding(request), expires_at=timezone.now() + timedelta(minutes=5))
    challenge = create_challenge(
        algorithm="PBKDF2/SHA-256",
        cost=settings.PUBLIC_CAPTCHA_COST,
        key_prefix="00",
        expires_at=row.expires_at,
        data={"id": str(row.pk)},
        hmac_secret=proof_secret(),
    ).to_dict()
    row.challenge = challenge
    row.save(force_insert=True)
    # Brak kolektora zachowania i zewnętrznych usług; tylko lokalny PoW.
    return {**challenge, "configuration": {"humanInteractionSignature": False}}, 0


@transaction.atomic
def consume_proof(request, encoded):
    if not isinstance(encoded, str) or not 0 < len(encoded) <= 8192:
        return False
    try:
        payload = json.loads(base64.b64decode(encoded, validate=True))
        if not isinstance(payload, dict):
            return False
        submitted = payload["challenge"]
        nonce = submitted["parameters"]["data"]["id"]
        if not isinstance(nonce, str) or len(nonce) != 36:
            return False
        solution = payload["solution"]
        counter, key = solution["counter"], solution["derivedKey"]
        if type(counter) is not int or not 0 <= counter <= 0xFFFFFFFF:
            return False
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            return False
        row = PublicChallenge.objects.select_for_update().filter(pk=nonce).first()
        if (
            not row
            or row.consumed_at
            or row.expires_at <= timezone.now()
            or not binding(request)
            or row.binding != binding(request)
            or submitted != row.challenge
        ):
            return False
        # Weryfikujemy parametry z własnej bazy, nie koszt/algorytm klienta.
        original = Payload(Challenge.from_dict(row.challenge), Solution(counter, key))
        if not verify_solution(original, proof_secret()).verified:
            return False
        row.consumed_at = timezone.now()
        row.save(update_fields=["consumed_at"])
        return True
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, ValidationError):
        return False


@transaction.atomic
def public_gate(request, payload=""):
    count, retry = rate_count("public:" + request.META.get("REMOTE_ADDR", ""), 60)
    if count > settings.PUBLIC_QUERY_LIMIT:
        return "limited", retry
    if count > settings.PUBLIC_CAPTCHA_THRESHOLD and not consume_proof(request, payload):
        return "challenge", 0
    return "allowed", 0
