"""Signing evidence is mandatory and must cover the bytes being released."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("signing_evidence", PACKAGE / "desktop/verify_signing_evidence.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


def receipt(path):
    return dict(
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        publisher="synthetic publisher",
        thumbprint="a" * 40,
        timestamp_verified=True,
        authenticode_verified=True,
        signtool_verified=True,
    )


def fixture(root):
    directory, bundle = root / "evidence", root / "bundle"
    directory.mkdir()
    bundle.mkdir()
    records = []
    for name in evidence.OWNED_EXECUTABLES:
        path = bundle / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        records.append(dict(receipt(path), relative_path=name))
    (directory / "windows-native-signatures.json").write_text(json.dumps(records))
    installer = root / "setup.exe"
    installer.write_bytes(b"synthetic signed installer")
    (directory / "windows-installer-signatures.json").write_text(
        json.dumps(dict(installer=receipt(installer), uninstaller=receipt(installer)))
    )
    for name in (
        "windows-signing.log",
        "windows-verification.log",
        "windows-installer-signing.log",
        "native-install-identity.json",
    ):
        (directory / name).write_text("synthetic evidence")
    return directory, bundle, installer


def test_owned_executables_and_installer_are_bound_to_receipts(tmp_path):
    paths = fixture(tmp_path)
    evidence.verify("windows-x86_64", *paths, "synthetic publisher")


@pytest.mark.parametrize(
    "defect", ["missing", "executable", "changed", "installer", "timestamp", "publisher", "duplicate", "log"]
)
def test_incomplete_or_stale_windows_evidence_refuses(tmp_path, defect):
    directory, bundle, installer = fixture(tmp_path)
    path = directory / "windows-native-signatures.json"
    records = json.loads(path.read_text())
    if defect == "missing":
        path.unlink()
    elif defect == "executable":
        (bundle / evidence.OWNED_EXECUTABLES[1]).unlink()
    elif defect == "changed":
        (bundle / evidence.OWNED_EXECUTABLES[0]).write_bytes(b"changed after signing")
    elif defect == "installer":
        installer.write_bytes(b"changed")
    elif defect == "log":
        (directory / "windows-verification.log").write_text("")
    else:
        if defect == "duplicate":
            records.append(records[0])
        elif defect == "timestamp":
            records[0]["timestamp_verified"] = False
        else:
            records[0]["publisher"] = "wrong publisher"
        path.write_text(json.dumps(records))
    with pytest.raises((ValueError, FileNotFoundError)):
        evidence.verify("windows-x86_64", directory, bundle, installer, "synthetic publisher")


@pytest.mark.parametrize("missing", ["macos-app-notarization.json", "macos-dmg-notarization.json"])
def test_macos_requires_both_accepted_receipts_even_with_other_evidence(tmp_path, missing):
    for name in ("macos-app-notarization.json", "macos-dmg-notarization.json"):
        (tmp_path / name).write_text('{"status":"Accepted","id":"synthetic"}')
    evidence.verify("macos-arm64", tmp_path, tmp_path, tmp_path, "")
    (tmp_path / missing).unlink()
    with pytest.raises(FileNotFoundError):
        evidence.verify("macos-arm64", tmp_path, tmp_path, tmp_path, "")


def test_third_party_files_do_not_require_our_publisher_receipts(tmp_path):
    directory, bundle, installer = fixture(tmp_path)
    for name in ("vendor.exe", "electron.dll", "numpy.pyd", "addon.node"):
        (bundle / name).write_bytes(b"third-party bytes and signatures are preserved")
    evidence.verify("windows-x86_64", directory, bundle, installer, "synthetic publisher")
