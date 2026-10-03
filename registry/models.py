import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import models
from django.db.models import Q


class Office(models.Model):
    id = models.SlugField(primary_key=True)
    name = models.CharField(max_length=180)
    kind = models.CharField(
        max_length=8,
        choices=[("MAIN", "Urząd główny"), ("COUNTY", "Starostwo"), ("CITY", "Miasto")],
    )
    city = models.CharField(max_length=80)
    teryt = models.CharField(max_length=7, blank=True)
    ade = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    allowed_domains = models.JSONField(default=list)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["kind"], condition=Q(kind="MAIN"), name="one_main_office")
        ]

    def clean(self):
        super().clean()
        if not isinstance(self.allowed_domains, list) or any(
            not isinstance(d, str) for d in self.allowed_domains
        ):
            raise ValidationError({"allowed_domains": 'Podaj listę domen e-mail, np. ["urzad.gov.pl"].'})
        normalized = []
        for value in self.allowed_domains:
            domain = value.strip().lower()
            try:
                validate_email("account@" + domain)
                if "." not in domain or "@" in domain or domain.startswith("["):
                    raise ValidationError("Niepoprawna domena")
            except ValidationError as exc:
                raise ValidationError(
                    {"allowed_domains": "Podaj pełne domeny e-mail bez adresów, URL i symbolu *."}
                ) from exc
            if domain not in normalized:
                normalized.append(domain)
        self.allowed_domains = normalized

    def __str__(self):
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        COUNTY = "COUNTY", "Urzędnik powiatowy"
        MAIN = "MAIN", "Urzędnik UMP"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.COUNTY)
    office = models.ForeignKey(Office, null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(role="ADMIN", office__isnull=True)
                    | Q(role__in=["MAIN", "COUNTY"], office__isnull=False)
                ),
                name="account_office_required",
            )
        ]

    @property
    def access_allowed(self):
        if not self.is_active:
            return False
        if self.role == "ADMIN":
            return self.office_id is None
        if (
            not self.office_id
            or not self.office.active
            or ((self.role == "MAIN") != (self.office.kind == "MAIN"))
        ):
            return False
        domains = self.office.allowed_domains
        if not isinstance(domains, list) or any(not isinstance(d, str) for d in domains):
            return False
        if not domains:
            return settings.LOCAL
        return self.email.rsplit("@", 1)[-1].lower() in [d.strip().lower() for d in domains]

    def clean(self):
        super().clean()
        if self.role == "ADMIN" and self.office_id:
            raise ValidationError("Administrator nie jest rolą merytoryczną urzędu.")
        if self.role != "ADMIN" and not self.office_id:
            raise ValidationError("Urzędnik musi mieć przypisany urząd.")
        if self.office_id and ((self.role == "MAIN") != (self.office.kind == "MAIN")):
            raise ValidationError("Rola urzędnika nie odpowiada rodzajowi urzędu.")
        if self.office_id:
            try:
                self.office.clean()
            except ValidationError as exc:
                raise ValidationError(
                    "Niepoprawna konfiguracja domen e-mail urzędu. Popraw ją przed zapisaniem konta."
                ) from exc
        if self.office_id and self.is_active and not self.office.allowed_domains and not settings.LOCAL:
            raise ValidationError("Skonfiguruj dozwolone domeny e-mail urzędu przed aktywowaniem dostępu.")
        if (
            self.office_id
            and self.office.allowed_domains
            and self.email.rsplit("@", 1)[-1].lower() not in self.office.allowed_domains
        ):
            raise ValidationError("Domena adresu e-mail nie jest dozwolona dla urzędu.")


class AccountInvitation(models.Model):
    """Wiadomość o koncie utworzonym przez administratora, bez tokenu logowania."""

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="invitations")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="sent_invitations")
    email = models.EmailField()
    account_context = models.JSONField()
    subject = models.CharField(max_length=180)
    body = models.TextField()
    content_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=24, default="QUEUED")
    attempts = models.PositiveSmallIntegerField(default=0)
    claimed_until = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def status_label(self):
        return {
            "QUEUED": "Oczekuje na wysyłkę",
            "SENDING": "Wysyłka w toku",
            "REVIEW_REQUIRED": "Wymaga sprawdzenia wyniku",
            "CONFIG_ERROR": "Wymaga konfiguracji SMTP",
            "LOCAL_SAVED": "Zapisane lokalnie do pliku — bez wysyłki SMTP",
            "ACCEPTED": "Przyjęte przez SMTP — odbiór niepotwierdzony",
            "CONFIRMED_SENT": "Przyjęcie potwierdzone przez administratora",
            "CANCELLED": "Anulowane",
        }.get(self.status, self.status)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status__in=["QUEUED", "SENDING", "REVIEW_REQUIRED", "CONFIG_ERROR"]),
                name="one_pending_account_invitation",
            )
        ]


class LoginCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    digest = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)


class RateBucket(models.Model):
    key = models.CharField(max_length=64, unique=True)
    start = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)


class PublicChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    binding = models.CharField(max_length=64)
    challenge = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True)


class NumberSequence(models.Model):
    scope = models.CharField(max_length=100)
    year = models.PositiveSmallIntegerField()
    last_value = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["scope", "year"], name="unique_number_sequence"),
            models.CheckConstraint(condition=Q(year__gte=1, year__lte=9999), name="sequence_year_range"),
        ]


class PlateRecord(models.Model):
    class Status(models.TextChoices):
        RESERVED = "RESERVED", "Zarezerwowany"
        SENT = "SENT", "Wniosek w toku"
        ALLOCATED = "ALLOCATED", "Przydzielony"
        ISSUED = "ISSUED", "Wydany"
        SOLD = "SOLD", "Pojazd zbyty"
        RELEASED = "RELEASED", "Zwolniony"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    number = models.CharField(max_length=10)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RESERVED)
    office = models.ForeignKey(Office, on_delete=models.PROTECT)
    owner = models.CharField(max_length=180)
    address = models.CharField(max_length=300, blank=True)
    vin = models.CharField(max_length=17, blank=True)
    make = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=80, blank=True)
    registration_date = models.DateField(null=True, blank=True)
    sale_date = models.DateField(null=True, blank=True)
    buyer = models.CharField(max_length=180, blank=True)
    allocated_at = models.DateTimeField(null=True, blank=True)
    reservation_until = models.DateTimeField(null=True, blank=True)
    # Termin rezerwacji, dla którego wysłano już przypomnienie (przedłużenie pozwala na kolejne).
    reminded_until = models.DateTimeField(null=True, blank=True)
    letter_number = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["number"],
                condition=~Q(status="RELEASED"),
                name="unique_active_plate",
            )
        ]

    @property
    def display_number(self):
        return self.number[:2] + " " + self.number[2:]


class Request(models.Model):
    class Kind(models.TextChoices):
        INDIVIDUAL = "I", "Tablica indywidualna"
        SMALL = "II", "Pula tablic zmniejszonych"
        RESEARCH = "III", "Pula tablic do badań"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Szkic"
        SENT = "SENT", "Oczekuje na decyzję"
        APPROVED = "APPROVED", "Zaakceptowany"
        REJECTED = "REJECTED", "Odrzucony"
        WITHDRAWN = "WITHDRAWN", "Wycofany"
        EXPIRED = "EXPIRED", "Rezerwacja wygasła"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reference_number = models.CharField(max_length=40, unique=True, null=True, editable=False)
    reference_year = models.PositiveSmallIntegerField(null=True, editable=False)
    reference_ordinal = models.PositiveBigIntegerField(null=True, editable=False)
    kind = models.CharField(max_length=3, choices=Kind.choices)
    office = models.ForeignKey(Office, on_delete=models.PROTECT)
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="authored_requests")
    record = models.OneToOneField(PlateRecord, null=True, blank=True, on_delete=models.PROTECT)
    case_number = models.CharField(max_length=100)
    count = models.PositiveIntegerField(default=1)
    station = models.CharField(max_length=180, blank=True)
    justification = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="decided_requests")
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["reference_year", "reference_ordinal"], name="unique_request_ordinal"
            ),
            models.CheckConstraint(
                condition=(
                    Q(reference_year__isnull=True, reference_ordinal__isnull=True)
                    | Q(
                        reference_year__gte=1,
                        reference_year__lte=9999,
                        reference_ordinal__gt=0,
                        reference_year__isnull=False,
                        reference_ordinal__isnull=False,
                    )
                ),
                name="request_number_parts",
            ),
        ]

    @property
    def reference(self):
        return self.reference_number or f"W/{self.created_at.year}/{self.pk:05d}"


