"""UA API v3 + SE API v4. Publiczne kontrakty są zapisane w docs/api.

Uwierzytelnienie RFC 7523, pojedyncza przesyłka elektroniczna, odczyt metadanych
bez otwierania wiadomości i archiwizacja oryginalnych dowodów operatora.
Testy MockTransport nie potwierdzają dostępu do środowiska INT.
"""

import base64
import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings

from .ezdrp import ConnectorError, private_text, simulated

TOKEN_CACHE = {}
TOKEN_LOCK = threading.RLock()
REMOTE_STATUSES = {
    "W trakcie weryfikacji",
    "Przekazana do realizacji",
    "Odrzucona",
    "Nadana",
    "Wysłana",
    "Czeka na doręczenie",
    "Doręczona",
    "Uznana za doręczoną",
    "Niedoręczona",
}
EVIDENCE_TYPES = {
    "A.1",
    "A.2",
    "B.1",
    "B.2",
    "B.3",
    "D.1",
    "D.2",
    "D.3",
    "E.1",
    "E.2",
    "BP.WX",
    "BP.WP",
    "BP.OX",
    "BP.OP",
    "H.DW",
    "H.PN",
    "H.EPO",
    "E1",
    "BPOX",
    "BPOP",
    "BPWX",
    "D",
    "D1",
    "B2",
    "C2",
    "A1",
    "A2",
    "B1",
    "B3",
    "D2",
    "D3",
    "E2",
    "BPWP",
    "HDW",
    "HPN",
    "HEPO",
}


def ade(value):
    if not isinstance(value, str) or not re.fullmatch(r"AE:PL-\d{5}-\d{5}-[A-Z0-9]{5}-\d{2}", value):
        raise ConnectorError("Niepoprawny polski adres do e-Doręczeń.")
    return value


def opaque_id(value):
    if not isinstance(value, str) or not value or len(value) > 180 or re.search(r"[\x00-\x20/\\?#]", value):
        raise ConnectorError("API e-Doręczeń zwróciło niepoprawny identyfikator.", state="REVIEW_REQUIRED")
    return value


