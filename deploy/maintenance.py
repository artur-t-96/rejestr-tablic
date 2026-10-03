"""Wąska lista czynności instalacyjnych, z osobnym kontem PostgreSQL."""

import os
import subprocess
import sys
from pathlib import Path

actions = {
    "migrate": ["migrate", "--noinput"],
    "collectstatic": ["collectstatic", "--noinput"],
    "initialize": ["initialize_registry", "--admin-email", os.environ.get("DYNA_INITIAL_ADMIN_EMAIL", "")],
}
if len(sys.argv) != 2 or sys.argv[1] not in actions:
    raise SystemExit("Wybierz migrate, collectstatic albo initialize.")
if sys.argv[1] == "initialize" and not os.environ.get("DYNA_INITIAL_ADMIN_EMAIL"):
    raise SystemExit("Brak DYNA_INITIAL_ADMIN_EMAIL w konfiguracji instalacyjnej.")
if sys.argv[1] == "collectstatic":
    # Wyłącznie publiczne zasoby muszą być czytelne dla procesu Nginx.
    os.umask(0o022)
root = Path(__file__).resolve().parents[1]
result = subprocess.run([sys.executable, str(root / "manage.py"), *actions[sys.argv[1]]], cwd=root)
raise SystemExit(result.returncode)
