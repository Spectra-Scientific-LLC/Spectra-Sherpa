#!/usr/bin/env python3
"""Refuse signed release publication without the expected, byte-bound receipts."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

OWNED_EXECUTABLES = ("SpectraSherpa.exe", "resources/backend/SpectraSherpa.exe")


def load(directory: Path, name: str):
    return json.loads((directory / name).read_text(encoding="utf-8-sig"))


def signature(record: dict, expected_subject: str, path: Path | None = None) -> None:
    if not expected_subject or record.get("publisher") != expected_subject:
        raise ValueError("Signing receipt publisher differs")
    if any(record.get(key) is not True for key in ("timestamp_verified", "authenticode_verified", "signtool_verified")):
        raise ValueError("Incomplete signature verification")
    if not re.fullmatch(r"[A-Fa-f0-9]{40}", record.get("thumbprint", "")):
        raise ValueError("Missing signing certificate identity")
    if not re.fullmatch(r"[a-f0-9]{64}", record.get("sha256", "")):
        raise ValueError("Missing signed bytes identity")
    if path is not None and hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError("Signed bytes changed after verification")


def verify(target: str, directory: Path, bundle: Path, installer: Path, expected_subject: str) -> None:
    if target == "macos-arm64":
        for name in ("macos-app-notarization.json", "macos-dmg-notarization.json"):
            receipt = load(directory, name)
            if receipt.get("status") != "Accepted" or not receipt.get("id"):
                raise ValueError("Missing accepted Apple notarization receipt")
        return
    if target != "windows-x86_64":
        raise ValueError("Unsupported signing evidence target")
    binaries = {name: bundle / name for name in OWNED_EXECUTABLES}
    if any(not path.is_file() for path in binaries.values()):
        raise ValueError("Missing SpectraSherpa executable")
    records = load(directory, "windows-native-signatures.json")
    paths = [record["relative_path"] for record in records]
    if not binaries or len(set(paths)) != len(paths) or set(paths) != set(binaries):
        raise ValueError("Signing receipt does not cover every SpectraSherpa executable exactly once")
    for record in records:
        signature(record, expected_subject, binaries[record["relative_path"]])
    installed = load(directory, "windows-installer-signatures.json")
    signature(installed["installer"], expected_subject, installer)
    # The installer test verified this executable before uninstall removed it.
    signature(installed["uninstaller"], expected_subject)
    for name in (
        "windows-signing.log",
        "windows-verification.log",
        "windows-installer-signing.log",
        "native-install-identity.json",
    ):
        if not (directory / name).read_text(encoding="utf-8-sig").strip():
            raise ValueError("Empty Windows signing evidence")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    verify(
        args.target,
        Path("desktop/signing-evidence"),
        Path("desktop/electron/out/SpectraSherpa-win32-x64"),
        Path("desktop/Output/SpectraSherpa_Setup.exe"),
        os.environ.get("EXPECTED_SUBJECT", ""),
    )
