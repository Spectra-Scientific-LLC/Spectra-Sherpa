#!/usr/bin/env python3
"""Qualify real-source axis admission across the 0.6 native format set.

Private Avatar/JF and IASIM16 bytes stay in caller-controlled custody.  This
command emits only parser identities, shapes, canonical axis semantics, and
the data-free receipts produced by their dedicated qualification tools.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from qualify_avatar_jf_parser_triplets import (
    AUTHORITIES,
    EXPECTED_NUMBERS,
    LIMITS,
    _admit_archive,
)
from qualify_avatar_jf_parser_triplets import (
    qualify as qualify_jf_triplets,
)

from spectra_sherpa.core.axis_semantics import axis_semantics
from spectra_sherpa.io import ingest

SCHEMA_VERSION = "spectrasherpa-vendor-axis-admission-sweep/1"


class QualificationError(ValueError):
    """One closed vendor-axis admission invariant failed."""


def _axis_record(path: Path, *, parser_options: dict[str, str] | None = None) -> dict[str, Any]:
    result = ingest(path, limits=LIMITS if parser_options is not None else None, parser_options=parser_options)
    assets: list[dict[str, Any]] = []
    for asset in result.assets:
        axis = asset.dataset.feature_axis
        if axis is None:
            continue
        semantics = axis_semantics(
            axis_class=type(axis).__name__,
            title=axis.title,
            units=axis.units,
            quantity=axis.quantity,
        )
        assets.append(
            {
                "asset_id": asset.asset_id,
                "shape": list(asset.dataset.shape),
                "axis_class": type(axis).__name__,
                "axis_title": axis.title,
                "canonical_axis_units": semantics.units,
                "canonical_axis_quantity": semantics.quantity.value if semantics.quantity is not None else None,
            }
        )
    if not assets:
        raise QualificationError(f"{path.name} exposed no feature-axis authority")
    return {
        "format_id": result.format_id,
        "variant": result.variant,
        "parser_id": result.parser_id,
        "parser_version": result.parser_version,
        "assets": assets,
        "warnings": list(result.warnings),
    }


def qualify(*, repository_root: Path, jf_input_dir: Path, iasim_receipt_path: Path) -> dict[str, Any]:
    jf_receipt = qualify_jf_triplets(jf_input_dir)
    if jf_receipt.get("status") != "pass":
        raise QualificationError("Avatar/JF same-source parser qualification did not pass")

    private_cases: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="spectrasherpa-vendor-axis-") as temporary:
        temporary_root = Path(temporary)
        number = EXPECTED_NUMBERS[0]
        for kind, authority in AUTHORITIES.items():
            raw = _admit_archive(jf_input_dir, authority)[number]
            source = temporary_root / f"jf-{number}{authority.suffix}"
            source.write_bytes(raw)
            record = _axis_record(source, parser_options=authority.parser_options)
            if record["parser_id"] != authority.parser_id:
                raise QualificationError(f"{kind} did not use its expected native parser")
            private_cases[kind] = record

    fixtures = repository_root / "packages" / "spectra-sherpa" / "tests" / "fixtures"
    bundled_sources = {
        "opus": fixtures / "opus" / "openspecy-polystyrene.0",
        "spc": fixtures / "spc" / "nir.spc",
        "wdf": fixtures / "wdf" / "sp.wdf",
    }
    bundled_cases = {name: _axis_record(path) for name, path in bundled_sources.items()}

    iasim_receipt = json.loads(iasim_receipt_path.read_text(encoding="utf-8"))
    iasim_ingestion = iasim_receipt.get("native_ingestion")
    if iasim_receipt.get("status") != "passed" or not isinstance(iasim_ingestion, dict):
        raise QualificationError("current IASIM16 native-ingestion receipt is unavailable")
    if (
        iasim_ingestion.get("format_id") != "matlab"
        or iasim_ingestion.get("parser_id") != "spectrasherpa.matlab"
        or iasim_ingestion.get("parser_version") != "5"
    ):
        raise QualificationError("IASIM16 DSO receipt does not use the expected native MATLAB reader")

    cases = {**private_cases, **bundled_cases}
    expected_parsers = {
        "spa": "spectrasherpa.omnic",
        "csv": "spectrasherpa.csv",
        "jdx": "spectrasherpa.jcamp",
        "opus": "spectrasherpa.opus",
        "spc": "spectrasherpa.spc",
        "wdf": "spectrasherpa.native.wdf",
    }
    for name, parser_id in expected_parsers.items():
        if cases[name]["parser_id"] != parser_id:
            raise QualificationError(f"{name} parser identity changed")
    if "spectrochempy" in __import__("sys").modules:
        raise QualificationError("SpectroChemPy was loaded during the native vendor-axis sweep")

    source_digests = {
        relative: hashlib.sha256((repository_root / relative).read_bytes()).hexdigest()
        for relative in (
            "packages/spectra-sherpa/src/spectra_sherpa/core/axis_semantics.py",
            "packages/spectra-sherpa/src/spectra_sherpa/io/registry.py",
            "packages/spectra-sherpa/src/spectra_sherpa/io/invariants.py",
        )
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "qualification_date": "2026-09-04",
        "cases": cases,
        "matlab_dso": iasim_ingestion,
        "avatar_jf_same_source_summary": jf_receipt["summary"],
        "axis_authority_source_sha256": source_digests,
        "spectrochempy_loaded": False,
        "claim": (
            "Real OMNIC SPA, supplier CSV, JCAMP-DX, Bruker OPUS, Galactic SPC, Renishaw WDF, and "
            "Eigenvector MATLAB DSO sources are admitted by the current bounded native registry with canonical "
            "feature-axis semantics and no SpectroChemPy import or fallback."
        ),
        "nonclaims": [
            "every dialect or historical variant of these format families is qualified",
            "unknown source axis quantities are guessed from numerical values",
            "the private Avatar/JF or IASIM16 source bytes are redistributed",
            "axis-grid harmonization is automatic or scientifically appropriate without an explicit DAG step",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jf-input-dir", type=Path, required=True)
    parser.add_argument("--iasim-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[3]
    receipt = qualify(
        repository_root=repository_root,
        jf_input_dir=args.jf_input_dir,
        iasim_receipt_path=args.iasim_receipt,
    )
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
