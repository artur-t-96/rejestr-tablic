from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from registry.documents import DEFAULT_TEMPLATES
from registry.models import LetterTemplate, Office, User
from registry.services import (
    allocate_pool,
    create_request,
    decide_request,
    send_request,
)

COUNTIES = [
    ("chd", "chodzieski", "Chodzież", "Chodzieży"),
    ("czt", "czarnkowsko-trzcianecki", "Czarnków", "Czarnkowie"),
    ("gni", "gnieźnieński", "Gniezno", "Gnieźnie"),
    ("gos", "gostyński", "Gostyń", "Gostyniu"),
    ("grd", "grodziski", "Grodzisk Wlkp.", "Grodzisku Wielkopolskim"),
    ("jar", "jarociński", "Jarocin", "Jarocinie"),
    ("kli", "kaliski", "Kalisz", "Kaliszu"),
    ("kep", "kępiński", "Kępno", "Kępnie"),
    ("kol", "kolski", "Koło", "Kole"),
    ("kni", "koniński", "Konin", "Koninie"),
    ("kos", "kościański", "Kościan", "Kościanie"),
    ("kro", "krotoszyński", "Krotoszyn", "Krotoszynie"),
    ("lsz", "leszczyński", "Leszno", "Lesznie"),
    ("mdz", "międzychodzki", "Międzychód", "Międzychodzie"),
    ("nto", "nowotomyski", "Nowy Tomyśl", "Nowym Tomyślu"),
    ("obo", "obornicki", "Oborniki", "Obornikach"),
    ("ost", "ostrowski", "Ostrów Wlkp.", "Ostrowie Wielkopolskim"),
    ("osz", "ostrzeszowski", "Ostrzeszów", "Ostrzeszowie"),
    ("pil", "pilski", "Piła", "Pile"),
    ("ple", "pleszewski", "Pleszew", "Pleszewie"),
    ("pzn", "poznański", "Poznań", "Poznaniu"),
    ("raw", "rawicki", "Rawicz", "Rawiczu"),
    ("slu", "słupecki", "Słupca", "Słupcy"),
    ("szr", "szamotulski", "Szamotuły", "Szamotułach"),
    ("sre", "średzki", "Środa Wlkp.", "Środzie Wielkopolskiej"),
    ("srm", "śremski", "Śrem", "Śremie"),
    ("tur", "turecki", "Turek", "Turku"),
    ("wag", "wągrowiecki", "Wągrowiec", "Wągrowcu"),
    ("wol", "wolsztyński", "Wolsztyn", "Wolsztynie"),
    ("wrz", "wrzesiński", "Września", "Wrześni"),
    ("zlo", "złotowski", "Złotów", "Złotowie"),
]


class Command(BaseCommand):
    help = "Zakłada fikcyjne konta, słownik 35 urzędów i dane do lokalnego pilotażu. Nie usuwa istniejących wpisów."

    @transaction.atomic
    def handle(self, **options):
        if not settings.LOCAL:
            raise CommandError("Dane pokazowe można tworzyć wyłącznie w trybie lokalnym.")
        main, _ = Office.objects.get_or_create(
            pk="ump",
            defaults={
                "name": "Urząd Miasta Poznania – Wydział Komunikacji",
                "kind": "MAIN",
                "city": "Poznań",
                "email": "ump@example.invalid",
                "allowed_domains": ["example.invalid"],
            },
        )
        for code, city in [("kal", "Kalisz"), ("kon", "Konin"), ("les", "Leszno")]:
            Office.objects.get_or_create(
                pk=code,
                defaults={
                    "name": "Urząd Miasta " + city,
                    "kind": "CITY",
                    "city": city,
                    "email": code + "@example.invalid",
                    "allowed_domains": ["example.invalid"],
                },
            )
        for code, adj, city, location in COUNTIES:
            Office.objects.get_or_create(
                pk=code,
                defaults={
                    "name": "Starostwo Powiatowe w " + location,
                    "kind": "COUNTY",
                    "city": city,
                    "email": code + "@example.invalid",
                    "allowed_domains": ["example.invalid"],
                },
            )
        for kind, (title, body) in DEFAULT_TEMPLATES.items():
            LetterTemplate.objects.get_or_create(kind=kind, defaults={"title": title, "body": body})
        accounts = [
            ("admin", "ADMIN", None, "Administrator", "Testowy"),
            ("ump", "MAIN", main, "Urzędnik", "UMP"),
            ("gniezno", "COUNTY", Office.objects.get(pk="gni"), "Urzędnik", "Gniezno"),
            ("pila", "COUNTY", Office.objects.get(pk="pil"), "Urzędnik", "Piła"),
        ]
        users = {}
        for name, role, office, first, last in accounts:
            email = name + "@example.invalid"
            user, new = User.objects.get_or_create(
                username=email,
                defaults={
                    "email": email,
                    "role": role,
                    "office": office,
                    "first_name": first,
                    "last_name": last,
                },
            )
            if new:
                user.set_unusable_password()
                user.full_clean()
                user.save()
            users[name] = user
        if not users["gniezno"].authored_requests.exists():
            for number, owner in [
                ("P0DYNA", "Osoba Testowa Alfa"),
                ("P1AUTO", "Firma Testowa Beta"),
                ("P5ANNA", "Osoba Testowa Gamma"),
            ]:
                req = create_request(
                    users["gniezno"],
                    {
                        "kind": "I",
                        "number": number,
                        "owner": owner,
                        "case_number": "TEST/" + number,
                        "count": 1,
                    },
                )
                send_request(users["gniezno"], req.uuid)
                if number != "P5ANNA":
                    decide_request(users["ump"], req.uuid, True, "Dane pokazowe")
            allocate_pool(
                users["ump"],
                {
                    "kind": "II",
                    "office": "gni",
                    "prefix": "P",
                    "start": 1,
                    "end": 30,
                    "valid_from": timezone.localdate(),
                },
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Gotowe: {Office.objects.count()} urzędów. Konta: admin, ump, gniezno, pila @example.invalid. Logowanie kodem e-mail."
            )
        )
