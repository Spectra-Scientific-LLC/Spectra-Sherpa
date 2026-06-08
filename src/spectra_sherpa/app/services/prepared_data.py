from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.core.config import settings

logger = logging.getLogger(__name__)
from spectra_sherpa.app.lib.data_roles import normalize_data_role
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset, SpectralAxis


@dataclass(frozen=True)
class PreparedDataOverrides:
    title: str | None = None
    x_title: str | None = None
    x_units: str | None = None
    y_title: str | None = None
    y_units: str | None = None
    is_time_series: bool | None = None
    data_role: str | None = None
    target_column: str | None = None
    target_type: str | None = None

    @classmethod
    def from_mapping(cls, overrides: Mapping[str, Any] | None) -> "PreparedDataOverrides":
        if not overrides:
            return cls()
        return cls(
            title=_normalize_text(overrides.get("title")),
            x_title=_normalize_text(overrides.get("x_title")),
            x_units=_normalize_text(overrides.get("x_units"), allow_empty=True),
            y_title=_normalize_text(overrides.get("y_title")),
            y_units=_normalize_text(overrides.get("y_units"), allow_empty=True),
            is_time_series=_normalize_bool(overrides.get("is_time_series")),
            data_role=_normalize_data_role_value(overrides.get("data_role")),
            target_column=_normalize_text(overrides.get("target_column")),
            target_type=_normalize_target_type(overrides.get("target_type")),
        )

    def to_sidecar_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.title is not None:
            payload["title"] = self.title
        if self.x_title is not None:
            payload["x_title"] = self.x_title
        if self.x_units is not None:
            payload["x_units"] = self.x_units
        if self.y_title is not None:
            payload["y_title"] = self.y_title
        if self.y_units is not None:
            payload["y_units"] = self.y_units
        if self.is_time_series is not None:
            payload["is_time_series"] = self.is_time_series
        if self.data_role is not None:
            payload["data_role"] = self.data_role
        if self.target_column is not None:
            payload["target_column"] = self.target_column
        if self.target_type is not None:
            payload["target_type"] = self.target_type
        return payload

    def to_prompt_dict(self) -> dict[str, Any]:
        payload = self.to_sidecar_dict()
        if "y_title" in payload:
            payload["data_quantity"] = payload.pop("y_title")
        return payload

    def is_empty(self) -> bool:
        return not any(
            value is not None
            for value in (
                self.x_title,
                self.title,
                self.x_units,
                self.y_title,
                self.y_units,
                self.is_time_series,
                self.data_role,
                self.target_column,
                self.target_type,
            )
        )


_OVERRIDES_DIR = Path(settings.data_dir) / ".metadata_overrides"


