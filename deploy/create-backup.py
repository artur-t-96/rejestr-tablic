"""Nowa nazwa przy każdej próbie; niczego nie usuwa i nie nadpisuje."""

import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex + ".zip"
result = subprocess.run(
    [
        sys.executable,
        str(root / "manage.py"),
        "backup_registry",
        "--output",
        str(Path("/var/backups/dyna") / name),
    ],
    cwd=root,
)
raise SystemExit(result.returncode)
