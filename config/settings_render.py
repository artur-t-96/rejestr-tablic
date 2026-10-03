import os

from .render import build_settings
from .settings import *  # noqa: F403

globals().update(build_settings(os.environ, globals()))
