"""Zbiera tylko publiczne zasoby podczas build; nie używa trwałego dysku ani bazy."""

from .settings import *  # noqa: F403

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
