"""Small construction helpers shared by built-in format plugins."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.io.base import BoundedSource
from spectra_sherpa.io.types import IngestionResult, SpectralAsset

_MISSING_ROW_DISPLAY_LIMIT = 12


def derive_data_role(feature_axis: object | None) -> str:
    """Derive the canonical predictor role from the typed feature axis."""

    return "X_spectra" if isinstance(feature_axis, SpectralAxis) else "X_features"


def _missingness_warning(asset: SpectralAsset) -> str | None:
    values = np.asarray(asset.dataset.X)
    finite = np.isfinite(values)
    if asset.dataset.extra.get("process_log.schema_version") == "spectrasherpa-matlab-process-log/1":
        sample_axis = asset.dataset.sample_axis
        sample_table = None if sample_axis is None else sample_axis.sample_table
        counts = None if sample_table is None else sample_table.get("time_point_count")
        if values.ndim == 3 and counts is not None and len(counts) == values.shape[0]:
            observed = np.zeros(values.shape, dtype=bool)
            for index, count in enumerate(counts):
                if type(count) is int and 0 < count <= values.shape[1]:
                    observed[index, :count, :] = True
            observed_finite = finite | ~observed
            if observed_finite.all() and not finite.all():
                return (
                    f"Missing data preserved: asset {asset.asset_id!r} uses NaN only as structural padding "
                    "outside each wafer's governed source time-point count. The padding is not an observed "
                    "source value and is excluded by Wafer Time Average."
                )
            finite = observed_finite
    if finite.all():
        return None

    missing_count = int(np.count_nonzero(~finite))
    if values.ndim <= 1:
        affected = np.flatnonzero(~finite) + 1
        location = "data position(s)"
    else:
        affected = np.flatnonzero(np.any(~finite, axis=tuple(range(1, values.ndim)))) + 1
        location = "sample row(s)"
    shown = affected[:_MISSING_ROW_DISPLAY_LIMIT].tolist()
    remaining = int(affected.size - len(shown))
    row_text = ", ".join(str(index) for index in shown)
    if remaining:
        row_text += f", and {remaining} more"
    noun = "value" if missing_count == 1 else "values"
    return (
        f"Missing data preserved: asset {asset.asset_id!r} contains {missing_count} missing or non-finite "
        f"{noun} in {location} {row_text}. Modeling operations fail closed on missing data; repair the source "
        "or use Prepare Samples to exclude affected rows or variables. SpectraSherpa does not impute values "
        "implicitly."
    )


def dataset_asset(
    dataset: SherpaDataset,
    *,
    asset_id: str,
    raw_metadata: Mapping[str, Any] | None = None,
    warnings: tuple[str, ...] = (),
) -> SpectralAsset:
    declared_roles = tuple(dataset.layout.mode_roles)
    if declared_roles:
        roles = declared_roles
    elif dataset.ndim == 1:
        roles = ("spectral_feature",)
    elif dataset.ndim == 2:
        roles = ("sample", "spectral_feature" if derive_data_role(dataset.feature_axis) == "X_spectra" else "feature")
    else:
        roles = tuple(
            "sample" if index == 0 else "spectral_feature" if index == dataset.ndim - 1 else "inner"
            for index in range(dataset.ndim)
        )
    return SpectralAsset(
        asset_id=asset_id,
        dataset=dataset,
        dimension_roles=roles,
        raw_metadata=raw_metadata or {},
        warnings=warnings,
    )


def ingestion_result(
    *,
    source: BoundedSource,
    format_id: str,
    variant: str,
    parser_id: str,
    parser_version: str,
    assets: tuple[SpectralAsset, ...],
    raw_metadata: Mapping[str, Any] | None = None,
    warnings: tuple[str, ...] = (),
) -> IngestionResult:
    missingness_warnings = tuple(warning for asset in assets if (warning := _missingness_warning(asset)) is not None)
    return IngestionResult(
        format_id=format_id,
        variant=variant,
        parser_id=parser_id,
        parser_version=parser_version,
        source_members=(source.member(),),
        assets=assets,
        raw_metadata=raw_metadata or {},
        warnings=tuple(dict.fromkeys((*warnings, *missingness_warnings))),
    )
