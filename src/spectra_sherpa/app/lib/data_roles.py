"""Canonical data roles and modalities for Spectra Sherpa datasets.

The application distinguishes the physical shape of an X block from its
algorithmic type. A two-dimensional matrix can be either an ordered spectrum
(``X_spectra``) or an unordered feature table (``X_features``); HSI is reserved
as the third first-class role.
"""

from __future__ import annotations

from typing import Any, Literal

DataRole = Literal["X_spectra", "X_features", "X_hsi"]
DataModality = Literal["spectra", "features", "hsi"]

DATA_ROLES: tuple[DataRole, ...] = ("X_spectra", "X_features", "X_hsi")
DATA_MODALITIES: tuple[DataModality, ...] = ("spectra", "features", "hsi")

ROLE_TO_MODALITY: dict[DataRole, DataModality] = {
    "X_spectra": "spectra",
    "X_features": "features",
    "X_hsi": "hsi",
}

MODALITY_TO_ROLE: dict[DataModality, DataRole] = {
    "spectra": "X_spectra",
    "features": "X_features",
    "hsi": "X_hsi",
}


SPECTRUM_ONLY_NODE_TYPES: frozenset[str] = frozenset(
    {
        "analysis.peak_finding",
        "baseline.penalized_ls",
        "baseline.rubberband",
        "preprocess.cosmic_ray",
        "preprocess.derivative",
        "preprocess.emsc",
        "preprocess.smooth",
        "preprocess.wavenumber_align",
        "model.efa",
        "model.mcr_als",
        "model.simplisma",
        "transfer.pds",
        "transfer.sbc",
    }
)


def normalize_data_role(value: Any, *, default: DataRole = "X_spectra") -> DataRole:
    """Return a canonical data role or ``default`` for missing values."""
    if value is None:
        return default
    text = str(value).strip()
    if text in DATA_ROLES:
        return text  # type: ignore[return-value]
    if text in DATA_MODALITIES:
        return MODALITY_TO_ROLE[text]  # type: ignore[index]
    raise ValueError(f"Unsupported data role: {value!r}. Expected one of {', '.join(DATA_ROLES)}.")


def normalize_modalities(value: Any, *, default: tuple[DataModality, ...] = ("spectra",)) -> list[DataModality]:
    """Normalize template modality metadata to a unique ordered list."""
    if value is None:
        raw_items: list[Any] = list(default)
    elif isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raise ValueError("data_modalities must be a string or a list of strings")

    normalized: list[DataModality] = []
    for item in raw_items:
        role = normalize_data_role(item)
        modality = ROLE_TO_MODALITY[role]
        if modality not in normalized:
            normalized.append(modality)
    return normalized


def data_role_to_modality(role: Any) -> DataModality:
    return ROLE_TO_MODALITY[normalize_data_role(role)]


def get_dataset_data_role(dataset: Any) -> DataRole | None:
    """Best-effort extraction of a dataset role from Sherpa/SCP-like objects."""
    role = getattr(dataset, "data_role", None)
    if role:
        return normalize_data_role(role)

    extra = getattr(dataset, "extra", None) or getattr(dataset, "meta", None)
    if isinstance(extra, dict):
        for key in ("sherpa.data_role", "scp.sherpa.data_role", "data_role", "data_modality"):
            if extra.get(key):
                return normalize_data_role(extra[key])

    # Legacy dataset objects without role metadata are treated
    # as spectra to preserve existing workflows until individual sources assert
    # a more specific role.
    if hasattr(dataset, "shape") or hasattr(dataset, "data"):
        return "X_spectra"
    return None


def is_spectrum_only_node(node_type: str, parameters: dict[str, Any] | None = None) -> bool:
    """Whether a node needs an ordered spectral axis instead of feature columns."""
    if node_type in SPECTRUM_ONLY_NODE_TYPES:
        return True
    if node_type == "preprocess.normalize":
        method = str((parameters or {}).get("method") or "").lower()
        return method in {"snv", "msc"}
    if node_type == "preprocess.clip_range":
        return True
    return False


def require_data_role(dataset: Any, accepted_roles: list[str] | tuple[str, ...], *, context: str) -> None:
    role = get_dataset_data_role(dataset)
    if role is None:
        return
    accepted = [normalize_data_role(item) for item in accepted_roles]
    if role not in accepted:
        expected = ", ".join(accepted)
        raise ValueError(f"{context} requires {expected} input; received {role}.")
