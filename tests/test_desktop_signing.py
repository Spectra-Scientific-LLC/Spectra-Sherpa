"""Signing orchestration safety; native signing remains a release-environment test."""

import importlib.util
import json
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("desktop_sign_macos", PACKAGE / "desktop/sign_macos.py")
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


def test_signing_orders_inner_code_before_enclosing_framework_and_skips_symlinks(tmp_path):
    app = tmp_path / "Example.app"
    framework = app / "Contents/Frameworks/Python.framework"
    binary = framework / "Versions/3.11/Python"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\xcf\xfa\xed\xfe" + b"fake native binary")
    (framework / "Python").symlink_to("Versions/3.11/Python")
    data = app / "Contents/config.json"
    data.write_text("{}")
    assert signing.signing_targets(app) == [binary, framework]


@pytest.mark.parametrize("status", ["Invalid", "In Progress", "Rejected", None])
def test_notary_success_exit_is_not_acceptance(monkeypatch, tmp_path, status):
    monkeypatch.setattr(signing, "run", lambda *args: json.dumps({"id": "synthetic", "status": status}))
    receipt = tmp_path / "receipt.json"
    with pytest.raises(RuntimeError, match="not Accepted"):
        signing.notarize(tmp_path / "candidate.zip", tmp_path / "keychain", receipt)
    assert json.loads(receipt.read_text())["status"] == status


def test_notary_acceptance_is_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(signing, "run", lambda *args: '{"id":"synthetic", "status":"Accepted"}')
    receipt = tmp_path / "receipt.json"
    signing.notarize(tmp_path / "candidate.zip", tmp_path / "keychain", receipt)
    assert json.loads(receipt.read_text())["status"] == "Accepted"


def test_command_failures_do_not_echo_credentials(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(signing.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError) as exc:
        signing.run("security", "import", "--password", "synthetic-private-password")
    assert "synthetic-private-password" not in str(exc.value)


def test_windows_requires_trusted_timestamp_and_expected_publisher():
    source = (PACKAGE / "desktop/windows_signing.ps1").read_text()
    assert '$Signature.Status -ne "Valid"' in source
    assert "$Signature.SignerCertificate.Subject -ne $ExpectedSubject" in source
    assert "$Signature.TimeStamperCertificate" in source
    assert "verify /pa /all /v" in source


def test_native_entitlements_cover_electron_helpers_and_python_separately(tmp_path):
    app = tmp_path / "SpectraSherpa.app"
    helper = app / "Contents/Frameworks/SpectraSherpa Helper (Renderer).app"
    helper_exe = helper / "Contents/MacOS/SpectraSherpa Helper (Renderer)"
    backend = app / "Contents/Resources/backend/SpectraSherpa"
    library = app / "Contents/Resources/backend/_internal/scipy/native.so"
    for target in (app, app / "Contents/MacOS/SpectraSherpa", helper, helper_exe):
        assert signing.target_entitlements(target, app, native_shell=True).name == "entitlements.electron.mac.plist"
    assert signing.target_entitlements(backend, app, native_shell=True).name == "entitlements.mac.plist"
    assert signing.target_entitlements(library, app, native_shell=True) is None
    assert signing.target_entitlements(app, app, native_shell=False).name == "entitlements.mac.plist"


def test_native_installer_preserves_original_inno_identity_and_profile_policy():
    source = (PACKAGE / "desktop/windows_installer.iss").read_text()
    assert "AppId=Spectra Sherpa" in source
    assert "PrivilegesRequired=lowest" in source
    assert "DefaultDirName={autopf}\\SpectraSherpa" in source
    assert 'Source: "electron\\out\\SpectraSherpa-win32-x64\\*"' in source
    assert "MB_DEFBUTTON2" in source
    assert "AppMutex=Global\\SpectraSherpaAppMutex" in source


@pytest.mark.parametrize("fails", [False, True])
def test_team_api_key_is_private_and_removed_after_credential_import(monkeypatch, tmp_path, fails):
    import base64

    secret = b"synthetic private key"
    monkeypatch.setenv("APPLE_NOTARY_KEY_P8_BASE64", base64.b64encode(secret).decode())
    monkeypatch.setenv("APPLE_NOTARY_KEY_ID", "SYNTHETIC")
    monkeypatch.setenv("APPLE_NOTARY_ISSUER_ID", "synthetic-issuer")

    def capture(*args):
        key = Path(args[args.index("--key") + 1])
        assert key.read_bytes() == secret
        import os

        if os.name != "nt":
            assert key.stat().st_mode & 0o777 == 0o600
        assert "--apple-id" not in args and "--password" not in args
        assert args[args.index("--issuer") + 1] == "synthetic-issuer"
        if fails:
            raise RuntimeError("synthetic credential refusal")
        return ""

    monkeypatch.setattr(signing, "run", capture)
    if fails:
        with pytest.raises(RuntimeError):
            signing.store_notary_credentials(tmp_path, tmp_path / "keychain")
    else:
        signing.store_notary_credentials(tmp_path, tmp_path / "keychain")
    assert not (tmp_path / "notary-key.p8").exists()
