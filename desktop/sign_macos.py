#!/usr/bin/env python3
"""Sign and notarize a native macOS app and its distributable disk image.

Credentials only enter an ephemeral keychain; never persist them in artifacts.
Both the copied app and its outer DMG retain tickets for offline verification.
Run from the package root on a native macOS release runner.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

MACHO_MAGIC = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


def run(*args: str) -> str:
    # Never surface argv in exceptions: security/notarytool receive credentials.
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed (exit {result.returncode}); inspect signing configuration")
    return result.stdout


def signing_targets(app: Path) -> list[Path]:
    """Sign physical inner code first, then enclosing framework/bundle seals."""
    targets = []
    for path in app.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            with path.open("rb") as stream:
                if stream.read(4) in MACHO_MAGIC:
                    targets.append(path)
        elif path.is_dir() and path.suffix in {".framework", ".bundle", ".app", ".xpc"}:
            targets.append(path)
    return sorted(targets, key=lambda p: (-len(p.parts), str(p)))


def notarize(path: Path, keychain: Path, receipt: Path) -> None:
    raw = run(
        "xcrun",
        "notarytool",
        "submit",
        str(path),
        "--keychain-profile",
        "desktop-release",
        "--keychain",
        str(keychain),
        "--wait",
        "--timeout",
        "20m",
        "--output-format",
        "json",
    )
    response = json.loads(raw)
    # Exit status alone is not proof of acceptance; retain the provider receipt.
    receipt.write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")
    if response.get("status") != "Accepted":
        raise RuntimeError("Apple notarization was not Accepted; inspect the retained receipt")


def store_notary_credentials(root: Path, keychain: Path) -> None:
    """Use a team API key only inside the private, temporary signing directory."""
    key = root / "notary-key.p8"
    key.write_bytes(base64.b64decode(os.environ["APPLE_NOTARY_KEY_P8_BASE64"], validate=True))
    key.chmod(0o600)
    try:
        run(
            "xcrun",
            "notarytool",
            "store-credentials",
            "desktop-release",
            "--keychain",
            str(keychain),
            "--key",
            str(key),
            "--key-id",
            os.environ["APPLE_NOTARY_KEY_ID"],
            "--issuer",
            os.environ["APPLE_NOTARY_ISSUER_ID"],
        )
    finally:
        key.unlink(missing_ok=True)


def target_entitlements(target: Path, app: Path, *, native_shell: bool) -> Path | None:
    """Apply process permissions to executables/bundles, never every dylib."""
    python_permissions = Path("desktop/entitlements.mac.plist").resolve()
    if native_shell:
        if target == app / "Contents/Resources/backend/SpectraSherpa":
            return python_permissions
        if target.suffix == ".app" or target.parent.name == "MacOS":
            return Path("desktop/entitlements.electron.mac.plist").resolve()
        return None
    if target == app or target.parent == app / "Contents/MacOS":
        return python_permissions
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-shell", action="store_true", help="Sign the packaged Electron candidate")
    options = parser.parse_args()
    required = (
        "APPLE_CERTIFICATE_P12_BASE64",
        "APPLE_CERTIFICATE_PASSWORD",
        "APPLE_NOTARY_KEY_P8_BASE64",
        "APPLE_NOTARY_KEY_ID",
        "APPLE_NOTARY_ISSUER_ID",
        "APPLE_TEAM_ID",
    )
    for name in required:
        if not os.environ.get(name):
            raise RuntimeError(f"Missing signing configuration: {name}")
    team = os.environ["APPLE_TEAM_ID"]
    if not re.fullmatch(r"[A-Z0-9]{10}", team):
        raise RuntimeError("Invalid Apple team identifier")
    app = Path(
        "desktop/electron/out/SpectraSherpa-darwin-arm64/SpectraSherpa.app"
        if options.native_shell
        else "desktop/dist/SpectraSherpa.app"
    ).resolve()
    if not (app / "Contents/MacOS/SpectraSherpa").is_file():
        raise RuntimeError("Missing native application bundle")
    if options.native_shell:
        run("node", "desktop/electron/harden.cjs", str(app), "--verify")
    evidence = Path("desktop/signing-evidence")
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="desktop-sign-", dir=os.environ.get("RUNNER_TEMP")) as temp:
        root = Path(temp)
        keychain, certificate = root / "signing.keychain-db", root / "certificate.p12"
        password = secrets.token_urlsafe(32)
        certificate.write_bytes(base64.b64decode(os.environ["APPLE_CERTIFICATE_P12_BASE64"], validate=True))
        certificate.chmod(0o600)
        try:
            run("security", "create-keychain", "-p", password, str(keychain))
            run("security", "set-keychain-settings", "-lut", "3600", str(keychain))
            run("security", "unlock-keychain", "-p", password, str(keychain))
            run(
                "security",
                "import",
                str(certificate),
                "-P",
                os.environ["APPLE_CERTIFICATE_PASSWORD"],
                "-k",
                str(keychain),
                "-T",
                "/usr/bin/codesign",
                "-T",
                "/usr/bin/security",
            )
            run(
                "security",
                "set-key-partition-list",
                "-S",
                "apple-tool:,apple:,codesign:",
                "-s",
                "-k",
                password,
                str(keychain),
            )
            identities = run("security", "find-identity", "-v", "-p", "codesigning", str(keychain))
            matches = re.findall(
                r'\b([0-9A-Fa-f]{40}) "Developer ID Application: [^"\n]+ \(' + team + r'\)"', identities
            )
            if len(matches) != 1:
                raise RuntimeError("Require exactly one valid Developer ID Application identity for the expected team")
            identity = matches[0]
            provenance = app / (
                "Contents/Resources/backend/_internal/provenance.json"
                if options.native_shell
                else "Contents/Frameworks/provenance.json"
            )
            data = json.loads(provenance.read_text(encoding="utf-8"))
            data["signing_identity"] = identity
            provenance.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            for target in [*signing_targets(app), app]:
                args = [
                    "codesign",
                    "--force",
                    "--sign",
                    identity,
                    "--keychain",
                    str(keychain),
                    "--options",
                    "runtime",
                    "--timestamp",
                ]
                permissions = target_entitlements(target, app, native_shell=options.native_shell)
                if permissions is not None:
                    args += ["--entitlements", str(permissions)]
                run(*args, str(target))
            run("codesign", "--verify", "--deep", "--strict", str(app))
            store_notary_credentials(root, keychain)
            archive = root / "application.zip"
            run("ditto", "-c", "-k", "--keepParent", str(app), str(archive))
            notarize(archive, keychain, evidence / "macos-app-notarization.json")
            run("xcrun", "stapler", "staple", str(app))
            run("xcrun", "stapler", "validate", str(app))
            run("spctl", "--assess", "--type", "execute", "--verbose=2", str(app))
            staging = root / "image"
            staging.mkdir()
            shutil.copytree(app, staging / app.name, symlinks=True)
            (staging / "Applications").symlink_to("/Applications", target_is_directory=True)
            dmg = Path("desktop/dist/SpectraSherpa.dmg").resolve()
            run(
                "hdiutil",
                "create",
                "-volname",
                "SpectraSherpa",
                "-srcfolder",
                str(staging),
                "-ov",
                "-format",
                "UDZO",
                str(dmg),
            )
            run("codesign", "--sign", identity, "--keychain", str(keychain), "--timestamp", str(dmg))
            notarize(dmg, keychain, evidence / "macos-dmg-notarization.json")
            run("xcrun", "stapler", "staple", str(dmg))
            run("xcrun", "stapler", "validate", str(dmg))
            run("codesign", "--verify", "--strict", str(dmg))
            run("spctl", "--assess", "--type", "open", "--context", "context:primary-signature", str(dmg))
        finally:
            # The private key is never added to the user's search list. Always
            # delete its temporary keychain, including failed notarizations.
            if keychain.exists():
                run("security", "delete-keychain", str(keychain))


if __name__ == "__main__":
    main()
