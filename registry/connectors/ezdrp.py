"""EZD RP Integrator API v2. Kontrakt: docs/api/ezdrp-v2.json.

Żaden mutujący POST nie jest automatycznie ponawiany po niepewnej odpowiedzi.
Odpowiedzi operatora i nagłówki autoryzacji nie trafiają do logów aplikacji.
"""

import base64
import hashlib
import json
import re
import stat
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from django.conf import settings


class ConnectorError(Exception):
    def __init__(self, message, *, state="CONFIG_ERROR", retry_seconds=60, safe_to_resubmit=False):
        super().__init__(message)
        self.state = state
        self.retry_seconds = retry_seconds
        self.safe_to_resubmit = safe_to_resubmit


def private_text(path):
    path = Path(path)
    if not path.is_absolute():
        raise ConnectorError("Plik konfiguracji lub sekretu wymaga ścieżki bezwzględnej.")
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o007:
            raise ConnectorError(
                "Plik konfiguracji lub sekretu nie może być dostępny dla innych użytkowników."
            )
        if info.st_size > 1024 * 1024:
            raise ConnectorError("Plik konfiguracji jest zbyt duży.")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConnectorError("Nie można odczytać prywatnej konfiguracji EZD RP.") from exc


SIMULATOR_SUFFIX = ".symulator.invalid"


def simulated(url):
    """Adres wbudowanego symulatora; nigdy nie jest rozwiązywany w sieci."""
    return isinstance(url, str) and (urlsplit(url).hostname or "").endswith(SIMULATOR_SUFFIX)


def https_url(value, *, root=False):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (root and parsed.path not in ("", "/"))
        or parsed.hostname == "integrator-api.demo.ezdrp.gov.pl"
    ):
        raise ConnectorError("EZD RP wymaga adresów HTTPS własnej instancji lub przydzielonej piaskownicy.")
    return value.rstrip("/")


