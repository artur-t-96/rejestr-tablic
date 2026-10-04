"""Tryb demonstracyjny: fikcyjne konta na zastrzeżonej domenie i reguły ich widoczności."""

from django.conf import settings

DOMAIN = "demo.invalid"
OFFICES = ("ump", "gni", "pil")
# klucz, rola, urząd, imię, nazwisko, opis na ekranie wejścia
ACCOUNTS = (
    ("powiat-gniezno", "COUNTY", "gni", "Grażyna", "Demo-Gniezno", "Urzędnik powiatu — Gniezno"),
    ("powiat-pila", "COUNTY", "pil", "Paweł", "Demo-Piła", "Urzędnik powiatu — Piła"),
    ("ump", "MAIN", "ump", "Urszula", "Demo-UMP", "Urzędnik UMP — decyzje, całe województwo"),
    ("administrator", "ADMIN", None, "Adam", "Demo-Administrator", "Administrator — konta demonstracyjne"),
)
SEEDED = frozenset(f"{key}@{DOMAIN}" for key, *_ in ACCOUNTS)


def is_demo_email(address):
    return isinstance(address, str) and address.lower().endswith("@" + DOMAIN)


def is_demo(user):
    return bool(getattr(user, "is_authenticated", False)) and is_demo_email(user.email)


def demo_viewer(user):
    """Konto demo ogląda instancję współdzieloną z kontami rzeczywistymi właściciela."""
    return settings.DEMO_MODE and is_demo(user)
