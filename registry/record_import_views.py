"""Import indywidualny: oryginalny CSV/XLSX i zatwierdzenie konkretnego podglądu."""

import csv
import secrets
from io import StringIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from .forms import RecordImportConfirmForm, RecordImportUploadForm
from .imports import FIELDS, apply_source_import, preview_source_import
from .models import PlateRecord
from .services import require_role
from .tabular_sources import pack_source, unpack_source

SESSION_KEY = "record_import_preview_v3"


def current_preview(request):
    saved = request.session.get(SESSION_KEY)
    if not saved or saved.get("user") != request.user.pk:
        return None
    created = parse_datetime(saved.get("created", ""))
    if not created or not 0 <= (timezone.now() - created).total_seconds() <= 900:
        request.session.pop(SESSION_KEY, None)
        return None
    return saved


@login_required
@require_http_methods(["GET", "POST"])
def import_records(request):
    require_role(request.user, "MAIN")
    request.session.pop("record_import_preview_v2", None)
    # Podgląd dawnego formularza nie określa wersji pliku ani daty ważności.
    request.session.pop("import_preview", None)
    if request.method == "GET" and request.GET.get("template") == "1":
        stream = StringIO()
        csv.writer(stream, delimiter=";").writerow(FIELDS)
        response = HttpResponse("\ufeff" + stream.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="wzor-ewidencji.csv"'
        return response
    upload_form, confirm_form = RecordImportUploadForm(), RecordImportConfirmForm()
    form, result = upload_form, None
    saved = current_preview(request)
    if request.method == "POST":
        if request.POST.get("action") == "confirm" or request.POST.get("confirm"):
            confirm_form = RecordImportConfirmForm(request.POST)
            form = confirm_form
            if confirm_form.is_valid():
                try:
                    if not saved or not secrets.compare_digest(
                        saved["token"].encode(), confirm_form.cleaned_data["preview_token"].encode()
                    ):
                        raise ValidationError(
                            "Podgląd wygasł lub został zastąpiony. Sprawdź właściwy plik ponownie."
                        )
                    count = apply_source_import(
                        request.user,
                        unpack_source(saved),
                        saved["sha256"],
                        confirm_form.cleaned_data["reason"],
                        filename=saved["filename"],
                        ip=request.META.get("REMOTE_ADDR"),
                        sheet_name=saved.get("source_sheet", ""),
                    )
                    request.session.pop(SESSION_KEY, None)
                    messages.success(
                        request,
                        f"Zaimportowano historyczny wykaz. Liczba wpisów: {count}. Nie utworzono nowych wniosków ani pism.",
                    )
                    return redirect("records_list")
                except ValidationError as error:
                    confirm_form.add_error(None, error)
        else:
            request.session.pop(SESSION_KEY, None)
            saved = None
            upload_form = RecordImportUploadForm(request.POST, request.FILES)
            form = upload_form
            if upload_form.is_valid():
                try:
                    upload = upload_form.cleaned_data["file"]
                    content = upload.read()
                    result = preview_source_import(
                        content, upload.name, upload_form.cleaned_data["sheet_name"]
                    )
                    if not result["errors"]:
                        saved = {
                            **pack_source(content, result),
                            "sha256": result["sha256"],
                            "token": secrets.token_hex(24),
                            "user": request.user.pk,
                            "created": timezone.now().isoformat(),
                            "filename": upload.name[:255],
                            "row_count": len(result["rows"]),
                        }
                        request.session[SESSION_KEY] = saved
                except UnicodeDecodeError:
                    upload_form.add_error("file", "Plik musi być zapisany jako CSV UTF-8.")
                except ValidationError as error:
                    upload_form.add_error("file", error)
    if saved:
        try:
            result = preview_source_import(
                unpack_source(saved), saved["filename"], saved.get("source_sheet", "")
            )
            if not confirm_form.is_bound:
                confirm_form = RecordImportConfirmForm(initial={"preview_token": saved["token"]})
        except ValidationError as error:
            if not upload_form.is_bound:
                upload_form = RecordImportUploadForm({})
                upload_form.full_clean()
            upload_form.add_error("file", error)
            form, saved, result = upload_form, None, None
            request.session.pop(SESSION_KEY, None)
    if result and result["errors"]:
        saved = None
        request.session.pop(SESSION_KEY, None)
    display_rows = (
        [
            {
                **row,
                "office_name": result["office_names"][row["office_id"]],
                "status_label": PlateRecord.Status(row["status"]).label,
            }
            for row in result["rows"]
        ]
        if result
        else []
    )
    return render(
        request,
        "registry/import.html",
        {
            "form": form,
            "upload_form": upload_form,
            "confirm_form": confirm_form,
            "preview": result,
            "preview_rows": Paginator(display_rows, 100).get_page(request.GET.get("page"))
            if result
            else None,
            "saved": saved,
        },
    )
