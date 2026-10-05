"""Pure prepared-data metadata contracts and dataset transformations.

Filesystem sidecars are an application concern.  This module owns only the
closed override value and the deterministic transformation it applies to a
scientific dataset, so canonical nodes can use it without discovering settings
or persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

import numpy as np

from spectra_sherpa.app.lib.data_roles import DATA_ROLES, normalize_data_role
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset, SpectralAxis, TargetContext


@dataclass(frozen=True)
class PreparedDataOverrides:
    title: str | None = None
    x_title: str | None = None
    x_units: str | None = None
    y_title: str | None = None
    y_units: str | None = None
    technique: str | None = None
    is_time_series: bool | None = None
    data_role: str | None = None
    target_column: str | None = None
    target_type: str | None = None
    target_mode: str | None = None
    selected_target: str | None = None
    csv_layout: str | None = None

    _FIELDS = (
        "title",
        "x_title",
        "x_units",
        "y_title",
        "y_units",
        "technique",
        "is_time_series",
        "data_role",
        "target_column",
        "target_type",
        "target_mode",
        "selected_target",
        "csv_layout",
    )
    _TEXT_MAX_UTF8_BYTES = 4096

    @classmethod
    def from_mapping(cls, overrides: Mapping[str, Any] | None) -> "PreparedDataOverrides":
        if not overrides:
            return cls()
        return cls(
            title=_normalize_text(overrides.get("title"), allow_empty=True),
            x_title=_normalize_text(overrides.get("x_title"), allow_empty=True),
            x_units=_normalize_text(overrides.get("x_units"), allow_empty=True),
            y_title=_normalize_text(overrides.get("y_title"), allow_empty=True),
            y_units=_normalize_text(overrides.get("y_units"), allow_empty=True),
            technique=_normalize_text(overrides.get("technique")),
            is_time_series=_normalize_bool(overrides.get("is_time_series")),
            data_role=_normalize_data_role_value(overrides.get("data_role")),
            target_column=_normalize_text(overrides.get("target_column")),
            target_type=_normalize_target_type(overrides.get("target_type")),
            target_mode=_normalize_target_mode(overrides.get("target_mode")),
            selected_target=_normalize_text(overrides.get("selected_target")),
            csv_layout=_normalize_csv_layout(overrides.get("csv_layout")),
        )

    @classmethod
    def from_sidecar_mapping(cls, overrides: Mapping[str, Any]) -> "PreparedDataOverrides":
        """Admit durable sidecar state without UI-style coercion or key loss."""

        unknown = set(overrides) - set(cls._FIELDS)
        if unknown:
            raise ValueError(f"prepared-data sidecar contains unsupported fields: {sorted(unknown)!r}")
        admitted: dict[str, Any] = {}
        for name, value in overrides.items():
            if name == "is_time_series":
                if type(value) is not bool:
                    raise ValueError("prepared-data is_time_series must be a boolean")
            else:
                if not isinstance(value, str):
                    raise ValueError(f"prepared-data {name} must be a string")
                if len(value.encode("utf-8")) > cls._TEXT_MAX_UTF8_BYTES:
                    raise ValueError(f"prepared-data {name} exceeds the text limit")
            admitted[name] = value

        if "data_role" in admitted and admitted["data_role"] not in DATA_ROLES:
            raise ValueError("prepared-data data_role is not canonical")
        if "target_type" in admitted and admitted["target_type"] not in {"continuous", "categorical"}:
            raise ValueError("prepared-data target_type is not canonical")
        if "target_mode" in admitted and admitted["target_mode"] not in {"single", "multi"}:
            raise ValueError("prepared-data target_mode is not canonical")
        if "csv_layout" in admitted:
            admitted["csv_layout"] = _normalize_csv_layout(admitted["csv_layout"])
        return cls(**admitted)

    def to_sidecar_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for name in self._FIELDS:
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return payload

    def to_prompt_dict(self) -> dict[str, Any]:
        payload = self.to_sidecar_dict()
        if "y_title" in payload:
            payload["data_quantity"] = payload.pop("y_title")
        return payload

    def is_empty(self) -> bool:
        return not self.to_sidecar_dict()


def _normalize_text(value: Any, *, allow_empty: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text and not allow_empty:
        return None
    return text


def _normalize_bool(value: Any) -> bool | None:
    return None if value is None else bool(value)


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


def _normalize_target_mode(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "auto":
        return None
    aliases = {
        "single-target": "single",
        "single_property": "single",
        "single-property": "single",
        "multi-target": "multi",
        "multi_property": "multi",
        "multi-property": "multi",
    }
    text = aliases.get(text, text)
    if text not in {"single", "multi"}:
        raise ValueError("target_mode must be single, multi, or auto")
    return text


CSV_LAYOUTS = (
    "headered",
    "headerless_two_column_spectrum",
    "headerless_axis_column_spectra",
    "headered_decimal_comma",
    "headerless_two_column_spectrum_decimal_comma",
    "headerless_axis_column_spectra_decimal_comma",
)


def csv_layout_settings(value: Any) -> tuple[str, str]:
    """Return the structural layout and decimal mark for one closed CSV profile."""

    layout = _normalize_csv_layout(value)
    if layout is None:
        return "auto", "."
    decimal = "," if layout.endswith("_decimal_comma") else "."
    structural = layout.removesuffix("_decimal_comma")
    return structural, decimal


def _normalize_csv_layout(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "auto":
        return None
    if text not in CSV_LAYOUTS:
        raise ValueError(f"csv_layout must be one of: {', '.join(CSV_LAYOUTS)}")
    return text


def parser_options_for_prepared_data(
    file_name: str,
    overrides: PreparedDataOverrides | Mapping[str, Any] | None,
) -> dict[str, str] | None:
    """Project durable source-interpretation authority into native parser options."""

    prepared = (
        overrides if isinstance(overrides, PreparedDataOverrides) else PreparedDataOverrides.from_mapping(overrides)
    )
    if prepared.csv_layout is None:
        return None
    if not str(file_name).casefold().endswith(".csv"):
        raise ValueError("csv_layout can be attached only to a CSV source")
    return {"csv_layout": prepared.csv_layout}


def _selected_target_from_context(dataset: SherpaDataset, selected: str | None) -> str | None:
    context = dataset.target_context
    names = list(context.target_names or [])
    if selected and (not names or selected in names):
        return selected
    if selected and names:
        available = ", ".join(str(name) for name in names)
        raise ValueError(f"Selected target {selected!r} is not available. Available targets: {available}.")
    if names:
        return str(names[0])
    if selected:
        return selected
    return str(context.target_name) if context.target_name else None


def bind_explicit_target_selection(
    overrides: PreparedDataOverrides,
    *,
    selected_target: object = None,
    target_type: object = None,
) -> PreparedDataOverrides:
    """Make a saved DAG's explicit target selection authoritative."""

    if selected_target is None:
        return overrides
    return replace(
        overrides,
        target_column=str(selected_target),
        selected_target=str(selected_target),
        target_mode="single",
        target_type=str(target_type) if target_type is not None else overrides.target_type,
    )


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
    for name, key in (
        ("x_title", "x_title"),
        ("x_units", "x_units"),
        ("y_title", "data_quantity"),
        ("y_units", "value_units"),
        ("technique", "technique"),
        ("is_time_series", "is_time_series"),
        ("data_role", "data_role"),
        ("target_column", "target_column"),
        ("target_type", "target_type"),
        ("target_mode", "target_mode"),
        ("selected_target", "selected_target"),
        ("csv_layout", "csv_layout"),
    ):
        value = getattr(prepared, name)
        if value is not None:
            meta[key] = value
    if prepared.x_title is not None or prepared.x_units is not None:
        axis = result.get("x_axis") or result.get("feature_axis")
        if isinstance(axis, dict):
            if prepared.x_title is not None:
                axis["title"] = prepared.x_title
            if prepared.x_units is not None:
                axis["units"] = prepared.x_units
    if prepared.is_time_series is not None:
        result["is_time_series"] = prepared.is_time_series
    if prepared.data_role is not None:
        result["data_role"] = prepared.data_role
    if prepared.target_mode is not None or prepared.selected_target is not None:
        target_context = result.get("target_context")
        if isinstance(target_context, dict):
            if prepared.target_mode == "multi":
                target_context["selected_target"] = None
            else:
                names = target_context.get("target_names")
                selected = prepared.selected_target
                if selected is None and isinstance(names, list) and names:
                    selected = str(names[0])
                if selected is not None:
                    target_context["selected_target"] = selected
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
    if prepared.technique is not None:
        domain.technique = prepared.technique
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
        dataset.set_extra("spectrasherpa.value_units_label", prepared.y_units or None)
    if prepared.technique is not None:
        dataset.meta["technique"] = prepared.technique
    if allow_is_time_series and prepared.is_time_series is not None:
        dataset.is_time_series = prepared.is_time_series
        dataset.meta["is_time_series"] = prepared.is_time_series
    if prepared.target_column is not None:
        properties = dataset.get_extra("properties")
        if isinstance(properties, Mapping) and prepared.target_column in properties:
            target = np.asarray(properties[prepared.target_column])
            if target.ndim != 1 or target.shape[0] != dataset.n_samples:
                raise ValueError("Prepared target column does not align with the dataset samples")
            target_type = prepared.target_type or (
                "categorical" if target.dtype.kind in {"O", "S", "U"} else "continuous"
            )
            class_names = None
            if target_type == "categorical":
                class_names = sorted(
                    {str(value).strip() for value in target.tolist() if value is not None and str(value).strip()}
                )
            dataset.target = target
            dataset.target_context = TargetContext(
                target_type=target_type,
                target_name=prepared.target_column,
                target_names=[prepared.target_column],
                selected_target=prepared.selected_target or prepared.target_column,
                n_classes=len(class_names) if class_names is not None else None,
                class_names=class_names,
            )
        dataset.meta["csv.target_column"] = prepared.target_column
    if prepared.target_type is not None:
        dataset.meta["csv.target_type"] = prepared.target_type
    if prepared.target_mode is not None:
        dataset.meta["target_mode"] = prepared.target_mode
    if prepared.selected_target is not None:
        dataset.meta["selected_target"] = prepared.selected_target
    if prepared.csv_layout is not None:
        dataset.meta["csv_layout"] = prepared.csv_layout
    if prepared.target_mode is not None or prepared.selected_target is not None:
        if prepared.target_mode == "multi":
            dataset.target_context = dataset.target_context.model_copy(update={"selected_target": None})
            dataset.meta.pop("selected_target", None)
        else:
            selected = _selected_target_from_context(dataset, prepared.selected_target)
            if selected is not None:
                dataset.target_context = dataset.target_context.model_copy(update={"selected_target": selected})
                dataset.meta["selected_target"] = selected
    return dataset


def merge_prepared_data_overrides(overrides: list[PreparedDataOverrides]) -> PreparedDataOverrides:
    merged = PreparedDataOverrides()
    for current in overrides:
        # Preserve the existing sidecar precedence contract exactly. ``y_units``
        # remains a per-dataset value rather than an arbitrary first-file
        # authority when several source files are combined.
        for name in (
            "title",
            "x_title",
            "x_units",
            "y_title",
            "technique",
            "is_time_series",
            "data_role",
            "target_column",
            "target_type",
            "target_mode",
            "selected_target",
            "csv_layout",
        ):
            if getattr(current, name) is not None and getattr(merged, name) is None:
                merged = replace(merged, **{name: getattr(current, name)})
    return merged


__all__ = [
    "PreparedDataOverrides",
    "CSV_LAYOUTS",
    "csv_layout_settings",
    "apply_dataset_prepared_data_overrides",
    "apply_serialized_prepared_data_overrides",
    "bind_explicit_target_selection",
    "merge_prepared_data_overrides",
    "parser_options_for_prepared_data",
]