class Pool(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=3, choices=Request.Kind.choices[1:])
    office = models.ForeignKey(Office, on_delete=models.PROTECT)
    request = models.OneToOneField(Request, null=True, blank=True, on_delete=models.PROTECT)
    prefix = models.CharField(max_length=2, default="P")
    scheme = models.CharField(max_length=20, default="NUMERIC")
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    station = models.CharField(max_length=180, blank=True)
    alerted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(end__gte=models.F("start")), name="pool_order"),
            models.CheckConstraint(
                condition=Q(valid_until__isnull=True) | Q(valid_until__gte=models.F("valid_from")),
                name="pool_dates",
            ),
            models.CheckConstraint(
                condition=~Q(kind="III") | Q(valid_until__isnull=False),
                name="pool_iii_finite_period",
            ),
        ]
        ordering = ["kind", "start"]

    def clean(self):
        super().clean()
        if self.kind == "III" and self.valid_until is None:
            raise ValidationError({"valid_until": "Podaj termin końca puli modułu III."})

    @property
    def total(self):
        return self.slots.count()

    @property
    def used(self):
        return self.slots.filter(issued_at__isnull=False).count()

    @property
    def percent(self):
        return round(100 * self.used / self.total) if self.total else 0


class PoolSlot(models.Model):
    pool = models.ForeignKey(Pool, on_delete=models.PROTECT, related_name="slots")
    number = models.CharField(max_length=12, unique=True)
    ordinal = models.PositiveIntegerField()
    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(User, null=True, on_delete=models.PROTECT)
    case_number = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["ordinal"]


class FlaggedWord(models.Model):
    """Słownik ostrzeżeń dla UMP; ocena treści wyróżnika pozostaje decyzją urzędnika."""

    word = models.CharField(max_length=5, unique=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["word"]

    def __str__(self):
        return self.word


class LetterTemplate(models.Model):
    kind = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=180)
    body = models.TextField()
    revision = models.PositiveIntegerField(default=1)


class Letter(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    number = models.CharField(max_length=100, unique=True)
    number_year = models.PositiveSmallIntegerField(null=True, editable=False)
    number_ordinal = models.PositiveBigIntegerField(null=True, editable=False)
    replaces = models.ForeignKey("self", null=True, on_delete=models.PROTECT, related_name="versions")
    request = models.ForeignKey(Request, null=True, on_delete=models.PROTECT, related_name="letters")
    pool = models.ForeignKey(Pool, null=True, on_delete=models.PROTECT, related_name="letters")
    office = models.ForeignKey(Office, on_delete=models.PROTECT)
    recipient = models.ForeignKey(Office, on_delete=models.PROTECT, related_name="received_letters")
    kind = models.CharField(max_length=20)
    title = models.CharField(max_length=180)
    body = models.TextField()
    template_revision = models.PositiveIntegerField(default=1)
    pdf = models.BinaryField()
    sha256 = models.CharField(max_length=64)
    signed_pdf = models.BinaryField(null=True)
    signature_status = models.CharField(max_length=20, default="UNSIGNED")
    signed_sha256 = models.CharField(max_length=64, blank=True)
    signature_report = models.JSONField(default=dict)
    signed_at = models.DateTimeField(null=True)
    signed_by = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="signed_letters")
    ezd_id = models.CharField(max_length=150, blank=True)
    # Wysyłka papierowa odnotowana przez urząd nadawcy; nie jest dowodem doręczenia.
    posted_at = models.DateField(null=True, blank=True)
    posted_reference = models.CharField(max_length=60, blank=True)
    posted_by = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="posted_letters")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["office", "number_year", "number_ordinal"], name="unique_letter_ordinal"
            ),
            models.CheckConstraint(
                condition=(
                    Q(number_year__isnull=True, number_ordinal__isnull=True)
                    | Q(
                        number_year__gte=1,
                        number_year__lte=9999,
                        number_ordinal__gt=0,
                        number_year__isnull=False,
                        number_ordinal__isnull=False,
                    )
                ),
                name="letter_number_parts",
            ),
        ]

    @property
    def signature_label(self):
        return {
            "UNSIGNED": "Niepodpisany",
            "TEST_SIGNED": "Podpis testowy — niekwalifikowany",
            "VERIFIED_SIGNED": "Podpis zweryfikowany — kwalifikacja nieustalona",
            "UNVERIFIED": "Podpis wymaga weryfikacji",
        }.get(self.signature_status, "Podpis wymaga weryfikacji")


