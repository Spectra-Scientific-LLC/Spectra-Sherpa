#!/usr/bin/env python3
"""Qualify the private IASIM16 Test 1 DSO through native masked PARAFAC.

The input archive remains in caller-controlled custody. The command verifies
its registered size and SHA-256, extracts only the registered Test_1.mat member
to a private temporary directory, and emits a data-free JSON receipt.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.reference_artifacts import (
    load_reference_artifact_registry,
    reference_artifact_registry_digest,
)
from spectra_sherpa.app.services.dag.nodes.modeling.parafac_node import PARAFACNode
from spectra_sherpa.app.services.dag.stable_execution_contract import execution_contract_digest
from spectra_sherpa.io import ingest

SCHEMA_VERSION = "spectrasherpa-iasim16-parafac-private-qualification/1"
ARTIFACT_ID = "eigenvector-iasim16-test1-archive-v1"
PROJECTION_ID = "public-iasim16-test1-v1"
MEMBER_NAME = "Test_1.mat"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
PARAMETERS: dict[str, object] = {
    "n_components": 3,
    "max_iter": 200,
    "tol": 0.0001,
    "ridge": 0.000000000001,
}


class QualificationError(ValueError):
    """One IASIM16 private qualification invariant failed."""


def _open_regular_nofollow(path: Path, *, expected_size: int) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise QualificationError("IASIM16 archive is unavailable as a regular non-link file") from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise QualificationError("IASIM16 archive is not a regular file")
        if observed.st_size != expected_size or observed.st_size > MAX_ARCHIVE_BYTES:
            raise QualificationError("IASIM16 archive size differs from the registered authority")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _stream_digest(path: Path, *, expected_size: int) -> str:
    descriptor = _open_regular_nofollow(path, expected_size=expected_size)
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb", closefd=True) as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_registered_member(
    archive_path: Path,
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> None:
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            member = archive.getinfo(MEMBER_NAME)
            mode = (member.external_attr >> 16) & 0o170000
            if member.is_dir() or member.flag_bits & 0x1 or mode == stat.S_IFLNK:
                raise QualificationError("registered IASIM16 member is not a plain unencrypted file")
            if member.file_size != expected_size:
                raise QualificationError("registered IASIM16 member size differs from authority")
            digest = hashlib.sha256()
            observed = 0
            with archive.open(member, "r") as source, destination.open("xb") as target:
                for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
                    observed += len(chunk)
                    if observed > expected_size:
                        raise QualificationError("registered IASIM16 member exceeded its declared size")
                    digest.update(chunk)
                    target.write(chunk)
            if observed != expected_size or digest.hexdigest() != expected_sha256:
                raise QualificationError("registered IASIM16 member bytes differ from authority")
    except (KeyError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise QualificationError("IASIM16 archive does not expose the registered Test_1.mat member") from exc


def _template_references(root: Path) -> list[str]:
    templates = root / "src" / "spectra_sherpa" / "data" / "templates"
    return sorted(
        path.relative_to(root).as_posix()
        for path in templates.glob("*.yaml")
        if "model.parafac" in path.read_text(encoding="utf-8")
    )


def qualify(archive_path: Path) -> dict[str, Any]:
    registry = load_reference_artifact_registry()
    artifact = registry.artifact(ARTIFACT_ID).as_dict()
    projection = registry.projection(PROJECTION_ID).as_dict()
    if _stream_digest(archive_path, expected_size=artifact["expected_size_bytes"]) != artifact["sha256"]:
        raise QualificationError("IASIM16 archive SHA-256 differs from the registered authority")
    members = [value for value in artifact["members"] if value["path"] == MEMBER_NAME]
    if len(members) != 1 or projection["member_path"] != MEMBER_NAME:
        raise QualificationError("IASIM16 registered member authority is missing or ambiguous")
    member = members[0]

    root = Path(__file__).resolve().parents[1]
    template_references = _template_references(root)
    if template_references:
        raise QualificationError("PARAFAC must remain absent from analysis-starter templates in 0.6.0")

    with tempfile.TemporaryDirectory(prefix="spectrasherpa-iasim16-") as temporary:
        source_path = Path(temporary) / MEMBER_NAME
        _extract_registered_member(
            archive_path,
            source_path,
            expected_size=member["expected_size_bytes"],
            expected_sha256=member["sha256"],
        )
        result = ingest(source_path)
        if (
            result.format_id != "matlab"
            or result.variant != "mat-v5"
            or result.parser_id != "spectrasherpa.matlab"
            or result.parser_version != "5"
            or result.warnings
        ):
            raise QualificationError("IASIM16 member did not follow the expected warning-free native MATLAB path")
        if [asset.asset_id for asset in result.assets] != ["z", "z:image-cube"]:
            raise QualificationError("IASIM16 DSO did not expose the exact unfolded and image-cube views")
        unfolded, cube = (asset.dataset for asset in result.assets)
        if unfolded.shape != (59_292, 229) or cube.shape != (243, 244, 229):
            raise QualificationError("IASIM16 native DSO shapes differ from the registered image authority")
        if not np.array_equal(cube.X.reshape((59_292, 229), order="F"), unfolded.X):
            raise QualificationError("IASIM16 image cube does not exactly refold the admitted pixel table")
        if tuple(str(value) for value in cube.layout.mode_roles) != (
            "spatial_coordinate",
            "spatial_coordinate",
            "feature",
        ):
            raise QualificationError("IASIM16 image cube lacks canonical spatial and feature mode roles")
        mask = cube.layout.image_include
        if mask is None or len(mask) != 59_292 or sum(mask) != 41_797:
            raise QualificationError("IASIM16 image cube did not preserve the DSO soft-exclusion mask")
        axis = cube.feature_axis
        if axis is None or axis.values is None or len(axis.values) != 229:
            raise QualificationError("IASIM16 image cube lacks its exact spectral coordinate")
        if float(axis.values[0]) != 1122.0 or float(axis.values[-1]) != 1578.0:
            raise QualificationError("IASIM16 spectral-coordinate endpoints differ from authority")
        if not np.isfinite(cube.X).all():
            raise QualificationError("IASIM16 image cube contains non-finite values")

        node = PARAFACNode("iasim16-parafac-qualification", PARAMETERS)
        first = asyncio.run(node.run(cube))
        second = asyncio.run(node.run(cube))
        first_metadata = first.outputs["model"]["metadata"]
        second_metadata = second.outputs["model"]["metadata"]
        if (
            not first.diagnostics["converged"]
            or first_metadata["state_content_digest"] != second_metadata["state_content_digest"]
        ):
            raise QualificationError("IASIM16 masked PARAFAC did not converge deterministically")
        if first.diagnostics["spatial_mask_policy"] != "binary-spatial-modes-0-1":
            raise QualificationError("IASIM16 PARAFAC did not honor the exact DSO spatial mask")
        if (
            first.diagnostics["included_spatial_cells"] != 41_797
            or first.diagnostics["excluded_spatial_cells"] != 17_495
        ):
            raise QualificationError("IASIM16 PARAFAC spatial-cell census differs from the source authority")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "qualification_date": "2026-09-04",
        "source_authority": {
            "artifact_id": ARTIFACT_ID,
            "archive_size_bytes": artifact["expected_size_bytes"],
            "archive_sha256": artifact["sha256"],
            "member_path": MEMBER_NAME,
            "member_size_bytes": member["expected_size_bytes"],
            "member_sha256": member["sha256"],
            "redistribution": artifact["redistribution"],
            "registry_sha256": reference_artifact_registry_digest(),
        },
        "native_ingestion": {
            "format_id": result.format_id,
            "variant": result.variant,
            "parser_id": result.parser_id,
            "parser_version": result.parser_version,
            "asset_ids": [asset.asset_id for asset in result.assets],
            "unfolded_shape": list(unfolded.shape),
            "image_cube_shape": list(cube.shape),
            "image_cube_mode_roles": [str(value) for value in cube.layout.mode_roles],
            "refolding_order": "MATLAB-column-major",
            "spectral_coordinate": {
                "count": len(axis.values),
                "first": float(axis.values[0]),
                "last": float(axis.values[-1]),
                "units_in_source": axis.units,
            },
            "included_spatial_cells": 41_797,
            "excluded_spatial_cells": 17_495,
            "warnings": list(result.warnings),
        },
        "parafac_execution": {
            "node_type": "model.parafac",
            "node_contract_sha256": execution_contract_digest(PARAFACNode.metadata),
            "parameters": PARAMETERS,
            "converged": first.diagnostics["converged"],
            "iterations": first.diagnostics["n_iter"],
            "relative_reconstruction_error": first.diagnostics["relative_reconstruction_error"],
            "spatial_mask_policy": first.diagnostics["spatial_mask_policy"],
            "unfolding": first.diagnostics["unfolding"],
            "state_content_sha256": first_metadata["state_content_digest"],
            "deterministic_repeat_match": True,
            "mode_1_score_shape": list(first.outputs["sample_scores"].shape),
        },
        "reachability": {
            "canonical_dag_node": True,
            "managed_optimization_eligible": False,
            "analysis_starter_template_references": template_references,
            "manual_dag_construction_required": True,
        },
        "scientific_interpretation": {
            "source_documented_quantity": "NIR reflectance scaled from 0 to 1",
            "source_documented_spectral_range": "1120-1580 nm; retained coordinates are 1122-1578",
            "purpose": "exploratory low-rank decomposition preserving two spatial modes and one spectral mode",
            "soft_exclusions_honored": True,
        },
        "claim_boundary": (
            "The exact registered IASIM16 Test_1.mat DSO is admitted by the bounded native MATLAB reader, "
            "refolded without changing values into its 243 x 244 x 229 image cube, and deterministically "
            "decomposed by the canonical masked PARAFAC node while honoring all 17,495 source-excluded pixels."
        ),
        "nonclaims": [
            "PARAFAC establishes melamine detection, identification, concentration, or challenge performance",
            "the source file declares spectral-axis units; nm is documented by the exact upstream challenge PDF",
            "Spectra Scientific redistributes or relicenses the IASIM16 archive",
            "PARAFAC is offered through an analysis-starter template in 0.6.0",
            "the qualification generalizes beyond the exact registered IASIM16 Test 1 source",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = qualify(args.archive)
    payload = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
