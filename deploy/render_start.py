"""Jeden dysk Render dla WWW i kolejek; błąd procesu zatrzymuje całą instancję."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main():
    os.umask(0o077)
    data_dir = Path(os.environ.get("DYNA_DATA_DIR", ""))
    if not data_dir.is_absolute() or not os.path.ismount(data_dir):
        raise SystemExit("Brak zamontowanego trwałego dysku DYNA_DATA_DIR.")
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings_render"
    # Dysk dostępny dopiero w start command. Nie inicjalizujemy kont ani fikcyjnych danych.
    subprocess.run([sys.executable, "manage.py", "check", "--deploy", "--fail-level", "ERROR"], check=True)
    subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], check=True)
    commands = [
        [sys.executable, "-m", "gunicorn", "config.wsgi:application", "--config", "deploy/render-gunicorn.py"],
        [sys.executable, "manage.py", "expire_reservations", "--watch"],
        [sys.executable, "manage.py", "process_integrations", "--watch"],
        [sys.executable, "manage.py", "process_account_invitations", "--watch"],
    ]
    children = []
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    result = 0
    try:
        for command in commands:
            if stopping:
                break
            children.append(subprocess.Popen(command, start_new_session=True))
        while not stopping:
            if any(child.poll() is not None for child in children):
                result = 1
                break
            time.sleep(0.25)
    finally:
        for child in children:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 25
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