def _normalize_text(value: Any, *, allow_empty: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text and not allow_empty:
        return None
    return text


def _normalize_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _normalize_data_role_value(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return normalize_data_role(value)


def _normalize_target_type(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "auto":
        return None
    if text not in {"continuous", "categorical"}:
        raise ValueError("target_type must be continuous, categorical, or auto")
    return text


def normalize_relative_data_path(file_path: str) -> str:
    # Metadata sidecars only need a stable identifier; this helper normalizes
    # display/storage keys and does not open the path. Sidecar filenames are
    # derived from a SHA-256 digest, never from this raw string directly.
    # lgtm[py/path-injection]
    path = Path(file_path)
    if path.is_absolute():
        try:
            normalized = str(path.resolve().relative_to(settings.data_dir))
        except ValueError:
            normalized = str(path.resolve())
    else:
        normalized = file_path
    return normalized.replace("\\", "/")


def _sidecar_digest(kind: str, *parts: str) -> str:
    """Return an opaque, filesystem-safe identifier for a sidecar record."""
    payload = "\x1f".join([kind, *parts])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sidecar_path(*, file_path: str | None, source: str | None, name: str | None) -> Path:
    if source and name:
        filename = f"ref__{_sidecar_digest('ref', source, name)}.json"
    elif file_path:
        filename = f"file__{_sidecar_digest('file', normalize_relative_data_path(file_path))}.json"
    else:
        raise ValueError("Either file_path or source+name required")

    sanitised = _OVERRIDES_DIR / filename
    # Final containment check: the resolved sidecar must live under
    # ``_OVERRIDES_DIR``.  This is belt-and-braces — the filename is now
    # a fixed-prefix SHA-256 hex digest — but defends against drift if the
    # directory is ever computed differently.
    overrides_root = _OVERRIDES_DIR.resolve()
    resolved = sanitised.resolve()
    if not resolved.is_relative_to(overrides_root):
        raise ValueError("Computed sidecar path escapes the overrides directory.")
    return sanitised


def load_prepared_data_overrides(
    *,
    file_path: str | None = None,
    source: str | None = None,
    name: str | None = None,
) -> PreparedDataOverrides:
    try:
        target = sidecar_path(file_path=file_path, source=source, name=name)
        if target.exists():
            return PreparedDataOverrides.from_mapping(json.loads(target.read_text(encoding="utf-8")))
    except Exception:
        logger.warning("Failed to load prepared data overrides for %s", file_path or source or name, exc_info=True)
        return PreparedDataOverrides()
    return PreparedDataOverrides()


def save_prepared_data_overrides(
    overrides: PreparedDataOverrides | Mapping[str, Any],
    *,
    file_path: str | None = None,
    source: str | None = None,
    name: str | None = None,
) -> None:
    prepared = (
        overrides if isinstance(overrides, PreparedDataOverrides) else PreparedDataOverrides.from_mapping(overrides)
    )
    target = sidecar_path(file_path=file_path, source=source, name=name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(prepared.to_sidecar_dict(), indent=2), encoding="utf-8")


def apply_serialized_prepared_data_overrides(
    result: dict[str, Any],
    overrides: PreparedDataOverrides | Mapping[str, Any],
) -> dict[str, Any]:
    prepared = (
        overrides if isinstance(overrides, PreparedDataOverrides) else PreparedDataOverrides.from_mapping(overrides)
    )
    if prepared.is_empty():
        return result

    if prepared.title is not None:
        result["title"] = prepared.title
    meta = result.setdefault("metadata", {})
    if prepared.x_title is not None:
        meta["x_title"] = prepared.x_title
        axis = result.get("x_axis") or result.get("feature_axis")
        if isinstance(axis, dict):
            axis["title"] = prepared.x_title
    if prepared.x_units is not None:
        meta["x_units"] = prepared.x_units
        axis = result.get("x_axis") or result.get("feature_axis")
        if isinstance(axis, dict):
            axis["units"] = prepared.x_units
    if prepared.y_title is not None:
        meta["data_quantity"] = prepared.y_title
    if prepared.y_units is not None:
        meta["value_units"] = prepared.y_units
    if prepared.is_time_series is not None:
        meta["is_time_series"] = prepared.is_time_series
        result["is_time_series"] = prepared.is_time_series
    if prepared.data_role is not None:
        meta["data_role"] = prepared.data_role
        result["data_role"] = prepared.data_role
    if prepared.target_column is not None:
        meta["target_column"] = prepared.target_column
    if prepared.target_type is not None:
        meta["target_type"] = prepared.target_type
    return result


def apply_dataset_prepared_data_overrides(
    dataset: SherpaDataset,
    overrides: PreparedDataOverrides | Mapping[str, Any],
    *,
    allow_x_title: bool = True,
    allow_x_units: bool = True,
    allow_y_title: bool = True,
    allow_is_time_series: bool = True,
) -> SherpaDataset:
    prepared = (
        overrides if isinstance(overrides, PreparedDataOverrides) else PreparedDataOverrides.from_mapping(overrides)
    )
    if prepared.is_empty():
        return dataset
    if dataset.get_extra("csv.layout") == "axis_column_conditions" and prepared.data_role == "X_features":
        prepared = replace(prepared, data_role=None)

    if prepared.title is not None:
        dataset.title = prepared.title

    feature_axis = dataset.feature_axis
    if (
        feature_axis is None
        and dataset.data.ndim >= 1
        and (prepared.x_title is not None or prepared.x_units is not None)
    ):
        axis_cls = FeatureAxis if prepared.data_role == "X_features" else SpectralAxis
        feature_axis = axis_cls(values=np.arange(dataset.data.shape[-1], dtype=float), title="Feature")
        dataset.feature_axis = feature_axis

    if prepared.data_role is not None:
        dataset.data_role = prepared.data_role

    if feature_axis is not None and (prepared.x_title is not None or prepared.x_units is not None):
        updated_axis = feature_axis.copy()
        if allow_x_title and prepared.x_title is not None:
            updated_axis.title = prepared.x_title
        if allow_x_units and prepared.x_units is not None:
            updated_axis.units = prepared.x_units or None
        dataset.feature_axis = updated_axis

    domain = dataset.domain.model_copy(deep=True)
    if allow_x_units and prepared.x_units is not None:
        domain.expected_units = prepared.x_units or None
    if allow_y_title and prepared.y_title is not None:
        domain.data_quantity = prepared.y_title
    dataset.domain = domain
    if prepared.y_units is not None:
        dataset.units = prepared.y_units or None

    if allow_x_title and prepared.x_title is not None:
        dataset.meta["x_title"] = prepared.x_title
    if allow_x_units and prepared.x_units is not None:
        dataset.meta["x_units"] = prepared.x_units
    if allow_y_title and prepared.y_title is not None:
        dataset.meta["data_quantity"] = prepared.y_title
    if prepared.y_units is not None:
        dataset.meta["value_units"] = prepared.y_units or None
        dataset.set_extra("scp.value_units_label", prepared.y_units or None)
    if allow_is_time_series and prepared.is_time_series is not None:
        dataset.is_time_series = prepared.is_time_series
        dataset.meta["is_time_series"] = prepared.is_time_series
    if prepared.target_column is not None:
        dataset.meta["csv.target_column"] = prepared.target_column
    if prepared.target_type is not None:
        dataset.meta["csv.target_type"] = prepared.target_type

    return dataset


def merge_prepared_data_overrides(overrides: list[PreparedDataOverrides]) -> PreparedDataOverrides:
    merged = PreparedDataOverrides()
    for current in overrides:
        if current.title is not None and merged.title is None:
            merged = replace(merged, title=current.title)
        if current.x_title is not None and merged.x_title is None:
            merged = replace(merged, x_title=current.x_title)
        if current.x_units is not None and merged.x_units is None:
            merged = replace(merged, x_units=current.x_units)
        if current.y_title is not None and merged.y_title is None:
            merged = replace(merged, y_title=current.y_title)
        if current.is_time_series is not None and merged.is_time_series is None:
            merged = replace(merged, is_time_series=current.is_time_series)
        if current.data_role is not None and merged.data_role is None:
            merged = replace(merged, data_role=current.data_role)
        if current.target_column is not None and merged.target_column is None:
            merged = replace(merged, target_column=current.target_column)
        if current.target_type is not None and merged.target_type is None:
            merged = replace(merged, target_type=current.target_type)
    return merged


def load_prepared_data_overrides_for_source(
    *,
    source: str,
    parameters: Mapping[str, Any],
    resolved_file_paths: list[str] | None = None,
) -> PreparedDataOverrides:
    file_paths = resolved_file_paths or []
    if file_paths:
        loaded = [load_prepared_data_overrides(file_path=normalize_relative_data_path(path)) for path in file_paths]
        return merge_prepared_data_overrides(loaded)

    if source == "file":
        file_path = parameters.get("file_path")
        if isinstance(file_path, str) and file_path:
            return load_prepared_data_overrides(file_path=normalize_relative_data_path(file_path))

    reference_name = reference_dataset_name(source=source, parameters=parameters)
    if reference_name is not None:
        return load_prepared_data_overrides(source=source, name=reference_name)

    return PreparedDataOverrides()


def reference_dataset_name(*, source: str, parameters: Mapping[str, Any]) -> str | None:
    if source == "sklearn":
        value = parameters.get("sklearn_dataset")
        return str(value) if value else None
    if source == "eigenvector":
        value = parameters.get("eigenvector_dataset")
        return str(value) if value else None
    if source == "spectrochempy":
        example_dataset = str(parameters.get("example_dataset") or "").strip()
        example_file = str(parameters.get("example_file") or "").strip()
        if example_file:
            return example_file if "/" in example_file else f"{example_dataset}/{example_file}"
        return example_dataset or None
    if source == "oes":
        value = parameters.get("oes_dataset")
        return str(value) if value else None
    return None
