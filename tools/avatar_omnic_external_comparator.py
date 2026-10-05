#!/usr/bin/env python3
"""Run the pinned external OMNIC reader without importing SpectraSherpa."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "spectrasherpa-avatar-external-omnic-comparison/1"
MANIFEST_SCHEMA = "spectrasherpa-avatar-essential-oils-public-manifest/2"
DATASET_ID = "avatar-essential-oils/1"
CONVERTER = {
    "project": "spectrochempy-omnic",
    "version": "0.2.1",
    "commit": "2eb6b7d3964451d35eeb0c185cb99a0cc147c7cd",
    "upstream_url": "https://github.com/spectrochempy/spectrochempy-omnic",
    "license": "CeCILL-B",
    "source_tree_sha256": "8fbb46eebf22b81ea9395894cfdb4067a6bac0790a3a2d9e7980862b0c98cf4e",
    "license_sha256": "fb5b89c84879627a3149f3c94f3620da9fd8799419e6f8ffd8179066af1efb6a",
}


class ComparatorError(ValueError):
    """The external comparison did not satisfy its closed authority."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _array_sha256(value: Any) -> str:
    array = np.ascontiguousarray(np.asarray(value, dtype="<f8"))
    return _sha256_bytes(array.tobytes(order="C"))


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_tree_sha256(repo: Path) -> str:
    package = repo / "src" / "spectrochempy_omnic"
    files = sorted([repo / "pyproject.toml", repo / "LICENSE", *package.rglob("*.py")])
    if len(files) != 9 or not all(path.is_file() for path in files):
        raise ComparatorError("external converter source-tree file set is not the qualified nine-file set")
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(repo)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _verify_converter_repo(repo: Path) -> None:
    repo = repo.resolve()
    if _git(repo, "rev-parse", "HEAD") != CONVERTER["commit"]:
        raise ComparatorError("external converter repository is not at the qualified commit")
    if _git(repo, "describe", "--tags", "--exact-match", "HEAD") != CONVERTER["version"]:
        raise ComparatorError("external converter commit is not at the qualified release tag")
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise ComparatorError("external converter tracked source tree is dirty")
    if _source_tree_sha256(repo) != CONVERTER["source_tree_sha256"]:
        raise ComparatorError("external converter source-tree digest changed")
    if _sha256_bytes((repo / "LICENSE").read_bytes()) != CONVERTER["license_sha256"]:
        raise ComparatorError("external converter license digest changed")


def _disable_network() -> None:
    def denied(*_args: Any, **_kwargs: Any) -> Any:
        raise ComparatorError("network access is forbidden during external conversion")

    class DeniedSocket(socket.socket):
        def connect(self, *_args: Any, **_kwargs: Any) -> Any:
            return denied()

        def connect_ex(self, *_args: Any, **_kwargs: Any) -> Any:
            return denied()

    socket.socket = DeniedSocket  # type: ignore[misc]
    socket.getaddrinfo = denied  # type: ignore[assignment]


def build_external_report(
    manifest_path: Path,
    curated_dir: Path,
    converter_repo: Path,
) -> dict[str, Any]:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema_version") != MANIFEST_SCHEMA or manifest.get("dataset_id") != DATASET_ID:
        raise ComparatorError("source manifest identity is not recognized")
    manifest_rows = manifest.get("files")
    if not isinstance(manifest_rows, list) or len(manifest_rows) != 33:
        raise ComparatorError("source manifest must contain exactly 33 rows")

    _verify_converter_repo(converter_repo)
    _disable_network()
    source_root = (converter_repo.resolve() / "src").resolve()
    sys.path.insert(0, str(source_root))
    import spectrochempy_omnic
    from spectrochempy_omnic import OMNICReader  # type: ignore[import-not-found]

    if not Path(spectrochempy_omnic.__file__).resolve().is_relative_to(source_root):
        raise ComparatorError("external reader did not import from the qualified source tree")
    if "spectra_sherpa" in sys.modules:
        raise ComparatorError("external comparison process imported SpectraSherpa")

    expected_names = {str(row["distribution_filename"]) for row in manifest_rows}
    actual_names = {path.name for path in curated_dir.iterdir() if path.is_file()}
    if actual_names != expected_names:
        raise ComparatorError("curated directory is not the exact manifest file set")

    output_rows: list[dict[str, Any]] = []
    for row in manifest_rows:
        filename = str(row["distribution_filename"])
        if Path(filename).name != filename or Path(filename).suffix.lower() != ".spa":
            raise ComparatorError("manifest contains an unsafe or non-SPA distribution filename")
        path = curated_dir / filename
        source_bytes = path.read_bytes()
        if _sha256_bytes(source_bytes) != row.get("curated_sha256"):
            raise ComparatorError(f"{filename}: source bytes do not match the manifest")
        result = OMNICReader(path)
        values = np.asarray(result.data, dtype=np.float64)
        axis = np.asarray(result.x, dtype=np.float64)
        if values.shape != (1, 1868) or axis.shape != (1868,):
            raise ComparatorError(f"{filename}: external reader returned an unexpected shape")
        if not np.all(np.isfinite(values)) or not np.all(np.isfinite(axis)):
            raise ComparatorError(f"{filename}: external reader returned non-finite science")
        if not np.all(np.diff(axis) < 0):
            raise ComparatorError(f"{filename}: external reader did not preserve descending source order")
        if str(result.x_units) != "cm^-1" or str(result.units) != "absorbance":
            raise ComparatorError(f"{filename}: external reader returned unexpected scientific units")
        output_rows.append(
            {
                "sample_id": row["sample_id"],
                "spa_sha256": row["curated_sha256"],
                "shape": [1, 1868],
                "point_count": 1868,
                "axis_order": "strictly_descending",
                "axis_units": "cm^-1",
                "value_units": "absorbance",
                "external_values_sha256": _array_sha256(values),
                "external_axis_sha256": _array_sha256(axis),
            }
        )

    return {
        "schema_version": SCHEMA,
        "converter": CONVERTER,
        "source_manifest_sha256": _sha256_bytes(manifest_bytes),
        "execution": {
            "network_access": "python_socket_dns_blocked",
            "spectrasherpa_imported": False,
            "comparison_scope": "all_33_complete_axis_and_ordinate_arrays",
        },
        "files": output_rows,
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--curated-dir", type=Path, required=True)
    parser.add_argument("--converter-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = build_external_report(
        arguments.manifest.resolve(),
        arguments.curated_dir.resolve(),
        arguments.converter_repo.resolve(),
    )
    _write_json(arguments.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
