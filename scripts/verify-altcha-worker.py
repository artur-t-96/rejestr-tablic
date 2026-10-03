"""Offline interoperability check of the shipped worker and Python verifier.

Uses synthetic vectors, no browser, application session, database or network.
Run with the project's Python and a host-native Node.js on PATH.
"""

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from altcha import Payload, Solution, create_challenge, verify_solution

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "registry" / "static" / "registry" / "altcha"
TEST_SECRET = "synthetic-offline-interoperability-secret"
HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const challenge = JSON.parse(fs.readFileSync(0, 'utf8'));
let reply;
const self = { postMessage(value) { reply = value; } };
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  self, crypto: webcrypto, performance, TextEncoder, AbortController,
  ArrayBuffer, DataView, Uint8Array, setTimeout,
}, { timeout: 1000 });
(async () => {
  await self.onmessage({ data: { type: 'work', challenge, timeout: 30000 } });
  if (!reply || reply.error) throw new Error('Worker failed: ' + reply?.error);
  process.stdout.write(JSON.stringify(reply));
})().catch(error => { process.stderr.write(String(error)); process.exitCode = 1; });
"""


def main():
    node = shutil.which("node")
    if not node:
        raise SystemExit("Host-native Node.js is required for this optional check.")
    manifest = json.loads((VENDOR / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        actual = hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Vendor file integrity mismatch: {name}")
    report = {"widget_version": manifest["version"], "vendor_integrity": "PASS", "vectors": []}
    for name, options in [
        ("known-counter", {"counter": 17}),
        ("application-prefix", {"key_prefix": "00"}),
    ]:
        challenge = create_challenge(
            algorithm="PBKDF2/SHA-256",
            cost=5000,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            data={"purpose": "synthetic-offline-interop"},
            hmac_secret=TEST_SECRET,
            **options,
        )
        result = subprocess.run(
            [node, "-e", HARNESS, str(VENDOR / "pbkdf2.js")],
            input=json.dumps(challenge.to_dict()),
            text=True,
            capture_output=True,
            check=True,
            timeout=45,
        )
        reply = json.loads(result.stdout)
        payload = Payload(challenge, Solution(reply["counter"], reply["derivedKey"]))
        if not verify_solution(payload, TEST_SECRET).verified:
            raise RuntimeError(f"Python rejected the actual worker solution: {name}")
        if name == "known-counter" and reply["counter"] != 17:
            raise RuntimeError("Worker counter encoding does not match the Python vector.")
        tampered = Payload(challenge, Solution(reply["counter"], "0" * 64))
        if verify_solution(tampered, TEST_SECRET).verified:
            raise RuntimeError("Python accepted a tampered worker result.")
        report["vectors"].append(
            {
                "name": name,
                "algorithm": "PBKDF2/SHA-256",
                "cost": 5000,
                "counter": reply["counter"],
                "worker_time_ms": reply["time"],
                "python_verification": "PASS",
                "tampered_result_rejected": True,
            }
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
