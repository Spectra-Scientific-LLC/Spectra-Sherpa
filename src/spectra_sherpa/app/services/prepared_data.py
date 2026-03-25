from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.core.config import settings

logger = logging.getLogger(__name__)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis


@dataclass(frozen=True)
class PreparedDataOverrides:
    x_title: str | None = None
    x_units: str | None = None
    y_title: str | None = None
    is_time_series: bool | None = None

    @classmethod
    def from_mapping(cls, overrides: Mapping[str, Any] | None) -> "PreparedDataOverrides":
        if not overrides:
            return cls()
        return cls(
            x_title=_normalize_text(overrides.get("x_title")),
            x_units=_normalize_text(overrides.get("x_units"), allow_empty=True),
            y_title=_normalize_text(overrides.get("y_title")),
            is_time_series=_normalize_bool(overrides.get("is_time_series")),
        )

    def to_sidecar_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.x_title is not None:
            payload["x_title"] = self.x_title
        if self.x_units is not None:
            payload["x_units"] = self.x_units
        if self.y_title is not None:
            payload["y_title"] = self.y_title
        if self.is_time_series is not None:
            payload["is_time_series"] = self.is_time_series
        return payload

    def to_prompt_dict(self) -> dict[str, Any]:
        payload = self.to_sidecar_dict()
        if "y_title" in payload:
            payload["data_quantity"] = payload.pop("y_title")
        return payload

    def is_empty(self) -> bool:
        return not any(value is not None for value in (self.x_title, self.x_units, self.y_title, self.is_time_series))


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


def normalize_relative_data_path(file_path: str) -> str:
    path = Path(file_path)
    if path.is_absolute():
        try:
            return str(path.resolve().relative_to(settings.data_dir))
        except ValueError:
            return str(path.resolve())
    return file_path


def sidecar_path(*, file_path: str | None, source: str | None, name: str | None) -> Path:
    if source and name:
        return _OVERRIDES_DIR / f"ref__{source}__{name}.json"
    if file_path:
        safe = normalize_relative_data_path(file_path).replace("/", "__").replace("\\", "__")
        return _OVERRIDES_DIR / f"file__{safe}.json"
    raise ValueError("Either file_path or source+name required")


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
    if prepared.is_time_series is not None:
        meta["is_time_series"] = prepared.is_time_series
        result["is_time_series"] = prepared.is_time_series
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

    feature_axis = dataset.feature_axis
    if (
        feature_axis is None
        and dataset.data.ndim >= 1
        and (prepared.x_title is not None or prepared.x_units is not None)
    ):
        feature_axis = SpectralAxis(values=np.arange(dataset.data.shape[-1], dtype=float), title="Feature")
        dataset.feature_axis = feature_axis

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

    if allow_x_title and prepared.x_title is not None:
        dataset.meta["x_title"] = prepared.x_title
    if allow_x_units and prepared.x_units is not None:
        dataset.meta["x_units"] = prepared.x_units
    if allow_y_title and prepared.y_title is not None:
        dataset.meta["data_quantity"] = prepared.y_title
    if allow_is_time_series and prepared.is_time_series is not None:
        dataset.is_time_series = prepared.is_time_series
        dataset.meta["is_time_series"] = prepared.is_time_series

    return dataset


def merge_prepared_data_overrides(overrides: list[PreparedDataOverrides]) -> PreparedDataOverrides:
    merged = PreparedDataOverrides()
    for current in overrides:
        if current.x_title is not None and merged.x_title is None:
            merged = PreparedDataOverrides(
                x_title=current.x_title,
                x_units=merged.x_units,
                y_title=merged.y_title,
                is_time_series=merged.is_time_series,
            )
        if current.x_units is not None and merged.x_units is None:
            merged = PreparedDataOverrides(
                x_title=merged.x_title,
                x_units=current.x_units,
                y_title=merged.y_title,
                is_time_series=merged.is_time_series,
            )
        if current.y_title is not None and merged.y_title is None:
            merged = PreparedDataOverrides(
                x_title=merged.x_title,
                x_units=merged.x_units,
                y_title=current.y_title,
                is_time_series=merged.is_time_series,
            )
        if current.is_time_series is not None and merged.is_time_series is None:
            merged = PreparedDataOverrides(
                x_title=merged.x_title,
                x_units=merged.x_units,
                y_title=merged.y_title,
                is_time_series=current.is_time_series,
            )
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
