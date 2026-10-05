#!/usr/bin/env python3
"""Provision the exact external OPUS/OMNIC qualification corpus.

These files are public test references in ``spectrochempy_data``, but that
repository does not grant redistribution rights for its ``irdata`` subtree.
Consequently this tool is deliberately separate from package/runtime code: it
downloads exact bytes directly from the named upstream commit into a caller-
owned qualification directory, verifies every retained SHA-256, and never
places them in a wheel, sdist, repository fixture directory, or user home.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SOURCE_REPOSITORY = "https://github.com/spectrochempy/spectrochempy_data"
SOURCE_COMMIT = "08bb9b0cbff8f4363c48b6bff7ccb743f8140e0a"
RAW_ROOT = f"https://raw.githubusercontent.com/spectrochempy/spectrochempy_data/{SOURCE_COMMIT}/testdata"
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_CORPUS_BYTES = 128 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class CorpusMember:
    locator: str
    sha256: str


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validated_locator(raw: object) -> str:
    if not isinstance(raw, str) or not raw:
        raise ValueError("external corpus locator must be a non-empty string")
    locator = PurePosixPath(raw)
    if locator.is_absolute() or ".." in locator.parts or locator.parts[0] != "irdata":
        raise ValueError(f"unsafe external corpus locator: {raw!r}")
    return locator.as_posix()


def _validated_digest(raw: object) -> str:
    if not isinstance(raw, str) or len(raw) != 64 or any(char not in "0123456789abcdef" for char in raw):
        raise ValueError("external corpus SHA-256 must be 64 lowercase hexadecimal characters")
    return raw


def corpus_members(repo_root: Path | None = None) -> tuple[CorpusMember, ...]:
    root = repo_root or _repository_root()
    evidence = root / "docs" / "evidence"
    opus = _read_json(evidence / "native-opus-reader-conformance.json")
    omnic = _read_json(evidence / "native-omnic-reader-conformance.json")
    expected_source = {
        "repository": SOURCE_REPOSITORY,
        "commit": SOURCE_COMMIT,
        "path_root": "testdata",
        "license": None,
        "use_boundary": (
            "Exact-hash files are retrieved from the named public upstream commit only into an ephemeral "
            "qualification directory. They are not redistributed, cached, bundled, or downloaded by "
            "SpectraSherpa tests or runtime code."
        ),
    }
    if opus.get("external_corpus_source") != expected_source or omnic.get("external_corpus_source") != expected_source:
        raise ValueError("OPUS and OMNIC conformance records must bind the provisioner's exact external source")

    members = [
        CorpusMember(
            locator=_validated_locator(row["external_locator"]),
            sha256=_validated_digest(row["sha256"]),
        )
        for row in opus["external_fixtures"]
    ]
    members.extend(
        CorpusMember(
            locator=_validated_locator(row["external_locator"]),
            sha256=_validated_digest(row["source_sha256"]),
        )
        for row in omnic["fixtures"]
    )
    if len(members) != 11 or len({member.locator for member in members}) != 11:
        raise ValueError("external vendor corpus must contain exactly 11 unique retained references")
    return tuple(members)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_bounded(source: Path, target: Path) -> int:
    size = source.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise ValueError(f"external corpus member exceeds {MAX_SOURCE_BYTES} bytes: {source}")
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer, length=CHUNK_BYTES)
    return size


def _download_bounded(member: CorpusMember, target: Path) -> int:
    encoded = urllib.parse.quote(member.locator, safe="/")
    request = urllib.request.Request(
        f"{RAW_ROOT}/{encoded}",
        headers={"User-Agent": "SpectraSherpa-qualified-external-corpus/1"},
    )
    total = 0
    with urllib.request.urlopen(request, timeout=90) as response, target.open("xb") as writer:  # noqa: S310
        declared = response.headers.get("Content-Length")
        if declared is not None and int(declared) > MAX_SOURCE_BYTES:
            raise ValueError(f"external corpus member exceeds {MAX_SOURCE_BYTES} bytes: {member.locator}")
        while True:
            chunk = response.read(CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                raise ValueError(f"external corpus member exceeds {MAX_SOURCE_BYTES} bytes: {member.locator}")
            writer.write(chunk)
    return total


def provision(
    destination: Path,
    *,
    source_directory: Path | None = None,
    check_only: bool = False,
) -> tuple[int, int]:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    for member in corpus_members():
        target = destination / member.locator
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and _sha256(target) == member.sha256:
            size = target.stat().st_size
        elif check_only:
            raise FileNotFoundError(f"missing or mismatched external corpus member: {member.locator}")
        else:
            target.unlink(missing_ok=True)
            temporary = target.with_name(f".{target.name}.{os.getpid()}.part")
            temporary.unlink(missing_ok=True)
            try:
                if source_directory is None:
                    size = _download_bounded(member, temporary)
                else:
                    size = _copy_bounded(source_directory / member.locator, temporary)
                if _sha256(temporary) != member.sha256:
                    raise ValueError(f"external corpus digest mismatch: {member.locator}")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        total += size
        count += 1
        if total > MAX_CORPUS_BYTES:
            raise ValueError(f"external corpus exceeds aggregate {MAX_CORPUS_BYTES}-byte ceiling")
    return count, total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--source-directory",
        type=Path,
        help="Copy from an explicitly supplied local corpus instead of the pinned upstream commit.",
    )
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        count, total = provision(
            args.destination,
            source_directory=args.source_directory,
            check_only=args.check_only,
        )
    except Exception as exc:
        print(f"external vendor corpus provisioning failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        f"Verified {count} exact external vendor references ({total} bytes) from "
        f"{SOURCE_REPOSITORY}@{SOURCE_COMMIT}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
