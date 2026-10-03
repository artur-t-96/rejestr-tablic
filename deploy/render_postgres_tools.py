"""Oficjalne klienty PGDG 18.6 dla natywnego Render Debian 12, bez sudo."""

import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / ".render-postgres"
VERSION = "18.6-1.pgdg12+2"
PACKAGES = (
    ("libpq5", 265280, "9dc15f3f41090e632e0449693323f18c96bfd25794c439d8bcde06af6c5012f6"),
    ("postgresql-client-18", 2134056, "6105a64b8166ae06c2b6c681d7e600458c598151c08b0f10bf5fa25ac711d6b9"),
)


def run(arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=60).stdout.strip()


def validate(directory):
    receipt = {"version": VERSION, "packages": [list(package) for package in PACKAGES]}
    if json.loads((directory / "receipt.json").read_text()) != receipt:
        raise RuntimeError("Unexpected PostgreSQL tools receipt.")
    for name in ("pg_dump", "pg_restore", "psql"):
        if run([str(directory / "bin" / name), "--version"]) not in {
            f"{name} (PostgreSQL) 18.6", f"{name} (PostgreSQL) 18.6 (Debian {VERSION})"
        }:
            raise RuntimeError("Unexpected PostgreSQL client version.")


def main():
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise SystemExit("Render tools require Linux amd64; local/on-prem tools are configured separately.")
    release = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
    if release.get("ID", "").strip('"') != "debian" or release.get("VERSION_ID", "").strip('"') != "12":
        raise SystemExit("Render tools require the documented Debian 12 native runtime.")
    if DESTINATION.exists():
        validate(DESTINATION)
        return
    with tempfile.TemporaryDirectory(prefix=".render-pg-", dir=ROOT) as work:
        work = Path(work)
        extracted = work / "tools"
        extracted.mkdir()
        for name, size, digest in PACKAGES:
            filename = f"{name}_{VERSION}_amd64.deb"
            url = f"https://apt.postgresql.org/pub/repos/apt/pool/main/p/postgresql-18/{filename}"
            with urllib.request.urlopen(url, timeout=30) as response:
                if response.url != url:
                    raise RuntimeError("Unexpected package redirect.")
                payload = response.read(size + 1)
            if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
                raise RuntimeError("PostgreSQL package integrity check failed.")
            archive = work / filename
            archive.write_bytes(payload)
            if run(["dpkg-deb", "-f", str(archive), "Package", "Version", "Architecture"]) != (
                f"Package: {name}\nVersion: {VERSION}\nArchitecture: amd64"
            ):
                raise RuntimeError("Unexpected PostgreSQL package metadata.")
            # Extract only; no package install or maintainer scripts, no system changes.
            run(["dpkg-deb", "--extract", str(archive), str(extracted)])
        (extracted / "bin").mkdir()
        for name in ("pg_dump", "pg_restore", "psql"):
            wrapper = extracted / "bin" / name
            wrapper.write_text(
                '#!/bin/sh\nset -eu\n'
                'tool_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
                'export LD_LIBRARY_PATH="$tool_root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
                f'exec "$tool_root/usr/lib/postgresql/18/bin/{name}" "$@"\n'
            )
            wrapper.chmod(0o755)
        (extracted / "receipt.json").write_text(json.dumps({"version": VERSION, "packages": list(PACKAGES)}))
        validate(extracted)
        shutil.move(str(extracted), str(DESTINATION))
    print("Verified PostgreSQL 18.6 clients installed in the application build directory.")


if __name__ == "__main__":
    main()
