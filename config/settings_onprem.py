"""Wybierz jawnie przez DJANGO_SETTINGS_MODULE=config.settings_onprem."""

import os

from .onprem import build_settings
from .settings import *  # noqa: F403

globals().update(build_settings(os.environ, globals()))
