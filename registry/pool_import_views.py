"""Podgląd powiązany z sesją i wersją; ponowna walidacja przed transakcją."""

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

from .forms import PoolImportConfirmForm, PoolImportUploadForm
from .pool_imports import FIELDS, apply_pool_import, preview_pool_source
from .services import require_role
from .tabular_sources import pack_source, unpack_source

SESSION_KEY = "pool_import_preview_v2"


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
def import_pools(request):
    require_role(request.user, "MAIN")
    request.session.pop("pool_import_preview", None)
    if request.method == "GET" and request.GET.get("template") == "1":
        stream = StringIO()
        csv.writer(stream, delimiter=";").writerow(FIELDS)
        response = HttpResponse("\ufeff" + stream.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="wzor-pul.csv"'
        return response
    upload_form, confirm_form = PoolImportUploadForm(), PoolImportConfirmForm()
    form, result = upload_form, None
    saved = current_preview(request)
    if request.method == "POST":
        if request.POST.get("action") == "confirm":
            confirm_form = PoolImportConfirmForm(request.POST)
            form = confirm_form
            if confirm_form.is_valid():
                try:
                    if not saved or not secrets.compare_digest(
                        saved["token"].encode("utf-8"),
                        confirm_form.cleaned_data["preview_token"].encode("utf-8"),
                    ):
                        raise ValidationError(
                            "Podgląd wygasł lub został zastąpiony. Sprawdź właściwy plik ponownie."
                        )
                    pools = apply_pool_import(
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
                        f"Zaimportowano historyczny wykaz. Liczba pul: {len(pools)}; liczba numerów: {saved['row_count']}. Nie utworzono nowych decyzji ani pism.",
                    )
                    return redirect("pools_list")
                except ValidationError as error:
                    confirm_form.add_error(None, error)
        else:
            request.session.pop(SESSION_KEY, None)
            saved = None
            upload_form = PoolImportUploadForm(request.POST, request.FILES)
            form = upload_form
            if upload_form.is_valid():
                try:
                    upload = upload_form.cleaned_data["file"]
                    content = upload.read()
                    result = preview_pool_source(content, upload.name, upload_form.cleaned_data["sheet_name"])
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
            result = preview_pool_source(
                unpack_source(saved), saved["filename"], saved.get("source_sheet", "")
            )
            if not confirm_form.is_bound:
                confirm_form = PoolImportConfirmForm(initial={"preview_token": saved["token"]})
        except ValidationError as error:
            if not upload_form.is_bound:
                upload_form = PoolImportUploadForm({})
                upload_form.full_clean()
            upload_form.add_error("file", error)
            form, saved, result = upload_form, None, None
            request.session.pop(SESSION_KEY, None)
    if result and result["errors"]:
        saved = None
        request.session.pop(SESSION_KEY, None)
    return render(
        request,
        "registry/import_pools.html",
        {
            "form": form,
            "upload_form": upload_form,
            "confirm_form": confirm_form,
            "preview": result,
            "preview_rows": Paginator(result["rows"], 100).get_page(request.GET.get("page"))
            if result
            else None,
            "saved": saved,
        },
    )
