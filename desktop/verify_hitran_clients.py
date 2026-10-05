"""Verify retained source/notices, then exercise clients in the built executable."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from hitran_bundle import CLIENTS, _read_member


def verify_payload(payload: Path) -> None:
    if json.loads((payload / "manifest.json").read_text(encoding="utf-8")) != CLIENTS:
        raise ValueError("HITRAN source manifest differs from the approved desktop pins")
    for name, entry in CLIENTS.items():
        source = (payload / entry["filename"]).read_bytes()
        if hashlib.sha256(source).hexdigest() != entry["sha256"]:
            raise ValueError(f"{name}: retained source SHA256 mismatch")
        expected_license = _read_member(source, entry["filename"], entry["license_member"])
        if (payload / f"{name}-LICENSE.txt").read_bytes() != expected_license:
            raise ValueError(f"{name}: missing or altered upstream license")
    if not (payload / "README.txt").read_text(encoding="utf-8").strip():
        raise ValueError("HITRAN source directions missing")


def verify(root: Path) -> None:
    payloads = list(root.rglob("third_party/hitran/manifest.json"))
    if not payloads:
        raise ValueError("HITRAN source and notices missing from desktop bundle")
    for manifest in payloads:
        verify_payload(manifest.parent)
    executables = [root / name for name in ("SpectraSherpa", "SpectraSherpa.exe") if (root / name).is_file()]
    if len(executables) != 1:
        raise ValueError("Expected one frozen desktop backend")
    with tempfile.TemporaryDirectory(prefix="sherpa-hitran-receipt-") as directory:
        receipt = Path(directory) / "receipt.json"
        # A developer's disabled JIT or custom locator must not hide packaging
        # failures. Preserve platform launch variables, but qualify default JIT.
        environment = {key: value for key, value in os.environ.items() if not key.startswith("NUMBA_")}
        environment.update(SPECTRA_DESKTOP_NO_DIALOG="1", MPLCONFIGDIR=str(Path(directory) / "matplotlib"))
        subprocess.run(
            [str(executables[0].resolve()), "--verify-hitran-clients", str(receipt)],
            cwd=directory,
            env=environment,
            check=True,
            timeout=120,
        )
        result = json.loads(receipt.read_text(encoding="utf-8"))
        if result.get("versions") != {name: entry["version"] for name, entry in CLIENTS.items()}:
            raise ValueError("Frozen HITRAN client versions differ from retained source")
        if result.get("offline") is not True or result.get("sqlite_query") != 1:
            raise ValueError("Frozen HITRAN qualification did not finish")
        print("Offline frozen HAPI/HAPI2 qualification:", json.dumps(result, sort_keys=True), flush=True)
