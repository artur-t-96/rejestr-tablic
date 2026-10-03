import hashlib
from html import escape
from io import BytesIO
from string import Template
from urllib.parse import urlsplit
from xml.sax.saxutils import quoteattr

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .models import Letter, LetterTemplate, Office


def lock_letter(letter):
    """Wywołuj w transakcji: wspólna kolejność blokad dla podpisu i kolejki."""
    # NO KEY UPDATE serializuje operacje urzędu bez blokowania odwołań FK
    # podczas równoczesnego generowania nowych dokumentów.
    Office.objects.select_for_update(no_key=True).get(pk=letter.office_id)
    return Letter.objects.select_for_update().get(pk=letter.pk)


def document_payload(letter, *, original=False):
    payload = bytes(letter.pdf)
    if hashlib.sha256(payload).hexdigest() != letter.sha256:
        raise ValidationError("Oryginalny PDF nie przeszedł kontroli integralności.")
    if letter.signed_pdf is not None and not original:
        payload = bytes(letter.signed_pdf)
        if (
            not letter.signed_sha256
            or hashlib.sha256(payload).hexdigest() != letter.signed_sha256
            or letter.signature_status not in {"TEST_SIGNED", "VERIFIED_SIGNED"}
            or letter.signature_report.get("signed_sha256") != letter.signed_sha256
            or letter.signature_report.get("source_sha256") != letter.sha256
        ):
            raise ValidationError("Podpisany PDF wymaga sprawdzenia integralności i raportu weryfikacji.")
    return payload


DEFAULT_TEMPLATES = {
    "APPLICATION": (
        "Wniosek o przydział",
        "${sender} składa wniosek o przydział: ${subject}.\nZnak sprawy: ${case_number}\nWnioskodawca: ${owner}\nAdres wnioskodawcy: ${owner_address}\nDane pojazdu: ${vehicle}\nStacja / przeznaczenie: ${station}\nUzasadnienie: ${justification}",
    ),
    "APPROVAL": (
        "Potwierdzenie możliwości wydania tablic indywidualnych",
        "W odpowiedzi na wniosek ${reference}, znak sprawy ${case_number}, potwierdzamy możliwość wydania tablic ${subject}.\nWnioskodawca: ${owner}\nUzasadnienie decyzji: ${reason}",
    ),
    "REJECTION": (
        "Odmowa przydziału",
        "W odpowiedzi na wniosek ${reference}, znak sprawy ${case_number}, odmawiamy przydziału: ${subject}.\nUzasadnienie: ${reason}",
    ),
    "POOL": (
        "Informacja o przydziale puli numerów",
        "Adresat otrzymuje pulę: ${subject}.\nOkres obowiązywania: ${period}\nStacja / przeznaczenie: ${station}",
    ),
}

TEMPLATE_VARIABLES = frozenset(
    {
        "sender",
        "recipient",
        "subject",
        "case_number",
        "owner",
        "owner_address",
        "vehicle",
        "justification",
        "reason",
        "request_id",
        "reference",
        "request_url",
        "period",
        "station",
    }
)


def validate_template(body):
    template = Template(body)
    if not template.is_valid() or set(template.get_identifiers()) - TEMPLATE_VARIABLES:
        raise ValidationError(
            "Szablon zawiera nieobsługiwaną zmienną lub niepoprawny znak $. Użyj $$ dla dosłownego dolara."
        )


def document_link(letter):
    base = settings.APP_URL.rstrip("/")
    parsed = urlsplit(base)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
        or (
            parsed.scheme != "https"
            and not (
                settings.LOCAL
                and parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
        )
    ):
        raise ValidationError(
            "Link dokumentu wymaga poprawnego APP_URL: HTTPS lub lokalnego adresu testowego."
        )
    if letter.request_id:
        return f"{base}/panel/wnioski/{letter.request.uuid}/"
    if letter.pool_id:
        return f"{base}/panel/pule/{letter.pool.uuid}/"
    return f"{base}/panel/pisma/"


def letter_content(kind, req, pool, sender, recipient):
    template = LetterTemplate.objects.filter(kind=kind).first()
    title, body = (template.title, template.body) if template else DEFAULT_TEMPLATES[kind]
    validate_template(body)
    subject = (
        req.record.display_number
        if req and req.record
        else (f"{req.get_kind_display()} - {req.count} numerów" if req else "")
    )
    if pool:
        subject = f"{pool.get_kind_display()}: {pool.slots.first().number} - {pool.slots.last().number} ({pool.total} numerów)"
    values = {
        "sender": sender.name,
        "recipient": recipient.name,
        "subject": subject,
        "case_number": req.case_number if req else "-",
        "owner": req.record.owner if req and req.record else "Wniosek urzędu",
        "owner_address": req.record.address or "Nie podano"
        if req and req.record
        else "Nie dotyczy - wniosek o pulę",
        "vehicle": req.record.vin or "Nie podano" if req and req.record else "Nie dotyczy - wniosek o pulę",
        "justification": req.justification.strip() or "Nie podano" if req else "Nie dotyczy",
        "reason": req.reason.strip() or "Nie podano" if req else "Nie dotyczy",
        "request_id": str(req.uuid) if req else "-",
        "reference": req.reference if req else "-",
        "request_url": f"{settings.APP_URL}/panel/wnioski/{req.uuid}/" if req else "-",
        "period": f"od {pool.valid_from:%d.%m.%Y} do {pool.valid_until:%d.%m.%Y}"
        if pool and pool.valid_until
        else (f"od {pool.valid_from:%d.%m.%Y}, bezterminowo" if pool else "Nie dotyczy"),
        "station": (pool.station or "Nie podano")
        if pool
        else (req.station or "Nie podano" if req and req.kind != "I" else "Nie dotyczy"),
    }
    try:
        rendered = Template(body).substitute(values)
    except (KeyError, ValueError) as exc:
        from django.core.exceptions import ValidationError

        raise ValidationError("Szablon zawiera nieobsługiwaną zmienną.") from exc
    return title, rendered, template.revision if template else 1


