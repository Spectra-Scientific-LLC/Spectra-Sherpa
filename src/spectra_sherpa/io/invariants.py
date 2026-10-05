"""Closed conformance invariants for every native ingestion result."""

from __future__ import annotations

from enum import StrEnum

import numpy as np

from spectra_sherpa.app.lib.axes import canonicalize_feature_axis
from spectra_sherpa.ingestion_errors import FormatIdentityError
from spectra_sherpa.io.authority import INGESTION_AUTHORITY_SCHEMA
from spectra_sherpa.io.formats._helpers import derive_data_role
from spectra_sherpa.io.types import IngestionResult


class IngestionInvariant(StrEnum):
    """Stable names for the checks applied at the reader boundary."""

    RESULT_IDENTITY = "result_identity"
    SOURCE_IDENTITY = "source_identity"
    ASSET_IDENTITY = "asset_identity"
    NUMERIC_SHAPE = "numeric_shape"
    DIMENSION_ROLES = "dimension_roles"
    FEATURE_AXIS = "feature_axis"
    DATA_ROLE = "data_role"
    MISSINGNESS_DISCLOSURE = "missingness_disclosure"
    INGESTION_AUTHORITY = "ingestion_authority"


INGESTION_INVARIANTS = tuple(IngestionInvariant)


def _fail(invariant: IngestionInvariant, detail: str) -> None:
    raise FormatIdentityError(f"Ingestion invariant {invariant.value!r} failed: {detail}")


def assert_ingestion_invariants(
    result: IngestionResult,
    *,
    expected_format_id: str,
    expected_parser_id: str,
    expected_parser_version: str,
) -> tuple[str, ...]:
    """Fail closed unless one result satisfies the complete current checklist."""

    if (
        result.format_id != expected_format_id
        or result.parser_id != expected_parser_id
        or result.parser_version != expected_parser_version
    ):
        _fail(IngestionInvariant.RESULT_IDENTITY, "result identity differs from the selected plugin")

    if not result.source_members or len({(member.name, member.sha256) for member in result.source_members}) != len(
        result.source_members
    ):
        _fail(IngestionInvariant.SOURCE_IDENTITY, "source members are absent or aliased")

    asset_ids = [asset.asset_id for asset in result.assets]
    if not asset_ids or len(asset_ids) != len(set(asset_ids)):
        _fail(IngestionInvariant.ASSET_IDENTITY, "asset identifiers are absent or duplicated")

    source_projection = [
        {"name": member.name, "sha256": member.sha256, "size_bytes": member.size_bytes}
        for member in result.source_members
    ]
    invariant_projection = [invariant.value for invariant in INGESTION_INVARIANTS]
    for asset in result.assets:
        dataset = asset.dataset
        values = np.asarray(dataset.X)
        if values.ndim < 1 or values.size < 1 or tuple(values.shape) != tuple(dataset.shape):
            _fail(IngestionInvariant.NUMERIC_SHAPE, f"asset {asset.asset_id!r} has an empty or contradictory shape")
        if not np.issubdtype(values.dtype, np.number) or np.iscomplexobj(values):
            _fail(IngestionInvariant.NUMERIC_SHAPE, f"asset {asset.asset_id!r} is not a real numeric array")

        roles = tuple(str(role) for role in asset.dimension_roles)
        layout_roles = tuple(str(role) for role in dataset.layout.mode_roles)
        if len(roles) != values.ndim or (layout_roles and layout_roles != roles):
            _fail(
                IngestionInvariant.DIMENSION_ROLES,
                f"asset {asset.asset_id!r} does not carry one consistent canonical role per dimension",
            )

        axis = dataset.feature_axis
        if axis is not None:
            if axis.values is not None and len(axis.values) != values.shape[-1]:
                _fail(IngestionInvariant.FEATURE_AXIS, f"asset {asset.asset_id!r} feature-axis length is wrong")
            canonical = canonicalize_feature_axis(axis)
            if canonical.units != axis.units or canonical.quantity != axis.quantity:
                _fail(
                    IngestionInvariant.FEATURE_AXIS,
                    f"asset {asset.asset_id!r} feature-axis semantics are not canonical",
                )

        if dataset.data_role != derive_data_role(axis):
            _fail(IngestionInvariant.DATA_ROLE, f"asset {asset.asset_id!r} data role contradicts its feature axis")

        warnings = tuple(dict.fromkeys((*result.warnings, *asset.warnings)))
        if not np.isfinite(values).all() and not any(
            warning.startswith("Missing data preserved:") for warning in warnings
        ):
            _fail(
                IngestionInvariant.MISSINGNESS_DISCLOSURE,
                f"asset {asset.asset_id!r} has undisclosed non-finite data",
            )

        authority = dataset.get_extra("ingestion.authority")
        expected_authority = {
            "schema": INGESTION_AUTHORITY_SCHEMA,
            "format_id": result.format_id,
            "variant": result.variant,
            "parser_id": result.parser_id,
            "parser_version": result.parser_version,
            "asset_id": asset.asset_id,
            "source_members": source_projection,
            "warnings": list(warnings),
            "invariants": invariant_projection,
        }
        if authority != expected_authority:
            _fail(IngestionInvariant.INGESTION_AUTHORITY, f"asset {asset.asset_id!r} authority is incomplete")

    return tuple(invariant_projection)


__all__ = [
    "INGESTION_AUTHORITY_SCHEMA",
    "INGESTION_INVARIANTS",
    "IngestionInvariant",
    "assert_ingestion_invariants",
]