@dataclass(frozen=True)
class EZDProfile:
    api_url: str
    token_url: str
    web_host: str
    pid: str
    aki: str
    sid: str
    api_key: str = field(repr=False)
    jrwa_id: str = ""
    archival_category: str = ""
    metadata: dict = field(default_factory=dict)
    ca_file: str = ""
    download_origins: tuple = ()

    @property
    def target_hash(self):
        # Rotacja sekretu nie zmienia celu, zmiana instancji/stanowiska już tak.
        value = [self.api_url, self.web_host, self.pid, self.sid]
        return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def load_profile(office_id):
    if not settings.EZDRP_CONFIG_FILE:
        raise ConnectorError("Nie skonfigurowano połączenia z EZD RP dla tego urzędu.")
    try:
        config = json.loads(private_text(settings.EZDRP_CONFIG_FILE))
        value = config["offices"][office_id]
        key = private_text(value["api_key_file"]).strip()
        web_host = value["web_host"]
        if not re.fullmatch(r"[a-zA-Z0-9.-]+(?::[0-9]{1,5})?", web_host) or not key:
            raise ConnectorError("Niepoprawny host EZD lub pusty klucz API.")
        for name in ("pid", "aki", "sid"):
            if not isinstance(value[name], str) or not value[name].strip():
                raise ConnectorError("Konfiguracja EZD wymaga identyfikatorów podmiotu, klucza i stanowiska.")
        metadata = value.get("metadata", {})
        allowed = {"request_id", "request_url", "letter_number", "payload_sha256"}
        if not isinstance(metadata, dict) or set(metadata) - allowed:
            raise ConnectorError("Nieobsługiwane mapowanie metadanych EZD RP.")
        for item in metadata.values():
            if not isinstance(item, dict) or not item.get("key") or not item.get("name"):
                raise ConnectorError("Mapowanie metadanych wymaga klucza i nazwy atrybutu w EZD.")
        if simulated(value["api_url"]) and not settings.DEMO_MODE:
            raise ConnectorError("Profil symulatora EZD RP działa wyłącznie w trybie demonstracyjnym.")
        return EZDProfile(
            api_url=https_url(value["api_url"], root=True),
            token_url=https_url(value["token_url"]),
            web_host=web_host,
            pid=value["pid"],
            aki=value["aki"],
            sid=value["sid"],
            api_key=key,
            jrwa_id=value.get("jrwa_id", ""),
            archival_category=value.get("archival_category", ""),
            metadata=metadata,
            ca_file=value.get("ca_file", ""),
            download_origins=tuple(
                https_url(origin, root=True) for origin in value.get("download_origins", [])
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConnectorError("Brak poprawnego profilu EZD RP dla tego urzędu.") from exc


def opaque_id(value):
    if not isinstance(value, str) or not value or len(value) > 180 or re.search(r"[\x00-\x20/\\?#]", value):
        raise ConnectorError("API EZD zwróciło niepoprawny identyfikator.", state="REVIEW_REQUIRED")
    return value


class EZDRPClient:
    prefix = "/ezdrp/integrator/v2"

    def __init__(self, profile, *, transport=None):
        self.profile = profile
        if transport is None and simulated(profile.api_url):
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
        self.expires_at = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.http.close()
        self.token = ""

    def _response(self, response, *, mutation):
        status = response.status_code
        if status in (401, 403):
            self.token = ""
            raise ConnectorError("EZD RP odmówił uwierzytelnienia lub uprawnień.")
        if status == 429:
            try:
                delay = min(3600, max(60, int(response.headers.get("Retry-After", "60"))))
            except ValueError:
                delay = 60
            raise ConnectorError("EZD RP ograniczył liczbę żądań.", state="RETRY", retry_seconds=delay)
        if 400 <= status < 500 and status != 409:
            raise ConnectorError(f"EZD RP odrzucił żądanie (HTTP {status}).", state="REJECTED")
        if not 200 <= status < 300:
            raise ConnectorError(
                f"Niepotwierdzony wynik EZD RP (HTTP {status}).",
                state="REVIEW_REQUIRED" if mutation else "RETRY",
            )
        if len(response.content) > 5 * 1024 * 1024:
            raise ConnectorError("Odpowiedź EZD jest zbyt duża.", state="REVIEW_REQUIRED")
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except ValueError as exc:
            raise ConnectorError(
                "EZD RP zwrócił odpowiedź niezgodną z kontraktem.",
                state="REVIEW_REQUIRED" if mutation else "RETRY",
            ) from exc

    def _send(self, method, url, *, mutation=False, **kwargs):
        try:
            response = self.http.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise ConnectorError("Nie udało się nawiązać połączenia z EZD RP.", state="RETRY") from exc
        except httpx.TransportError as exc:
            raise ConnectorError(
                "Przerwano komunikację z EZD RP. Wynik operacji wymaga sprawdzenia."
                if mutation
                else "Przerwano odczyt z EZD RP.",
                state="REVIEW_REQUIRED" if mutation else "RETRY",
            ) from exc
        return self._response(response, mutation=mutation)

    def _authenticate(self):
        if self.token and time.monotonic() < self.expires_at:
            return
        rt = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        sha = lambda text: base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        result = self._send(
            "POST",
            self.profile.token_url,
            data={
                "grant_type": "api_credentials",
                "client_id": "api_" + sha(self.profile.web_host),
                "scope": "api.ezdrp.gov.pl",
                "pid": self.profile.pid,
                "aki": self.profile.aki,
                "rt": rt,
                "akh": sha(rt + self.profile.api_key),
            },
        )
        token = result.get("access_token")
        try:
            lifetime = int(result["expires_in"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConnectorError("Niepoprawna odpowiedź serwera uwierzytelniania EZD RP.") from exc
        if (
            not isinstance(token, str)
            or not token
            or lifetime <= 0
            or result.get("token_type", "Bearer").lower() != "bearer"
        ):
            raise ConnectorError("Serwer EZD RP nie zwrócił ważnego tokenu Bearer.")
        self.token = token
        self.expires_at = time.monotonic() + max(0, lifetime - 30)

    def authenticate(self):
        self._authenticate()

    def request(self, method, path, *, mutation=False, **kwargs):
        self._authenticate()
        return self._send(
            method,
            self.profile.api_url + self.prefix + path,
            mutation=mutation,
            headers={"Authorization": f"Bearer {self.token}", "SID": self.profile.sid},
            **kwargs,
        )

    def get_case(self, remote_id):
        result = self.request("GET", f"/sprawy/{quote(opaque_id(remote_id), safe='')}")
        if (
            result.get("idSprawa") != remote_id
            or not isinstance(result.get("tytul"), str)
            or result.get("idPodmiotWlascicielBiznesowy") != self.profile.pid
        ):
            raise ConnectorError("Odpowiedź nie potwierdza wskazanej sprawy EZD RP.", state="REVIEW_REQUIRED")
        return result

    def create_case(self, *, title, number, year):
        if not self.profile.jrwa_id or not self.profile.archival_category or number < 1:
            raise ConnectorError(
                "Utworzenie sprawy wymaga JRWA, kategorii archiwalnej i uzgodnionego numeru."
            )
        result = self.request(
            "POST",
            "/sprawy",
            mutation=True,
            json={
                "idWykaz": self.profile.jrwa_id,
                "tytul": title,
                "kategoriaArchiwalna": self.profile.archival_category,
                "numer": number,
                "rokZalozenia": year,
            },
        )
        opaque_id(result.get("idSprawa"))
        if result.get("tytul") != title or result.get("idPodmiotWlascicielBiznesowy") != self.profile.pid:
            raise ConnectorError("EZD nie potwierdził danych utworzonej sprawy.", state="REVIEW_REQUIRED")
        return result

    def add_document(self, case_id, payload, filename):
        result = self.request(
            "POST",
            f"/sprawy/{quote(opaque_id(case_id), safe='')}/dokumenty",
            mutation=True,
            files=[("files", (filename, payload, "application/pdf"))],
        )
        values = result.get("lista")
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
            raise ConnectorError(
                "EZD RP nie potwierdził jednego dodanego dokumentu.", state="REVIEW_REQUIRED"
            )
        opaque_id(values[0].get("idDokumentPrzestrzeni"))
        opaque_id(values[0].get("idPrzestrzenRobocza"))
        return {
            key: value
            for key, value in values[0].items()
            if key in {"idDokument", "idDokumentPrzestrzeni", "idDokumentWersja", "idPrzestrzenRobocza"}
        }

    def get_document(self, document_id):
        result = self.request("GET", f"/dokumenty/{quote(opaque_id(document_id), safe='')}")
        if result.get("idDokumentPrzestrzeni") != document_id:
            raise ConnectorError("EZD RP nie potwierdził wskazanego dokumentu.", state="REVIEW_REQUIRED")
        return result

    def _document_chunks(self, document_id):
        """Odczyt bajtów tylko z jawnie dopuszczonego repozytorium; bez Bearer."""
        result = self.request("GET", f"/dokumenty/{quote(opaque_id(document_id), safe='')}/link")
        link = result.get("link")
        if not isinstance(link, str):
            raise ConnectorError("EZD nie zwrócił linku dokumentu.", state="REVIEW_REQUIRED")
        parsed = urlsplit(link)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if (
            parsed.username
            or parsed.password
            or parsed.fragment
            or origin not in (self.profile.api_url, *self.profile.download_origins)
        ):
            raise ConnectorError("Repozytorium plików EZD nie jest dopuszczone w konfiguracji.")
        try:
            with self.http.stream("GET", link) as response:
                if response.status_code != 200:
                    raise ConnectorError(
                        "Nie udało się odczytać dokumentu z repozytorium EZD.", state="RETRY"
                    )
                length = 0
                for chunk in response.iter_bytes():
                    length += len(chunk)
                    if length > 10 * 1024 * 1024:
                        raise ConnectorError(
                            "Dokument EZD przekracza limit weryfikacji 10 MB.", state="REVIEW_REQUIRED"
                        )
                    yield chunk
        except httpx.TransportError as exc:
            raise ConnectorError("Przerwano odczyt dokumentu z repozytorium EZD.", state="RETRY") from exc

    def document_sha256(self, document_id):
        digest = hashlib.sha256()
        for chunk in self._document_chunks(document_id):
            digest.update(chunk)
        return digest.hexdigest()

    def document_bytes(self, document_id):
        return b"".join(self._document_chunks(document_id))

    def incoming_metadata(self, number, year):
        if (
            type(number) is not int
            or not 1 <= number <= 2147483647
            or type(year) is not int
            or not 2000 <= year <= 9999
        ):
            raise ConnectorError("Podaj poprawny numer RPW i rok.")
        result = self.request("GET", f"/rpw/{number}/{year}/metadane")
        if (
            not isinstance(result.get("numerRPW"), str)
            or not re.fullmatch(rf"RPW/{number}/{year}", result["numerRPW"])
            or type(result.get("status")) is not int
            or result["status"] not in {2, 3, 5, 6, 7, 8, 71, 72}
            or not isinstance(result.get("zalaczniki"), list)
        ):
            raise ConnectorError("EZD nie potwierdził aktywnego wskazanego RPW.", state="REVIEW_REQUIRED")
        opaque_id(result.get("idPrzestrzenRobocza"))
        return result

    def document_metadata(self, document_id):
        result = self.request("GET", f"/dokumenty/{quote(opaque_id(document_id), safe='')}/metadane")
        if result.get("idDokumentPrzestrzeni") != document_id or not isinstance(
            result.get("listaKonfiguracji"), list
        ):
            raise ConnectorError("EZD nie potwierdził metadanych dokumentu.", state="REVIEW_REQUIRED")
        return result

    def search_incoming(self, date_from, date_to, page=0):
        from datetime import date

        if (
            type(date_from) is not date
            or type(date_to) is not date
            or not 0 <= (date_to - date_from).days <= 31
            or type(page) is not int
            or not 0 <= page <= 1000
        ):
            raise ConnectorError("Odczyt RPW wymaga zakresu do 31 dni i poprawnej strony.")
        result = self.request(
            "POST",
            "/rpw/_search",
            json={
                "dataOd": date_from.isoformat(),
                "dataDo": date_to.isoformat(),
                "page": page,
                "pageSize": 25,
            },
        )
        items, info = result.get("lista"), result.get("pageInfo")
        if (
            not isinstance(items, list)
            or len(items) > 25
            or not isinstance(info, dict)
            or info.get("pageNumber") != page
            or info.get("pageSize") != 25
        ):
            raise ConnectorError("Niepotwierdzona strona rejestru RPW.", state="REVIEW_REQUIRED")
        numbers = []
        for item in items:
            if not isinstance(item, dict) or item.get("idPodmiotWlascicielBiznesowy") != self.profile.pid:
                raise ConnectorError("RPW wskazuje inny podmiot EZD.", state="REVIEW_REQUIRED")
            if type(item.get("czyUsuniety")) is not bool:
                raise ConnectorError("Niepotwierdzony stan wpisu RPW.", state="REVIEW_REQUIRED")
            if item["czyUsuniety"]:
                continue
            match = re.fullmatch(r"RPW/([1-9][0-9]*)/([0-9]{4})", str(item.get("numerRPW", "")))
            if not match:
                raise ConnectorError(
                    "Nieznany format numeru RPW; wymaga sprawdzenia.", state="REVIEW_REQUIRED"
                )
            numbers.append(tuple(map(int, match.groups())))
        has_next = info.get("isNextPageExists")
        count = info.get("pagesCount")
        if type(has_next) is not bool:
            if type(count) is not int or count < 0 or (count and page >= count):
                raise ConnectorError("Brak potwierdzenia końca rejestru RPW.", state="REVIEW_REQUIRED")
            has_next = page + 1 < count
        elif type(count) is int and has_next != (page + 1 < count):
            raise ConnectorError("Sprzeczna paginacja RPW.", state="REVIEW_REQUIRED")
        return numbers, has_next

    def set_metadata(self, document_id, values):
        metadata = [
            {"klucz": item["key"], "nazwa": item["name"], "wartosc": values[key]}
            for key, item in self.profile.metadata.items()
            if key in values
        ]
        if not metadata:
            return {"mapped_attributes": 0}
        result = self.request(
            "PUT",
            f"/dokumenty/{quote(opaque_id(document_id), safe='')}/metadane",
            mutation=True,
            json={"metadane": metadata},
        )
        confirmed = result.get("metadane")
        if not isinstance(confirmed, list) or any(
            not any(
                item.get("klucz") == wanted["klucz"] and item.get("wartosc") == wanted["wartosc"]
                for item in confirmed
                if isinstance(item, dict)
            )
            for wanted in metadata
        ):
            raise ConnectorError("EZD nie potwierdził zapisanych metadanych.", state="REVIEW_REQUIRED")
        return {"mapped_attributes": len(metadata)}
