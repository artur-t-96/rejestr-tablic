#!/usr/bin/env python3
"""Inventory downloaded wheels and preserve their supplied licence notices.

Reads archives without importing or executing packages. Requires every archive
to match its pinned version and a SHA-256 in the lock. Does not establish legal
compliance, vulnerability status, or execution on the archive's target platform.
"""

import argparse
import email
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lock(path):
    text = path.read_text()
    pins = {}
    for entry in text.replace("\\\n", " ").splitlines():
        match = re.match(r"^([\w.-]+)==([^\s;]+)", entry)
        if match:
            name, version = match.groups()
            key = canonical(name)
            if key in pins:
                raise ValueError(f"Multiple pins unsupported for inventory: {name}")
            pins[key] = (version, set(re.findall(r"--hash=sha256:([a-f0-9]{64})", entry)))
    if not pins or any(not hashes for _version, hashes in pins.values()):
        raise ValueError("Every lock entry must have an exact version and SHA-256.")
    return pins


def wheel_record(path, pins, notices):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as archive:
        metadata_files = [item for item in archive.namelist() if item.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise ValueError(f"Expected one METADATA: {path.name}")
        metadata = email.message_from_bytes(archive.read(metadata_files[0]))
        name, version = metadata["Name"], metadata["Version"]
        key = canonical(name)
        if key not in pins or version != pins[key][0] or digest not in pins[key][1]:
            raise ValueError(f"Wheel does not match the locked name/version/hash: {path.name}")
        licence = (
            metadata.get("License-Expression")
            or "; ".join(
                item.removeprefix("License :: ")
                for item in metadata.get_all("Classifier", [])
                if item.startswith("License :: ")
            )
            or metadata.get("License", "Unspecified")
        )
        record = {
            "name": name,
            "version": version,
            "wheel": path.name,
            "sha256": digest,
            "hash_matches_lock": True,
            "license_metadata": licence,
            "registry": f"https://pypi.org/project/{name}/{version}/",
            "notices": [],
        }
        for item in archive.infolist():
            source = PurePosixPath(item.filename)
            if item.is_dir() or not any(
                word in source.name.lower() for word in ("license", "licence", "copying", "notice")
            ):
                continue
            if source.is_absolute() or ".." in source.parts or "\\" in item.filename:
                raise ValueError(f"Unsafe notice path: {path.name}")
            if item.file_size > 2 * 1024 * 1024:
                raise ValueError(f"Oversized notice: {path.name}")
            content = archive.read(item)
            # Reject binary data: notices must be readable redistribution files.
            content.decode("utf-8")
            notice_hash = hashlib.sha256(content).hexdigest()
            target = notices / f"{key}-{version}" / Path(*source.parts)
            if target.exists() and target.read_bytes() != content:
                target = target.with_name(f"{notice_hash[:16]}-{target.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(content)
            record["notices"].append(
                {"archive_path": item.filename, "path": target.as_posix(), "sha256": notice_hash}
            )
        record["notice_present"] = bool(record["notices"])
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--target", required=True, help="Recorded target label, not an execution claim")
    parser.add_argument("--wheels", required=True, type=Path)
    parser.add_argument("--notices", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        pins = read_lock(args.lock)
        wheels = sorted(args.wheels.glob("*.whl"))
        if not wheels:
            raise ValueError("No wheel archives found.")
        if args.output.exists():
            raise ValueError("Inventory output already exists; choose a new path.")
        records = [wheel_record(path, pins, args.notices) for path in wheels]
        names = [canonical(record["name"]) for record in records]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate packages in wheel directory.")
        report = {
            "target": args.target,
            "lock": args.lock.as_posix(),
            "lock_sha256": hashlib.sha256(args.lock.read_bytes()).hexdigest(),
            "package_count": len(records),
            "packages": records,
            "target_execution_verified": False,
            "complete_license_compliance_verified": False,
            "bundled_native_components_fully_inventoried": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(f"{args.target}: {len(records)} locked wheels inventoried.")
    except (ValueError, OSError, zipfile.BadZipFile, UnicodeError) as exc:
        parser.exit(1, f"Inventory failed: {exc}\n")


if __name__ == "__main__":
    main()
