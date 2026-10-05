#!/usr/bin/env python3
"""Bind release assets to exact version/source/platform and refuse partial sets."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
from pathlib import Path

TARGETS = {
    "ubuntu-x86_64": ("Linux", "x86_64", "desktop/dist/SpectraSherpa.AppImage", ".AppImage"),
    "macos-arm64": ("Darwin", "arm64", "desktop/dist/SpectraSherpa.dmg", ".dmg"),
    "windows-x86_64": ("Windows", "AMD64", "desktop/Output/SpectraSherpa_Setup.exe", ".exe"),
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(tag: str, commit: str) -> str:
    if not re.fullmatch(r"spectra-sherpa-v[0-9]+\.[0-9]+\.[0-9]+(?:[a-zA-Z0-9.-]+)?", tag):
        raise ValueError("Require an explicit spectra-sherpa version tag")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Require a full source commit")
    return tag.removeprefix("spectra-sherpa-v")


def validate_dependency_provenance(value: dict) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Missing scoped dependency provenance")
    build = value.get("build_environment", {})
    scientific = value.get("scientific_runtime", {})
    if not isinstance(build, dict) or not isinstance(scientific, dict):
        raise ValueError("Invalid provenance sections")
    if build.get("scope") != "resolved_build_environment_not_bundle_inventory":
        raise ValueError("Build environment scope is not disclosed")
    if scientific.get("scope") != "canonical_profile_runtime_attestation":
        raise ValueError("Missing scientific runtime attestation")
    if not scientific.get("profile_id") or not re.fullmatch(r"[a-f0-9]{64}", scientific.get("profile_digest", "")):
        raise ValueError("Missing scientific profile identity")
    installed = build.get("distributions")
    observed = scientific.get("distributions")
    if not isinstance(installed, dict) or not installed or not isinstance(observed, dict) or not observed:
        raise ValueError("Empty dependency provenance")
    for name, version in installed.items():
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            raise ValueError("Invalid dependency identity")
    for name, version in observed.items():
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            raise ValueError("Invalid scientific dependency identity")
        if installed.get(re.sub(r"[-_.]+", "-", name).lower()) != version:
            raise ValueError("Scientific and build dependency evidence differ")


def prepare(target: str, tag: str, commit: str, output: Path) -> Path:
    import spectra_sherpa

    version = identity(tag, commit)
    shell = json.loads((Path(__file__).parent / "electron/package.json").read_text(encoding="utf-8"))
    if version != shell["version"]:
        raise ValueError("Tag version differs from native shell version")
    if version != spectra_sherpa.__version__:
        raise ValueError("Tag version differs from bundled source version")
    system, architecture, source, extension = TARGETS[target]
    if (platform.system(), platform.machine()) != (system, architecture):
        raise ValueError("Runner architecture differs from artifact target")
    path = Path(source)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Missing native verified artifact")
    provenance_path = Path(
        {
            "macos-arm64": "desktop/electron/out/SpectraSherpa-darwin-arm64/SpectraSherpa.app/Contents/Resources/backend/_internal/provenance.json",
            "windows-x86_64": "desktop/electron/out/SpectraSherpa-win32-x64/resources/backend/_internal/provenance.json",
            "ubuntu-x86_64": "desktop/electron/out/SpectraSherpa-linux-x64/resources/backend/_internal/provenance.json",
        }[target]
    )
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance.get("build_commit") != commit or provenance.get("version") != version:
        raise ValueError("Bundled provenance differs from the release identity")
    dependency_provenance = provenance.get("dependency_provenance")
    validate_dependency_provenance(dependency_provenance)
    output.mkdir(parents=True, exist_ok=True)
    asset = output / f"SpectraSherpa-{version}-{target}{extension}"
    shutil.copyfile(path, asset)
    manifest = {
        "schema_version": 2,
        "shell": "electron",
        "electron_version": shell["devDependencies"]["electron"],
        "python_version": platform.python_version(),
        "dependency_provenance": dependency_provenance,
        "target": target,
        "version": version,
        "tag": tag,
        "source_commit": commit,
        "asset": asset.name,
        "sha256": digest(asset),
        "size": asset.stat().st_size,
    }
    receipt = output / f"{target}.manifest.json"
    receipt.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return receipt


def validate(root: Path, tag: str, commit: str) -> list[Path]:
    version = identity(tag, commit)
    shell = json.loads((Path(__file__).parent / "electron/package.json").read_text(encoding="utf-8"))
    receipts = list(root.rglob("*.manifest.json"))
    records = [json.loads(path.read_text(encoding="utf-8")) for path in receipts]
    if len(records) != len(TARGETS) or {r.get("target") for r in records} != set(TARGETS):
        raise ValueError("Incomplete or duplicate desktop target set")
    assets = []
    for receipt, record in zip(receipts, records):
        if any(
            record.get(k) != v
            for k, v in {
                "schema_version": 2,
                "shell": "electron",
                "tag": tag,
                "version": version,
                "source_commit": commit,
            }.items()
        ):
            raise ValueError("Mixed release identity")
        if record.get("electron_version") != shell["devDependencies"]["electron"]:
            raise ValueError("Unexpected bundled Electron version")
        if record.get("python_version") != "3.11.9":
            raise ValueError("Unexpected bundled Python version")
        validate_dependency_provenance(record.get("dependency_provenance"))
        extension = TARGETS[record["target"]][3]
        expected = f"SpectraSherpa-{version}-{record['target']}{extension}"
        if record.get("asset") != expected:
            raise ValueError("Unexpected asset name")
        asset = receipt.parent / expected
        if asset.is_symlink() or not asset.is_file() or asset.stat().st_size != record.get("size"):
            raise ValueError("Missing or changed release asset")
        if digest(asset) != record.get("sha256"):
            raise ValueError("Release checksum mismatch")
        assets.append(asset)
    allowed = {p.resolve() for p in [*receipts, *assets]}
    if any(p.resolve() not in allowed for p in root.rglob("*") if p.is_file()):
        raise ValueError("Unexpected files in release artifact set")
    checksums = root / "SHA256SUMS"
    checksums.write_text("".join(f"{digest(p)}  {p.name}\n" for p in sorted(assets)), encoding="utf-8")
    combined = root / "desktop-manifest.json"
    combined.write_text(json.dumps(sorted(records, key=lambda r: r["target"]), indent=2) + "\n", encoding="utf-8")
    return [*assets, checksums, combined]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "validate"])
    parser.add_argument("--target", choices=TARGETS)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        if not args.target:
            parser.error("prepare requires --target")
        prepare(args.target, args.tag, args.commit, args.directory)
    else:
        for asset in validate(args.directory, args.tag, args.commit):
            print(asset)


if __name__ == "__main__":
    main()
