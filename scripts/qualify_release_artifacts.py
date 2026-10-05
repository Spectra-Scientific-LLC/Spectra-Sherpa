#!/usr/bin/env python3
"""Build-artifact authority and installed-distribution smoke for releases.

The build job creates one wheel and one sdist, writes a closed digest manifest,
and uploads that directory once. Clean qualification jobs and the OIDC-only
publication job receive that exact artifact by GitHub artifact ID. This module
uses only the standard library for manifest creation and verification so the
publication job never installs or executes a build dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tarfile
import tempfile
import zipfile
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = "spectra-sherpa-release-artifacts/1"
TAG_PATTERN = re.compile(r"spectra-sherpa-v(?P<version>[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9]+)?)\Z")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 50_000
NATIVE_SUFFIXES = (".dll", ".dylib", ".exe", ".pyd", ".so")
REQUIRED_NOTICES = (
    "THIRD_PARTY_LICENSES/brukeropus-MIT.txt",
    "THIRD_PARTY_LICENSES/spc-io-MIT.txt",
    "THIRD_PARTY_LICENSES/spc-parser-MIT.txt",
    "THIRD_PARTY_LICENSES/renishawWiRE-MIT.txt",
)
MANIFEST_KEYS = frozenset({"schema_version", "release_tag", "source_commit", "version", "artifacts"})
ARTIFACT_KEYS = frozenset({"filename", "kind", "sha256", "size_bytes"})
FRONTEND_PREFIX = "spectra_sherpa/static/"


class QualificationError(ValueError):
    """Raised when release artifacts are incomplete, unsafe, or unbound."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_identity(stream) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _frontend_relative(name: str, *, prefix: str) -> str | None:
    normalized = name.replace("\\", "/")
    if not normalized.startswith(prefix):
        if FRONTEND_PREFIX in normalized:
            raise QualificationError(f"frontend member is outside the exact installable path: {name!r}")
        return None
    relative = normalized[len(prefix) :]
    if not relative:
        return None
    if not _safe_member(relative):
        raise QualificationError(f"unsafe frontend member path: {name!r}")
    return relative


def _validate_frontend_inventory(inventory: dict[str, tuple[int, str]], *, label: str) -> None:
    if "index.html" not in inventory:
        raise QualificationError(f"{label} does not contain the generated frontend index.html")
    if not any(name.startswith("assets/") and name.endswith(".js") for name in inventory):
        raise QualificationError(f"{label} does not contain a generated frontend JavaScript asset")
    empty = sorted(name for name, (size, _digest) in inventory.items() if size <= 0)
    if empty:
        raise QualificationError(f"{label} contains empty frontend files: {empty!r}")