def render_pdf(letter):
    if "DynaSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DynaSans", settings.PDF_FONT))
    stream = BytesIO()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "Dyna",
        parent=styles["Normal"],
        fontName="DynaSans",
        fontSize=10,
        leading=16,
        spaceAfter=10,
    )
    title = ParagraphStyle(
        "TitleDyna",
        parent=normal,
        fontSize=16,
        leading=22,
        textColor=colors.HexColor("#183c55"),
        spaceAfter=18,
    )
    small = ParagraphStyle(
        "SmallDyna",
        parent=normal,
        fontSize=8,
        leading=12,
        textColor=colors.HexColor("#526372"),
    )
    right = ParagraphStyle("RightDyna", parent=normal, alignment=TA_RIGHT)
    link_style = ParagraphStyle("LinkDyna", parent=small, fontSize=8, leading=12, spaceAfter=4)
    p = lambda text, style=normal: Paragraph(escape(str(text)).replace("\n", "<br/>"), style)
    doc = BaseDocTemplate(
        stream,
        pagesize=(210 * mm, 297 * mm),
        rightMargin=22 * mm,
        leftMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=24 * mm,
        title=letter.title,
        author=letter.office.name,
    )
    head = Table(
        [
            [
                p(letter.office.name),
                p(f"{letter.office.city}, {timezone.localtime(letter.created_at):%d.%m.%Y}", right),
            ]
        ],
        colWidths=[100 * mm, 66 * mm],
    )
    head.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story = [
        head,
        p(f"Numer systemowy pisma: {letter.number}", small),
        Spacer(1, 8 * mm),
        p(f"Adresat: {letter.recipient.name}"),
        p(f"ADE: {letter.recipient.ade or 'nie skonfigurowano'}", small),
        Spacer(1, 8 * mm),
        p(letter.title, title),
    ]
    story.extend(p(line) for line in letter.body.split("\n"))
    url = document_link(letter)
    qr = QrCodeWidget(url, barWidth=32 * mm, barHeight=32 * mm, barLevel="M")
    drawing = Drawing(32 * mm, 32 * mm)
    drawing.add(qr)
    reference = (
        letter.request.reference
        if letter.request_id
        else ("Przydzielona pula" if letter.pool_id else "Pismo")
    )
    identifier = (
        letter.request.uuid if letter.request_id else (letter.pool.uuid if letter.pool_id else letter.uuid)
    )
    link = Paragraph(f'<link href={quoteattr(url)} color="#183c55">{escape(url)}</link>', link_style)
    related = Table(
        [
            [
                [
                    p(f"Powiązanie ze sprawą: {reference}", small),
                    p(f"Identyfikator: {identifier}", small),
                    link,
                    p("Otworzenie sprawy wymaga zalogowania i uprawnień urzędu.", link_style),
                ],
                drawing,
            ]
        ],
        colWidths=[126 * mm, 40 * mm],
    )
    related.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(KeepTogether([Spacer(1, 7 * mm), related]))
    story.extend(
        [
            Spacer(1, 12 * mm),
            p(
                "Dokument wygenerowany elektronicznie; sam wydruk nie potwierdza podpisu. Podpis sprawdź w czytniku PDF.",
                small,
            ),
        ]
    )
    if settings.LOCAL:
        story.append(
            p(
                "ŚRODOWISKO LOKALNE - dane fikcyjne. Wzór pisma wymaga zatwierdzenia przez urząd.",
                small,
            )
        )

    def footer(canvas, document):
        canvas.setFont("DynaSans", 8)
        canvas.setFillColor(colors.HexColor("#526372"))
        foot = Paragraph(escape(f"Dyna Rejestr Tablic | {letter.number}"), link_style)
        foot.wrap(145 * mm, 12 * mm)
        foot.drawOn(canvas, 22 * mm, 12 * mm)
        canvas.drawRightString(188 * mm, 14 * mm, f"Strona {document.page}")

    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id="Letter", frames=[frame], onPage=footer)])
    doc.build(story)
    return stream.getvalue()