class IntegrationJob(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    letter = models.ForeignKey(Letter, on_delete=models.PROTECT, related_name="jobs")
    provider = models.CharField(max_length=20)
    operation = models.CharField(max_length=30, default="SEND")
    key = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, default="QUEUED")
    attempts = models.PositiveIntegerField(default=0)
    remote_id = models.CharField(max_length=180, blank=True)
    error = models.TextField(blank=True)
    result = models.JSONField(default=dict)
    next_attempt_at = models.DateTimeField(null=True)
    claimed_until = models.DateTimeField(null=True)
    payload = models.BinaryField(null=True)
    payload_sha256 = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def operation_label(self):
        return {
            "SEND": "Wysyłka pisma",
            "REGISTER": "Zapis dokumentu",
            "DECISION_NOTICE": "Powiadomienie autora o decyzji",
        }.get(self.operation, self.operation)

    @property
    def status_label(self):
        return {
            "QUEUED": "W kolejce",
            "PROCESSING": "Przetwarzanie",
            "RETRY": "Oczekuje na ponowienie",
            "REVIEW_REQUIRED": "Wymaga sprawdzenia wyniku",
            "CONFIG_ERROR": "Błąd konfiguracji",
            "REJECTED": "Odrzucono operację",
            "RETRY_EXHAUSTED": "Wyczerpano próby",
            "REGISTERED": "Zapisano w EZD",
            "ACCEPTED": "Przyjęto przez serwer pocztowy",
            "LOCAL_SAVED": "Zapisano w lokalnej skrzynce",
            "MONITORING": "Oczekuje na status lub dowody",
            "EDOR_DELIVERED": "Doręczona — dowód zarchiwizowany",
            "EDOR_DEEMED": "Uznana za doręczoną — dowód zarchiwizowany",
            "EDOR_REJECTED": "Przesyłka odrzucona — dowód zarchiwizowany",
            "EDOR_FAILED": "Niedoręczona — dowód zarchiwizowany",
        }.get(self.status, self.status)


class EZDCaseLink(models.Model):
    """Sprawa EZD jest odrębna dla każdego urzędu obsługującego wniosek."""

    office = models.ForeignKey(Office, on_delete=models.PROTECT)
    scope_id = models.UUIDField()
    scope_kind = models.CharField(max_length=8, choices=[("REQUEST", "Wniosek"), ("POOL", "Pula")])
    remote_id = models.CharField(max_length=180, blank=True)
    remote_symbol = models.CharField(max_length=180, blank=True)
    state = models.CharField(max_length=20, default="UNLINKED")
    title = models.CharField(max_length=500)
    year = models.PositiveIntegerField()
    number = models.PositiveIntegerField(null=True)
    target_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def state_label(self):
        return {
            "UNLINKED": "Oczekuje na utworzenie sprawy",
            "UNVERIFIED": "Oczekuje na sprawdzenie w EZD",
            "CREATING": "Tworzenie sprawy",
            "LINKED": "Powiązanie potwierdzone",
            "REVIEW_REQUIRED": "Wymaga sprawdzenia wyniku",
        }.get(self.state, self.state)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["office", "scope_id"], name="ezd_case_per_office_scope"),
        ]


class EZDIncomingDocument(models.Model):
    """Minimalny dziennik RPW; bajty archiwizujemy dopiero po zgodnym powiązaniu."""

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    office = models.ForeignKey(Office, on_delete=models.PROTECT)
    target_hash = models.CharField(max_length=64)
    rpw_number = models.PositiveIntegerField()
    rpw_year = models.PositiveSmallIntegerField()
    document_id = models.CharField(max_length=180)
    version_id = models.CharField(max_length=180)
    workspace_id = models.CharField(max_length=180)
    letter = models.ForeignKey(Letter, null=True, on_delete=models.PROTECT, related_name="ezd_incoming")
    sha256 = models.CharField(max_length=64)
    content = models.BinaryField(null=True)
    status = models.CharField(max_length=20, default="UNMATCHED")
    error = models.CharField(max_length=300, blank=True)
    request_url = models.CharField(max_length=1000, blank=True)
    link_status = models.CharField(max_length=20, default="NOT_PUBLISHED")
    link_error = models.CharField(max_length=300, blank=True)
    link_attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["office", "target_hash", "rpw_number", "rpw_year", "document_id", "version_id"],
                name="unique_ezd_incoming_version",
            ),
            models.CheckConstraint(
                condition=Q(rpw_number__gt=0, rpw_year__gte=2000, rpw_year__lte=9999),
                name="ezd_incoming_rpw_parts",
            ),
        ]
        ordering = ["-created_at"]


class DeliveryEvidence(models.Model):
    job = models.ForeignKey(IntegrationJob, on_delete=models.PROTECT, related_name="evidence")
    remote_id = models.CharField(max_length=180)
    kind = models.CharField(max_length=40)
    content = models.BinaryField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["job", "remote_id"], name="unique_evidence")]


class AuditLog(models.Model):
    actor = models.ForeignKey(User, null=True, on_delete=models.PROTECT)
    office = models.ForeignKey(Office, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=50)
    object_type = models.CharField(max_length=40)
    object_id = models.CharField(max_length=100)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    reason = models.TextField(blank=True)
    ip = models.GenericIPAddressField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Log audytowy jest niezmienny.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Log audytowy jest niezmienny.")
