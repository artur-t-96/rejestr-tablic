import re

from django import forms

from .models import FlaggedWord, LetterTemplate, Office, PlateRecord, Request, User
from .services import COUNTY_FIELDS
from .validation import validate_number, validate_part, validate_vin


class LoginEmailForm(forms.Form):
    email = forms.EmailField(
        label="Służbowy adres e-mail",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )


class LoginCodeForm(forms.Form):
    code = forms.RegexField(
        r"^\d{8}$",
        label="Kod z wiadomości e-mail",
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "maxlength": 8,
            }
        ),
    )


class PoolImportUploadForm(forms.Form):
    sheet_name = forms.CharField(
        label="Nazwa arkusza (tylko XLSX)",
        max_length=31,
        required=False,
        help_text="Przy kilku arkuszach podaj dokładną nazwę. Dla jednego arkusza pozostaw puste.",
    )
    file = forms.FileField(
        label="Wykaz historycznych pul (CSV UTF-8 lub XLSX, do 2 MB)",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,.xlsx"}),
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith((".csv", ".xlsx")):
            raise forms.ValidationError("Wybierz CSV lub XLSX bez makr.")
        if upload.size > 2_000_000:
            raise forms.ValidationError("Wybierz CSV lub XLSX do 2 MB.")
        return upload


class PoolImportConfirmForm(forms.Form):
    preview_token = forms.CharField(max_length=48, widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Uzasadnienie i podstawa importu", max_length=1000, widget=forms.Textarea(attrs={"rows": 3})
    )
    acknowledged = forms.BooleanField(
        label="Potwierdzam zgodność wszystkich numerów, urzędów i dat z dokumentami źródłowymi."
    )


class RecordImportUploadForm(PoolImportUploadForm):
    file = forms.FileField(
        label="Historyczny wykaz tablic indywidualnych (CSV UTF-8 lub XLSX, do 2 MB)",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,.xlsx"}),
    )


class RecordImportConfirmForm(PoolImportConfirmForm):
    acknowledged = forms.BooleanField(
        label="Potwierdzam zgodność wszystkich wpisów, statusów i urzędów z dokumentami źródłowymi."
    )


class CheckForm(forms.Form):
    part = forms.CharField(
        label="Twój wyróżnik",
        max_length=5,
        min_length=3,
        widget=forms.TextInput(attrs={"placeholder": "np. KOWAL", "autocomplete": "off"}),
        help_text=(
            "Wpisz 3–5 znaków: litery A–Z z wyjątkiem Q. "
            "Cyfry mogą wystąpić wyłącznie na dwóch ostatnich pozycjach."
        ),
    )
    prefix = forms.ChoiceField(
        label="Województwo",
        choices=[("P", "P · Wielkopolska"), ("M", "M · Wielkopolska")],
    )
    digit = forms.ChoiceField(
        label="Cyfra",
        required=False,
        choices=[("", "Wszystkie cyfry")] + [(str(n), str(n)) for n in range(10)],
    )

    def clean_part(self):
        return validate_part(self.cleaned_data["part"])


class EDorSearchForm(forms.Form):
    entity_name = forms.CharField(label="Nazwa urzędu", min_length=2, max_length=2000)
    offset = forms.IntegerField(label="Strona wyników (od 0)", min_value=0, max_value=10000, initial=0)


class RequestForm(forms.Form):
    kind = forms.ChoiceField(label="Rodzaj wniosku", choices=Request.Kind.choices)
    number = forms.CharField(
        label="Pełny numer tablicy indywidualnej",
        required=False,
        help_text="Np. P0 KOWAL. Dla wniosku o pulę pozostaw puste.",
    )
    owner = forms.CharField(label="Właściciel / nazwa firmy", required=False, max_length=180)
    address = forms.CharField(label="Adres właściciela", required=False, max_length=300)
    vin = forms.CharField(label="VIN, jeśli znany", required=False, max_length=17)
    case_number = forms.CharField(label="Numer sprawy w urzędzie", max_length=100)
    count = forms.IntegerField(
        label="Liczba numerów (pule)", min_value=1, max_value=10000, initial=1, required=False
    )
    station = forms.CharField(label="Stacja / przeznaczenie (moduł III)", required=False, max_length=180)
    justification = forms.CharField(
        label="Uzasadnienie / uwagi",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and user.role == User.Role.MAIN:
            self.fields["kind"].choices = [(Request.Kind.INDIVIDUAL, Request.Kind.INDIVIDUAL.label)]
            self.initial["kind"] = Request.Kind.INDIVIDUAL
            self.fields["number"].help_text = "Np. P0 KOWAL."
            del self.fields["count"]
            del self.fields["station"]

    def clean(self):
        data = super().clean()
        if data.get("kind") == "I":
            data["count"] = 1
            for name, validator in [("number", validate_number), ("vin", validate_vin)]:
                try:
                    data[name] = validator(data.get(name, ""))
                except forms.ValidationError as exc:
                    self.add_error(name, exc)
            if not data.get("owner"):
                self.add_error("owner", "Podaj właściciela.")
        elif data.get("kind") in {"II", "III"}:
            if data.get("count") is None and "count" not in self.errors:
                self.add_error("count", "Podaj liczbę numerów.")
            if not data.get("justification"):
                self.add_error("justification", "Podaj uzasadnienie zapotrzebowania.")
        return data


class PoolForm(forms.Form):
    kind = forms.ChoiceField(label="Moduł", choices=Request.Kind.choices[1:])
    office = forms.ModelChoiceField(label="Urząd", queryset=Office.objects.filter(active=True))
    prefix = forms.CharField(
        label="Prefiks",
        initial="P",
        max_length=2,
        help_text="II: P lub M. III: P0–P9 / M0–M9. M wymaga wyczerpania pojemności P.",
    )
    start = forms.IntegerField(label="Od pozycji", min_value=1)
    end = forms.IntegerField(
        label="Do pozycji",
        min_value=1,
        help_text="II: kolejny układ wymaga wyczerpania wcześniejszych. III: 1–9999 to cyfry, dalej 001A–999Y (do 29979).",
    )
    valid_from = forms.DateField(
        label="Obowiązuje od", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    valid_until = forms.DateField(
        label="Obowiązuje do",
        required=False,
        help_text="Dla modułu III podaj obowiązkowy termin końca puli.",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    station = forms.CharField(label="Stacja / przeznaczenie", required=False)

    def clean(self):
        data = super().clean()
        if data.get("kind") == "III" and not data.get("valid_until") and "valid_until" not in self.errors:
            self.add_error("valid_until", "Podaj termin końca puli modułu III.")
        return data


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(label="Decyzja", choices=[("approve", "Akceptuję"), ("reject", "Odrzucam")])
    reason = forms.CharField(
        label="Uzasadnienie (obowiązkowe przy odmowie)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    prefix = forms.CharField(label="Prefiks puli", required=False)
    start = forms.IntegerField(label="Pula od pozycji", required=False, min_value=1)
    end = forms.IntegerField(
        label="Pula do pozycji",
        required=False,
        min_value=1,
        help_text="II: kolejny układ wymaga wyczerpania wcześniejszych. III: litery od pozycji 10000 wymagają wcześniejszych 9999 numerów.",
    )
    valid_from = forms.DateField(
        label="Pula obowiązuje od",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    valid_until = forms.DateField(
        label="Pula obowiązuje do",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, kind="I", **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        if kind == "III":
            self.fields["valid_until"].help_text = "Wymagane przy akceptacji puli modułu III."

    def clean(self):
        data = super().clean()
        if (
            self.kind == "III"
            and data.get("decision") == "approve"
            and not data.get("valid_until")
            and "valid_until" not in self.errors
        ):
            self.add_error("valid_until", "Podaj termin końca puli modułu III.")
        return data


class RecordForm(forms.ModelForm):
    reason = forms.CharField(label="Powód zmiany", widget=forms.Textarea(attrs={"rows": 2}))
    version = forms.IntegerField(widget=forms.HiddenInput)

    class Meta:
        model = PlateRecord
        fields = [
            "owner",
            "address",
            "office",
            "status",
            "vin",
            "make",
            "model",
            "registration_date",
            "sale_date",
            "buyer",
            "letter_number",
            "note",
        ]
        labels = {
            "owner": "Właściciel",
            "address": "Adres",
            "office": "Urząd prowadzący",
            "status": "Status",
            "vin": "VIN",
            "make": "Marka",
            "model": "Model",
            "registration_date": "Data rejestracji",
            "sale_date": "Data zbycia",
            "buyer": "Nabywca",
            "letter_number": "Numer pisma",
            "note": "Uwagi",
        }
        widgets = {
            k: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            for k in ["registration_date", "sale_date"]
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = self.instance.version
        self.fields["office"].queryset = Office.objects.filter(active=True)
        if user.role == "COUNTY":
            for field in list(self.fields):
                if field not in COUNTY_FIELDS + ["reason", "version"]:
                    del self.fields[field]
        elif Request.objects.filter(record=self.instance, status__in=["DRAFT", "SENT"]).exists():
            # Status wpisu z otwartym wnioskiem zmienia decyzja albo wycofanie, nie korekta.
            del self.fields["status"]


class OfficeForm(forms.ModelForm):
    class Meta:
        model = Office
        fields = [
            "id",
            "name",
            "kind",
            "city",
            "teryt",
            "ade",
            "email",
            "allowed_domains",
            "active",
        ]
        labels = {
            "id": "Kod urzędu",
            "name": "Nazwa",
            "kind": "Rodzaj",
            "city": "Miejscowość",
            "teryt": "TERYT",
            "ade": "Adres e-Doręczeń",
            "email": "E-mail kontaktowy",
            "allowed_domains": "Dozwolone domeny e-mail (lista JSON)",
            "active": "Aktywny",
        }


def account_settings_snapshot(user):
    return {
        "id": user.pk,
        **{key: getattr(user, key) for key in UserForm.Meta.fields if key != "office"},
        "office": user.office_id,
    }


class UserForm(forms.ModelForm):
    account_version = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        from django.core import signing

        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["account_version"].required = True
            self.initial["account_version"] = signing.dumps(
                account_settings_snapshot(self.instance), salt="admin-account-version"
            )

    reason = forms.CharField(
        label="Powód utworzenia lub zmiany konta", max_length=1000, widget=forms.Textarea(attrs={"rows": 2})
    )

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "role", "office", "is_active"]
        labels = {
            "email": "E-mail",
            "first_name": "Imię",
            "last_name": "Nazwisko",
            "role": "Rola",
            "office": "Urząd",
            "is_active": "Aktywne konto",
        }

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        matches = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            matches = matches.exclude(pk=self.instance.pk)
        if matches.exists():
            raise forms.ValidationError("Konto z tym adresem e-mail już istnieje.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email.lower()
        user.email = user.email.lower()
        if not user.pk:
            user.set_unusable_password()
        if commit:
            user.save()
        return user


class FlaggedWordForm(forms.ModelForm):
    class Meta:
        model = FlaggedWord
        fields = ["word", "note"]
        labels = {"word": "Ciąg liter (2–5)", "note": "Uwaga dla urzędnika UMP"}
        help_texts = {
            "word": "Wniosek o wyróżnik zawierający ten ciąg dostanie ostrzeżenie. Nie blokuje decyzji.",
        }

    def clean_word(self):
        word = self.cleaned_data["word"].strip().upper()
        if not re.fullmatch(r"[A-PR-Z]{2,5}", word):
            raise forms.ValidationError("Podaj 2–5 liter A–Z bez Q, bez cyfr i spacji.")
        return word


class TemplateForm(forms.ModelForm):
    def clean_body(self):
        from .documents import validate_template

        body = self.cleaned_data["body"]
        validate_template(body)
        return body

    class Meta:
        model = LetterTemplate
        fields = ["title", "body"]
        labels = {"title": "Tytuł pisma", "body": "Treść (zmienne w formacie ${nazwa})"}


class LetterRevisionForm(forms.Form):
    reason = forms.CharField(
        label="Uzasadnienie nowej wersji", max_length=500, widget=forms.Textarea(attrs={"rows": 3})
    )


class EZDIncomingForm(forms.Form):
    number = forms.IntegerField(label="Numer RPW", min_value=1, max_value=2147483647)
    year = forms.IntegerField(label="Rok RPW", min_value=2000, max_value=9999)
    reason = forms.CharField(label="Uzasadnienie odczytu", max_length=500)


class EDorResumeForm(forms.Form):
    reason = forms.CharField(
        label="Uzasadnienie wznowienia", max_length=500, widget=forms.Textarea(attrs={"rows": 3})
    )
    mode = forms.ChoiceField(
        choices=[("UNSENT", "UNSENT"), ("OBSERVATION", "OBSERVATION")], widget=forms.HiddenInput
    )
    expected_updated_at = forms.DateTimeField(widget=forms.HiddenInput)


class SignatureForm(forms.Form):
    method = forms.ChoiceField(
        label="Sposób podpisania",
        choices=[("IMPORT", "Import podpisanego PDF"), ("LOCAL", "Podpis kluczem urzędu")],
    )
    file = forms.FileField(label="Podpisany oryginał PDF (do 10 MB)", required=False)
    reason = forms.CharField(label="Uzasadnienie", max_length=500, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        values = super().clean()
        upload = values.get("file")
        if values.get("method") == "IMPORT" and not upload:
            self.add_error("file", "Wybierz podpisany plik PDF.")
        if upload and upload.size > 10 * 1024 * 1024:
            self.add_error("file", "Plik przekracza 10 MB.")
        if values.get("method") == "LOCAL" and upload:
            self.add_error("file", "Usuń plik przy podpisywaniu kluczem urzędu.")
        return values


class EZDRegisterForm(forms.Form):
    case_id = forms.CharField(
        label="Identyfikator istniejącej sprawy w EZD RP",
        required=False,
        max_length=180,
        help_text="Wklej identyfikator API sprawy, nie jej znak kancelaryjny.",
    )
    case_number = forms.IntegerField(
        label="Numer nowej sprawy w EZD RP",
        required=False,
        min_value=1,
        max_value=2147483647,
        help_text="Wypełnij tylko przy tworzeniu nowej sprawy. Numer musi być uzgodniony z kancelarią. JRWA i rok określa konfiguracja.",
    )
    reason = forms.CharField(
        label="Uzasadnienie powiązania", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, linked=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.linked = linked
        if linked:
            for name in ("case_id", "case_number", "reason"):
                self.fields.pop(name)

    def clean(self):
        values = super().clean()
        if not self.linked and not self.errors:
            if bool(values.get("case_id")) == bool(values.get("case_number")):
                raise forms.ValidationError("Wskaż istniejącą sprawę albo podaj numer nowej sprawy.")
            if not values.get("reason", "").strip():
                self.add_error("reason", "Podaj uzasadnienie powiązania dokumentu ze sprawą EZD.")
        return values