def _directory_frontend_inventory(root: Path) -> dict[str, tuple[int, str]]:
    if not root.is_dir() or root.is_symlink():
        raise QualificationError(f"frontend bundle directory is missing or unsafe: {root}")
    inventory: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise QualificationError(f"frontend bundle contains a symbolic link: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        inventory[relative] = (path.stat().st_size, _sha256(path))
    _validate_frontend_inventory(inventory, label=str(root))
    return inventory


def _archive_frontend_inventory(path: Path) -> dict[str, tuple[int, str]]:
    inventory: dict[str, tuple[int, str]] = {}
    if path.suffix == ".whl":
        prefix = FRONTEND_PREFIX
        try:
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    relative = _frontend_relative(member.filename, prefix=prefix)
                    if relative is None or member.is_dir():
                        continue
                    if relative in inventory:
                        raise QualificationError(f"{path.name} contains duplicate frontend member {relative!r}")
                    with archive.open(member) as stream:
                        inventory[relative] = _stream_identity(stream)
        except (OSError, zipfile.BadZipFile) as exc:
            raise QualificationError(f"wheel is unreadable: {path.name}") from exc
    elif path.name.endswith(".tar.gz"):
        distribution_root = path.name.removesuffix(".tar.gz")
        prefix = f"{distribution_root}/src/{FRONTEND_PREFIX}"
        try:
            with tarfile.open(path, "r:gz") as archive:
                for member in archive.getmembers():
                    relative = _frontend_relative(member.name, prefix=prefix)
                    if relative is None or not member.isfile():
                        continue
                    if relative in inventory:
                        raise QualificationError(f"{path.name} contains duplicate frontend member {relative!r}")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise QualificationError(f"{path.name} frontend member is unreadable: {member.name!r}")
                    with stream:
                        inventory[relative] = _stream_identity(stream)
        except (OSError, tarfile.TarError) as exc:
            raise QualificationError(f"sdist is unreadable: {path.name}") from exc
    else:
        raise QualificationError(f"unsupported distribution type for frontend verification: {path.name}")
    _validate_frontend_inventory(inventory, label=path.name)
    return inventory


def _compare_frontend_inventories(
    left: dict[str, tuple[int, str]],
    right: dict[str, tuple[int, str]],
    *,
    left_label: str,
    right_label: str,
) -> None:
    if left == right:
        return
    left_names = set(left)
    right_names = set(right)
    missing = sorted(left_names - right_names)
    extra = sorted(right_names - left_names)
    changed = sorted(name for name in left_names & right_names if left[name] != right[name])
    raise QualificationError(
        f"frontend bundles differ ({left_label} != {right_label}); "
        f"missing={missing!r}, extra={extra!r}, changed={changed!r}"
    )


def compare_frontend_directories(*, left: Path, right: Path) -> None:
    _compare_frontend_inventories(
        _directory_frontend_inventory(left),
        _directory_frontend_inventory(right),
        left_label=str(left),
        right_label=str(right),
    )


def verify_frontend_archive(*, artifact: Path, bundle: Path) -> None:
    _compare_frontend_inventories(
        _directory_frontend_inventory(bundle),
        _archive_frontend_inventory(artifact),
        left_label=str(bundle),
        right_label=artifact.name,
    )


def verify_frontend_distributions(*, dist: Path, bundle: Path | None = None) -> None:
    paths = sorted(path for path in dist.iterdir() if path.is_file()) if dist.is_dir() else []
    wheels = [path for path in paths if path.suffix == ".whl"]
    sdists = [path for path in paths if path.name.endswith(".tar.gz")]
    if len(paths) != 2 or len(wheels) != 1 or len(sdists) != 1:
        raise QualificationError("frontend qualification requires exactly one wheel and one .tar.gz sdist")
    wheel_inventory = _archive_frontend_inventory(wheels[0])
    sdist_inventory = _archive_frontend_inventory(sdists[0])
    _compare_frontend_inventories(
        wheel_inventory,
        sdist_inventory,
        left_label=wheels[0].name,
        right_label=sdists[0].name,
    )
    if bundle is not None:
        _compare_frontend_inventories(
            _directory_frontend_inventory(bundle),
            wheel_inventory,
            left_label=str(bundle),
            right_label=wheels[0].name,
        )


def _safe_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    return bool(normalized) and not normalized.startswith("/") and ".." not in pure.parts


def _validate_member_name(name: str) -> None:
    if not _safe_member(name):
        raise QualificationError(f"unsafe archive member path: {name!r}")
    if name.lower().endswith(NATIVE_SUFFIXES):
        raise QualificationError(f"unapproved native executable in universal distribution: {name!r}")


def _validate_wheel(path: Path) -> list[str]:
    names: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise QualificationError(f"wheel exceeds member limit: {len(members)}")
            if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
                raise QualificationError("wheel exceeds the uncompressed size limit")
            for member in members:
                _validate_member_name(member.filename)
                if member.filename in names:
                    raise QualificationError(f"wheel contains a duplicate member: {member.filename!r}")
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise QualificationError(f"wheel contains a symbolic link: {member.filename!r}")
                names.append(member.filename)
    except (OSError, zipfile.BadZipFile) as exc:
        raise QualificationError(f"wheel is unreadable: {path.name}") from exc
    return names


def _validate_sdist(path: Path) -> list[str]:
    names: list[str] = []
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise QualificationError(f"sdist exceeds member limit: {len(members)}")
            if sum(member.size for member in members if member.isfile()) > MAX_UNCOMPRESSED_BYTES:
                raise QualificationError("sdist exceeds the uncompressed size limit")
            for member in members:
                _validate_member_name(member.name)
                if member.name in names:
                    raise QualificationError(f"sdist contains a duplicate member: {member.name!r}")
                if not (member.isfile() or member.isdir()):
                    raise QualificationError(f"sdist contains a special member: {member.name!r}")
                names.append(member.name)
    except (OSError, tarfile.TarError) as exc:
        raise QualificationError(f"sdist is unreadable: {path.name}") from exc
    return names


def _artifacts(dist: Path, version: str) -> list[tuple[Path, str]]:
    if not dist.is_dir() or dist.is_symlink():
        raise QualificationError(f"distribution directory is missing or unsafe: {dist}")
    paths = sorted(dist.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise QualificationError("distribution set may contain only two regular, non-linked files")
    wheel = [path for path in paths if path.suffix == ".whl"]
    sdist = [path for path in paths if path.name.endswith(".tar.gz")]
    if len(paths) != 2 or len(wheel) != 1 or len(sdist) != 1:
        raise QualificationError("distribution set must contain exactly one wheel and one .tar.gz sdist")
    expected_wheel = f"spectra_sherpa-{version}-py3-none-any.whl"
    expected_sdist = f"spectra_sherpa-{version}.tar.gz"
    if wheel[0].name != expected_wheel or sdist[0].name != expected_sdist:
        raise QualificationError(
            f"distribution filenames do not match release version: expected {expected_wheel!r} and {expected_sdist!r}"
        )
    for path in paths:
        size = path.stat().st_size
        if size <= 0 or size > MAX_ARTIFACT_BYTES:
            raise QualificationError(f"distribution size is outside the admitted range: {path.name} ({size})")
    wheel_names = _validate_wheel(wheel[0])
    sdist_names = _validate_sdist(sdist[0])
    for suffix in REQUIRED_NOTICES:
        if sum(name.endswith(suffix) for name in wheel_names) != 1:
            raise QualificationError(f"wheel does not contain exactly one required notice: {suffix}")
        if sum(name.endswith(suffix) for name in sdist_names) != 1:
            raise QualificationError(f"sdist does not contain exactly one required notice: {suffix}")
    verify_frontend_distributions(dist=dist)
    return [(wheel[0], "wheel"), (sdist[0], "sdist")]


def create_manifest(*, dist: Path, output: Path, release_tag: str, source_commit: str) -> dict[str, object]:
    match = TAG_PATTERN.fullmatch(release_tag)
    if match is None:
        raise QualificationError("release tag does not use the exact spectra-sherpa-vX.Y.Z form")
    if COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise QualificationError("source commit must be a lowercase full Git SHA")
    version = match.group("version")
    artifacts = _artifacts(dist, version)
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "release_tag": release_tag,
        "source_commit": source_commit,
        "version": version,
        "artifacts": [
            {
                "filename": path.name,
                "kind": kind,
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
            for path, kind in artifacts
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def load_manifest(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 64 * 1024:
        raise QualificationError("artifact manifest is missing, linked, or oversized")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError("artifact manifest is unreadable") from exc
    if not isinstance(value, dict) or set(value) != MANIFEST_KEYS:
        raise QualificationError("artifact manifest does not use the closed current schema")
    return value


def verify_manifest(*, dist: Path, manifest_path: Path) -> dict[str, object]:
    document = load_manifest(manifest_path)
    if document["schema_version"] != SCHEMA_VERSION:
        raise QualificationError("artifact manifest schema version is unsupported")
    release_tag = document["release_tag"]
    source_commit = document["source_commit"]
    version = document["version"]
    if not isinstance(release_tag, str) or not isinstance(version, str):
        raise QualificationError("artifact manifest tag and version must be strings")
    match = TAG_PATTERN.fullmatch(release_tag)
    if match is None or match.group("version") != version:
        raise QualificationError("artifact manifest tag and version disagree")
    if not isinstance(source_commit, str) or COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise QualificationError("artifact manifest source commit is invalid")
    actual = _artifacts(dist, version)
    records = document["artifacts"]
    if not isinstance(records, list) or len(records) != 2:
        raise QualificationError("artifact manifest must bind exactly two distributions")
    by_name: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != ARTIFACT_KEYS:
            raise QualificationError("artifact record does not use the closed current schema")
        filename = record["filename"]
        if not isinstance(filename, str) or filename in by_name:
            raise QualificationError("artifact filenames must be unique strings")
        by_name[filename] = record
    for path, kind in actual:
        record = by_name.get(path.name)
        if record is None:
            raise QualificationError(f"artifact is absent from manifest: {path.name}")
        if record["kind"] != kind or record["size_bytes"] != path.stat().st_size or record["sha256"] != _sha256(path):
            raise QualificationError(f"artifact identity differs from manifest: {path.name}")
    return document


def select_artifact(*, dist: Path, manifest_path: Path, kind: str) -> Path:
    document = verify_manifest(dist=dist, manifest_path=manifest_path)
    matches = [record for record in document["artifacts"] if record["kind"] == kind]  # type: ignore[index]
    if len(matches) != 1:
        raise QualificationError(f"manifest does not contain exactly one {kind}")
    return (dist / str(matches[0]["filename"])).resolve()


def installed_smoke(expected_version: str) -> None:
    try:
        observed_version = distribution_version("spectra-sherpa")
    except PackageNotFoundError as exc:
        raise QualificationError("spectra-sherpa is not installed") from exc
    if observed_version != expected_version:
        raise QualificationError(f"installed version {observed_version!r} != expected {expected_version!r}")

    with tempfile.TemporaryDirectory(prefix="spectra-sherpa-artifact-smoke-") as temporary:
        root = Path(temporary)
        os.environ["DATA_DIR"] = str(root / "data")
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{root / 'smoke.db'}"
        csv_path = root / "smoke.csv"
        csv_path.write_text("wavenumber,absorbance\n4000,0.10\n3000,0.20\n2000,0.30\n", encoding="utf-8")

        from spectra_sherpa.io import ingest, select_asset

        result = ingest(csv_path)
        asset = select_asset(result)
        if result.format_id != "csv" or asset.dataset.shape != (1, 3):
            raise QualificationError("installed native CSV reader returned an unexpected scientific shape")

        from starlette.testclient import TestClient

        from spectra_sherpa.app.main import create_app

        app = create_app(include_server_routers=False, include_actor_compat_route=False)
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            health = client.get("/api/v1/health")
            version_response = client.get("/api/v1/version")
            frontend = client.get("/")
        if health.status_code != 200 or health.json() != {"status": "ok"}:
            raise QualificationError(f"installed Workbench health check failed: HTTP {health.status_code}")
        if version_response.status_code != 200 or version_response.json() != {"backend_version": expected_version}:
            raise QualificationError(f"installed version endpoint failed: HTTP {version_response.status_code}")
        if frontend.status_code != 200 or "text/html" not in frontend.headers.get("content-type", ""):
            raise QualificationError("installed Workbench frontend is unavailable")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-manifest")
    create.add_argument("--dist", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--release-tag", required=True)
    create.add_argument("--source-commit", required=True)

    verify = subparsers.add_parser("verify-manifest")
    verify.add_argument("--dist", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)

    select = subparsers.add_parser("select")
    select.add_argument("--dist", type=Path, required=True)
    select.add_argument("--manifest", type=Path, required=True)
    select.add_argument("--kind", choices=("wheel", "sdist"), required=True)

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--expected-version", required=True)

    compare_frontends = subparsers.add_parser("compare-frontends")
    compare_frontends.add_argument("--left", type=Path, required=True)
    compare_frontends.add_argument("--right", type=Path, required=True)

    verify_frontends = subparsers.add_parser("verify-frontends")
    verify_frontends.add_argument("--dist", type=Path, required=True)
    verify_frontends.add_argument("--bundle", type=Path)

    verify_archive = subparsers.add_parser("verify-frontend-archive")
    verify_archive.add_argument("--artifact", type=Path, required=True)
    verify_archive.add_argument("--bundle", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "create-manifest":
            document = create_manifest(
                dist=args.dist,
                output=args.output,
                release_tag=args.release_tag,
                source_commit=args.source_commit,
            )
            print(json.dumps(document, indent=2, sort_keys=True))
        elif args.command == "verify-manifest":
            document = verify_manifest(dist=args.dist, manifest_path=args.manifest)
            print(
                f"Verified {document['release_tag']} artifacts from {document['source_commit']} "
                f"({len(document['artifacts'])} files)."
            )
        elif args.command == "select":
            print(select_artifact(dist=args.dist, manifest_path=args.manifest, kind=args.kind))
        elif args.command == "smoke":
            installed_smoke(args.expected_version)
            print(f"Installed spectra-sherpa {args.expected_version} passed native-ingestion and Workbench smoke.")
        elif args.command == "compare-frontends":
            compare_frontend_directories(left=args.left, right=args.right)
            print("Frontend regeneration is byte-for-byte deterministic.")
        elif args.command == "verify-frontends":
            verify_frontend_distributions(dist=args.dist, bundle=args.bundle)
            print("Wheel and sdist contain the same qualified generated frontend.")
        else:
            verify_frontend_archive(artifact=args.artifact, bundle=args.bundle)
            print(f"{args.artifact.name} contains the exact qualified generated frontend.")
    except QualificationError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