def endpoint(value):
    if not isinstance(value, str):
        raise ConnectorError("Konfiguracja e-Doręczeń wymaga adresów HTTPS.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConnectorError("Konfiguracja e-Doręczeń wymaga adresów HTTPS bez parametrów i hasła.")
    return value.rstrip("/")


@dataclass(frozen=True)
class EDorProfile:
    sender_ade: str
    system_name: str
    ua_url: str
    se_url: str
    token_url: str
    audience: str
    private_key: object = field(repr=False)
    certificate_fingerprint: str
    certificate_expires_at: datetime
    environment: str = "INT"
    ca_file: str = ""

    @property
    def target_hash(self):
        return hashlib.sha256(
            json.dumps(
                [
                    self.sender_ade,
                    self.system_name,
                    self.ua_url,
                    self.se_url,
                    self.token_url,
                    self.audience,
                    self.environment,
                ]
            ).encode()
        ).hexdigest()

    @property
    def token_cache_key(self):
        return (self.target_hash, self.certificate_fingerprint, self.ca_file)


def load_profile(office_id):
    if not settings.EDOR_CONFIG_FILE:
        raise ConnectorError("Nie skonfigurowano e-Doręczeń dla tego urzędu.")
    try:
        configs = json.loads(private_text(settings.EDOR_CONFIG_FILE))
        if not isinstance(configs, dict) or not isinstance(configs.get("offices"), dict):
            raise ConnectorError("Niepoprawny plik konfiguracji e-Doręczeń.")
        if office_id not in configs["offices"]:
            raise ConnectorError("Nie skonfigurowano e-Doręczeń dla tego urzędu.")
        config = configs["offices"][office_id]
        password = (
            private_text(config["private_key_password_file"]).rstrip("\r\n").encode()
            if config.get("private_key_password_file")
            else None
        )
        key = serialization.load_pem_private_key(
            private_text(config["private_key_file"]).encode(),
            password=password,
        )
        cert = x509.load_pem_x509_certificate(private_text(config["certificate_file"]).encode())
        now = datetime.now(timezone.utc)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ConnectorError("Uwierzytelnienie e-Doręczeń wymaga klucza RSA co najmniej 2048 bitów.")
        if key.public_key().public_numbers() != cert.public_key().public_numbers():
            raise ConnectorError("Klucz prywatny nie odpowiada certyfikatowi e-Doręczeń.")
        if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
            raise ConnectorError("Certyfikat systemu e-Doręczeń jest nieważny czasowo.")
        system_name = config["system_name"]
        if not isinstance(system_name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", system_name):
            raise ConnectorError("Niepoprawna nazwa zarejestrowanego systemu e-Doręczeń.")
        environment = config["environment"]
        ua_url, se_url = endpoint(config["ua_url"]), endpoint(config["se_url"])
        if environment == "SYMULATOR" or simulated(ua_url):
            # Symulator musi być nazwany wprost i działa tylko w trybie demonstracyjnym.
            if not (environment == "SYMULATOR" and simulated(ua_url) and settings.DEMO_MODE):
                raise ConnectorError(
                    "Profil symulatora e-Doręczeń działa wyłącznie w trybie demonstracyjnym."
                )
        elif environment not in {"INT", "PROD"}:
            raise ConnectorError("Wskaż środowisko e-Doręczeń INT lub PROD.")
        if not ua_url.endswith("/api/v3") or not se_url.endswith("/api/se/v4"):
            raise ConnectorError("Konektor wymaga UA API v3 i SE API v4.")
        return EDorProfile(
            sender_ade=ade(config["sender_ade"]),
            system_name=system_name,
            ua_url=ua_url,
            se_url=se_url,
            token_url=endpoint(config["token_url"]),
            audience=endpoint(config["audience"]),
            private_key=key,
            certificate_fingerprint=hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest(),
            certificate_expires_at=cert.not_valid_after_utc,
            environment=environment,
            ca_file=config.get("ca_file", ""),
        )
    except ConnectorError as exc:
        # Wspólny czytnik plików ma historyczną nazwę EZD w błędzie I/O.
        raise ConnectorError(str(exc).replace("EZD RP", "e-Doręczeń")) from exc
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ConnectorError(
            "Brak poprawnego profilu, klucza lub certyfikatu e-Doręczeń dla urzędu."
        ) from exc


class EDorClient:
    def __init__(self, profile, *, transport=None):
        self.profile = profile
        if transport is None and simulated(profile.ua_url):
            from registry.simulators import transport as simulator_transport

            transport = simulator_transport()
        self.http = httpx.Client(
            timeout=httpx.Timeout(30, connect=10),
            verify=profile.ca_file or True,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.token = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.http.close()
        self.token = ""

    def _http(self, method, url, *, mutation=False, expected=(200,), binary=False, **kwargs):
        state = "REVIEW_REQUIRED" if mutation else "RETRY"
        try:
            # Strumieniowanie ogranicza pamięć również dla złośliwej odpowiedzi.
            with self.http.stream(method, url, **kwargs) as response:
                status = response.status_code
                if status in {401, 403}:
                    with TOKEN_LOCK:
                        TOKEN_CACHE.pop(self.profile.token_cache_key, None)
                    self.token = ""
                    raise ConnectorError(
                        "e-Doręczenia odmówiły uwierzytelnienia lub uprawnień.",
                        safe_to_resubmit=mutation,
                    )
                if status == 429:
                    try:
                        delay = min(3600, max(60, int(response.headers.get("Retry-After", "60"))))
                    except ValueError:
                        delay = 60
                    raise ConnectorError(
                        "e-Doręczenia ograniczyły liczbę żądań.",
                        state="RETRY",
                        retry_seconds=delay,
                        safe_to_resubmit=mutation,
                    )
                if 400 <= status < 500 and status not in {408, 409}:
                    raise ConnectorError(
                        f"e-Doręczenia odrzuciły żądanie (HTTP {status}).",
                        state="REJECTED",
                        safe_to_resubmit=mutation and status == 400,
                    )
                if status not in expected:
                    raise ConnectorError(f"Niepotwierdzony wynik e-Doręczeń (HTTP {status}).", state=state)
                chunks, length = [], 0
                for chunk in response.iter_bytes():
                    length += len(chunk)
                    if length > 10 * 1024 * 1024:
                        raise ConnectorError("Odpowiedź e-Doręczeń przekracza limit 10 MB.", state=state)
                    chunks.append(chunk)
                content = b"".join(chunks)
                if binary:
                    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                    if content_type not in {
                        "application/octet-stream",
                        "application/xml",
                        "text/xml",
                        "application/zip",
                        "application/pdf",
                    }:
                        raise ConnectorError(
                            "Operator zwrócił dowód w nieoczekiwanym formacie.", state="RETRY"
                        )
                    if not content:
                        raise ConnectorError("Operator zwrócił pusty dowód.", state="RETRY")
                    return content
                result = json.loads(content)
                if not isinstance(result, (dict, list)):
                    raise ValueError()
                return result
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ConnectorError(
                "Nie nawiązano połączenia z e-Doręczeniami.",
                state="RETRY",
                safe_to_resubmit=mutation,
            ) from exc
        except httpx.TransportError as exc:
            raise ConnectorError(
                "Przerwano połączenie z e-Doręczeniami; wynik operacji jest niepotwierdzony.", state=state
            ) from exc
        except (ValueError, UnicodeError) as exc:
            raise ConnectorError("Odpowiedź e-Doręczeń jest niezgodna z kontraktem.", state=state) from exc

    def authenticate(self):
        # Cache w pamięci pracownika, bez tokenów w bazie, plikach i logach.
        with TOKEN_LOCK:
            if datetime.now(timezone.utc) >= self.profile.certificate_expires_at:
                raise ConnectorError("Certyfikat e-Doręczeń wygasł.")
            entry = TOKEN_CACHE.get(self.profile.token_cache_key)
            if entry and entry[1] > time.monotonic():
                self.token = entry[0]
                return
            now = int(time.time())
            subject = f"{self.profile.sender_ade}.SYSTEM.{self.profile.system_name}"
            assertion = jwt.encode(
                {
                    "iss": subject,
                    "sub": subject,
                    "aud": self.profile.audience,
                    "iat": now,
                    "nbf": now,
                    "exp": now + 300,
                    "jti": str(uuid.uuid4()),
                },
                self.profile.private_key,
                algorithm="RS256",
            )
            result = self._http(
                "POST",
                self.profile.token_url,
                params={"login_hint": f"ADE.{self.profile.sender_ade}"},
                data={
                    "grant_type": "client_credentials",
                    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                    "client_assertion": assertion,
                },
            )
            try:
                token, lifespan = result["access_token"], int(result["expires_in"])
                if (
                    not isinstance(token, str)
                    or not token
                    or lifespan <= 5
                    or result.get("token_type", "").lower() != "bearer"
                ):
                    raise ValueError()
            except (KeyError, TypeError, ValueError) as exc:
                raise ConnectorError(
                    "Serwer uwierzytelniania nie zwrócił ważnego tokenu e-Doręczeń."
                ) from exc
            self.token = token
            TOKEN_CACHE[self.profile.token_cache_key] = (token, time.monotonic() + min(lifespan, 300) - 5)

    def request(self, method, path, *, search=False, **kwargs):
        self.authenticate()
        base = (
            self.profile.se_url
            if search
            else f"{self.profile.ua_url}/{quote(self.profile.sender_ade, safe='')}"
        )
        return self._http(method, base + path, headers={"Authorization": f"Bearer {self.token}"}, **kwargs)

    def confirm_address(self, recipient_ade):
        result = self.request(
            "POST",
            "/search/eda-confirmation",
            search=True,
            json={"senderEda": self.profile.sender_ade, "recipientEda": ade(recipient_ade)},
        )
        if not isinstance(result, dict):
            raise ConnectorError("SE API nie potwierdziło adresata.", state="REVIEW_REQUIRED")
        address, recipient = result.get("recipientEda"), result.get("recipient")
        if (
            not isinstance(address, dict)
            or address.get("recipientEda") != recipient_ade
            or not isinstance(recipient, dict)
            or recipient.get("isPublic") is not True
        ):
            raise ConnectorError(
                "Adres e-Doręczeń nie potwierdza wskazanego podmiotu publicznego.", state="REVIEW_REQUIRED"
            )
        if address.get("edaStatus") != "ACTIVE" or str(address.get("assignmentDegree")) != "3":
            raise ConnectorError("Adres do e-Doręczeń urzędu nie jest aktywny i ujawniony.", state="REJECTED")
        return {
            "ade": recipient_ade,
            "active": True,
            "is_public": True,
            "entity_name": recipient.get("entityName", ""),
        }

    def search_public(self, entity_name, *, offset=0):
        if not 2 <= len(entity_name.strip()) <= 2000 or not 0 <= offset <= 10000:
            raise ConnectorError("Podaj nazwę urzędu i poprawną stronę wyników.")
        result = self.request(
            "POST",
            "/search/bae_search",
            search=True,
            json={
                "senderEda": self.profile.sender_ade,
                "recipientEdasOnly": False,
                "searchCategory": ["PUBLIC_INSTITUTION"],
                "entityName": entity_name.strip(),
                "offset": offset,
                "limit": 20,
            },
        )
        if not isinstance(result, dict) or not isinstance(result.get("baeSearchResponses"), list):
            raise ConnectorError("SE API zwróciło niepoprawne wyniki wyszukiwania.", state="RETRY")
        rows = []
        for item in result["baeSearchResponses"]:
            if not isinstance(item, dict) or not isinstance(item.get("recipientEda"), dict):
                raise ConnectorError("SE API zwróciło niepoprawny adres.", state="RETRY")
            address = item["recipientEda"]
            records = item.get("baeSearchData", [])
            if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
                raise ConnectorError("SE API zwróciło niepoprawne dane urzędu.", state="RETRY")
            for record in records:
                if record.get("index") == 1 and record.get("isPublic") is True:
                    rows.append(
                        {
                            "ade": ade(address.get("recipientEda")),
                            "name": record.get("entityName", ""),
                            "active": address.get("edaStatus") == "ACTIVE"
                            and str(address.get("assignmentDegree")) == "3",
                            "main": address.get("isMainEda"),
                        }
                    )
        return {"rows": rows, "total": result.get("totalResults", len(rows))}

    def send_message(self, *, recipient_ade, subject, body, payload, file_id, scope_id):
        if not payload.startswith(b"%PDF-") or len(payload) > 10 * 1024 * 1024 or len(body) > 5000:
            raise ConnectorError(
                "Pismo musi być PDF do 10 MB, a treść wiadomości do 5000 znaków.",
                state="REJECTED",
                safe_to_resubmit=True,
            )
        value = {
            "messageMetadata": {
                "from": {"eDeliveryAddress": self.profile.sender_ade},
                "to": [{"eDeliveryAddress": ade(recipient_ade)}],
                "subject": subject,
                "caseId": str(scope_id),
                "shippingService": "electronic",
            },
            "textBody": body,
            "attachments": [
                {
                    "order": 1,
                    "file": {
                        "fileMetadata": {
                            "fileId": str(file_id),
                            "filename": f"DRT-{file_id}.pdf",
                            "contentType": "application/pdf",
                            "size": len(payload),
                        },
                        "file": base64.b64encode(payload).decode(),
                    },
                }
            ],
        }
        # Odnowienie tokenu może zawieść przed samym POST wiadomości.
        # request() uwierzytelniałby ponownie; używamy dokładnie tego tokenu,
        # który uzyskano przed granicą zewnętrznej operacji.
        try:
            self.authenticate()
        except ConnectorError as exc:
            exc.safe_to_resubmit = True
            raise
        url = f"{self.profile.ua_url}/{quote(self.profile.sender_ade, safe='')}/messages"
        result = self._http(
            "POST",
            url,
            mutation=True,
            expected=(202,),
            json=value,
            headers={"Authorization": f"Bearer {self.token}"},
        )
        if not isinstance(result, dict):
            raise ConnectorError("API nie potwierdziło przyjęcia zadania wysyłki.", state="REVIEW_REQUIRED")
        task_id = opaque_id(result.get("messageTaskId"))
        return {"task_id": task_id}

    def task_message(self, task_id, recipient_ade):
        path = f"/messages/tasks/{quote(opaque_id(task_id), safe='')}"
        status = self.request("GET", path + "/status")
        if not isinstance(status, dict) or status.get("messageTaskStatus") not in {"PENDING", "FINISHED"}:
            raise ConnectorError("API nie potwierdziło statusu zadania.", state="RETRY")
        if status["messageTaskStatus"] == "PENDING":
            return None
        result = self.request("GET", path)
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
            raise ConnectorError("Wynik zadania nie potwierdza jednej wiadomości.", state="REVIEW_REQUIRED")
        item = result[0]
        # W YAML required wskazuje nieistniejące addresseeAde/status. Używamy
        # zdefiniowanych properties i zawsze porównujemy pełnego adresata.
        if (
            not isinstance(item.get("addressee"), dict)
            or item["addressee"].get("eDeliveryAddress") != recipient_ade
        ):
            raise ConnectorError("Zadanie wskazuje innego adresata.", state="REVIEW_REQUIRED")
        if item.get("error"):
            raise ConnectorError(
                "Operator odrzucił utworzenie wiadomości. Nie ponawiaj wysyłki bez sprawdzenia zadania.",
                state="REJECTED",
            )
        return opaque_id(item.get("messageId"))

    def message_status(self, message_id, recipient_ade):
        result = self.request(
            "GET", f"/messages/{quote(opaque_id(message_id), safe='')}", params={"format": "metadata"}
        )
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
            raise ConnectorError("API nie potwierdziło metadanych wiadomości.", state="REVIEW_REQUIRED")
        message = result[0]
        metadata, control = message.get("messageMetadata"), message.get("messageControlData")
        if not isinstance(metadata, dict) or not isinstance(control, dict):
            raise ConnectorError("Niepoprawne metadane wiadomości.", state="REVIEW_REQUIRED")
        sender, recipients = metadata.get("from"), metadata.get("to")
        # Dodatkowe pola contributor/address nie zmieniają porównania ADE.
        if (
            metadata.get("messageId") != message_id
            or not isinstance(sender, dict)
            or sender.get("eDeliveryAddress") != self.profile.sender_ade
            or not isinstance(recipients, list)
            or len(recipients) != 1
            or not isinstance(recipients[0], dict)
            or recipients[0].get("eDeliveryAddress") != recipient_ade
            or metadata.get("shippingService") != "electronic"
        ):
            raise ConnectorError(
                "Wiadomość nie odpowiada nadawcy i adresatowi operacji.", state="REVIEW_REQUIRED"
            )
        if control.get("status") not in REMOTE_STATUSES:
            raise ConnectorError("Nieznany status wiadomości e-Doręczeń.", state="REVIEW_REQUIRED")
        return {
            "status": control["status"],
            "submission_date": metadata.get("submissionDate"),
            "receipt_date": metadata.get("receiptDate"),
        }

    def evidences(self, message_id):
        result = self.request("GET", f"/messages/{quote(opaque_id(message_id), safe='')}/evidences")
        if not isinstance(result, dict) or not isinstance(result.get("evidences"), list):
            raise ConnectorError("API nie zwróciło poprawnej listy dowodów.", state="RETRY")
        rows = []
        for item in result["evidences"]:
            if (
                not isinstance(item, dict)
                or item.get("messageId") != message_id
                or item.get("type") not in EVIDENCE_TYPES
            ):
                raise ConnectorError(
                    "Dowód nie odpowiada wiadomości lub ma nieznany typ.", state="REVIEW_REQUIRED"
                )
            rows.append(
                {
                    "id": opaque_id(item.get("evidenceId")),
                    "kind": item["type"],
                    "event_date": item.get("eventDate"),
                    "create_date": item.get("createDate"),
                }
            )
        return rows

    def evidence_content(self, evidence_id):
        # Nie używamy externalData z odpowiedzi, tylko uwierzytelnionego API.
        return self.request("GET", f"/evidences/purde/{quote(opaque_id(evidence_id), safe='')}", binary=True)
