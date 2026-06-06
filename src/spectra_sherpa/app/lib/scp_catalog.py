"""SpectroChemPy example dataset catalog and metadata.

Uses a packaged manifest to expose curated SpectroChemPy testdata entries.
Each entry resolves either a single loadable file or a compatible multi-file
bundle that can be previewed and imported as one SherpaDataset.
"""

from __future__ import annotations

import json
import logging
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset
from spectra_sherpa.app.lib.domain_flags import infer_is_spectra
from spectra_sherpa.app.lib.eigenvector import build_catalog_preview
from spectra_sherpa.app.lib.sample_labels import (
    clean_sample_labels,
    normalize_time_unit,
    parse_sample_label_metadata,
    time_unit_seconds,
)
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category metadata (technique labels for each top-level testdata folder)
# ---------------------------------------------------------------------------

_CATEGORY_META: dict[str, dict[str, str]] = {
    "irdata": {"technique": "FTIR", "technique_label": "IR Spectroscopy"},
    "ramandata": {"technique": "Raman", "technique_label": "Raman Spectroscopy"},
    "galacticdata": {"technique": "Various", "technique_label": "Galactic SPC Files"},
    "agirdata": {"technique": "FTIR", "technique_label": "Agilent IR"},
    "matlabdata": {"technique": "Various", "technique_label": "MATLAB Datasets"},
    "msdata": {"technique": "MS", "technique_label": "Mass Spectrometry"},
    "dscdata": {"technique": "DSC", "technique_label": "Differential Scanning Calorimetry"},
}

# Categories to skip (known-broken or not useful)
_SKIP_CATEGORIES: set[str] = set()

# Files to ignore when scanning
_IGNORE_NAMES = {"__index__", ".DS_Store", "README.txt", "__downloaded__"}

# Recognised spectral file extensions
_SPECTRAL_EXTENSIONS = {
    ".spg",
    ".spa",
    ".spc",
    ".csv",
    ".mat",
    ".jdx",
    ".dx",
    ".txt",
    ".wdf",
    ".asc",
    ".dat",
    ".srs",
    ".opus",
    ".0",
}

# ---------------------------------------------------------------------------
# Human-readable labels for well-known files / subdirs
# ---------------------------------------------------------------------------

_KNOWN_LABELS: dict[str, str] = {
    # irdata files
    "irdata/nh4y-activation.spg": "NH4Y Zeolite Activation",
    "irdata/CO@Mo_Al2O3.SPG": "CO on Mo/Al2O3 Catalyst",
    "irdata/IR.CSV": "IR Spectrum (CSV)",
    # irdata subdirs
    "irdata/OPUS": "OPUS Format Spectra",
    "irdata/carroucell_samp": "Carousel Zeolite Samples",
    "irdata/subdir": "Pd/CZ Catalyst Series",
    "irdata/interferogram": "Interferogram Pair",
    # irdata/omnic_series individual time-series files
    "irdata/omnic_series/GC_Demo.srs": "OMNIC GC Demo Time Series",
    "irdata/omnic_series/TGA_demo.srs": "OMNIC TGA Demo Time Series",
    "irdata/omnic_series/high_speed.srs": "OMNIC High-Speed Time Series",
    "irdata/omnic_series/rapid_scan.srs": "OMNIC Rapid Scan Time Series",
    "irdata/omnic_series/rapid_scan_reprocessed.srs": "OMNIC Rapid Scan Reprocessed",
    # ramandata subdirs
    "ramandata/labspec": "LabSpec Raman",
    "ramandata/wire": "Renishaw WiRE Raman",
    # galacticdata files (use filename without extension)
    # matlabdata
    "matlabdata/als2004dataset.MAT": "ALS-2004 MCR-ALS Mixture (de Juan & Tauler)",
    # msdata
    "msdata/ion_currents.asc": "Ion Currents",
    # agirdata
    "agirdata/P350": "Agilent P350 FTIR+TGA",
}


# Per-entry technique overrides (when category technique is too generic)
_TECHNIQUE_OVERRIDES: dict[str, str] = {
    "matlabdata/als2004dataset.MAT": "FTIR",
}

# Subdirectories whose files should be listed individually rather than as
# a single group entry.  Each file inside these dirs is a standalone dataset
# (e.g. each .srs file is a complete time-resolved experiment).
_EXPAND_AS_INDIVIDUAL: set[str] = {
    "irdata/omnic_series",
}


def _label_for(rel_path: str, is_dir: bool, file_count: int = 0) -> str:
    """Generate a human-readable label for a catalog entry."""
    if rel_path in _KNOWN_LABELS:
        label = _KNOWN_LABELS[rel_path]
        if is_dir and file_count:
            label += f" ({file_count} files)"
        return label

    name = Path(rel_path).name
    if is_dir:
        suffix = f" ({file_count} files)" if file_count else ""
        return f"{name}/{suffix}"
    # For individual files, use stem as label
    return Path(name).stem.replace("_", " ")


def _count_data_files(directory: Path) -> int:
    """Count spectral data files in a directory (non-recursive)."""
    count = 0
    for item in directory.iterdir():
        if item.is_file() and item.name not in _IGNORE_NAMES:
            count += 1
    return count


def _contains_nested_nmr_dataset(directory: Path) -> bool:
    """Return True when a directory tree contains Bruker-style NMR data."""
    for item in directory.rglob("*"):
        if not item.is_dir():
            continue
        if (item / "fid").exists() or (item / "ser").exists():
            return True
    return False


def _find_nested_nmr_entries(category_dir: Path, category_name: str, technique_label: str) -> list[dict[str, Any]]:
    """Discover nested Bruker NMR experiments as explicit catalog entries."""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in sorted(category_dir.rglob("*")):
        if not item.is_dir():
            continue
        if not ((item / "fid").exists() or (item / "ser").exists()):
            continue

        # Always emit POSIX-style separators so the catalog ``name`` field is
        # stable across operating systems (Windows ``rglob`` returns paths
        # with ``\`` separators).
        rel = f"{category_name}/{item.relative_to(category_dir).as_posix()}"
        if rel in seen:
            continue
        seen.add(rel)

        entries.append(
            {
                "name": rel,
                "label": _label_for(rel, is_dir=True),
                "technique": "NMR",
                "category": category_name,
                "file_path": rel + "/",
                "file_count": 1,
                "entry_type": "group",
                "description": f"Bruker NMR directory from {technique_label}",
            }
        )

    return entries


def _is_spectral_file(path: Path) -> bool:
    """Check if a file has a recognised spectral extension."""
    ext = path.suffix.lower()
    if ext in _SPECTRAL_EXTENSIONS:
        return True
    # Also accept extensionless files that look like OPUS numbered files
    if not ext and path.name.replace(".", "").isdigit():
        return True
    return False


# ---------------------------------------------------------------------------
# Catalog builder
# ---------------------------------------------------------------------------

_catalog_cache: list[dict[str, Any]] | None = None
_manifest_cache: dict[str, Any] | None = None


def _load_scp_manifest() -> dict[str, Any]:
    global _manifest_cache
    if _manifest_cache is None:
        text = resources.files("spectra_sherpa").joinpath("data/scp_reference_catalog.json").read_text()
        _manifest_cache = dict(json.loads(text))
    return _manifest_cache


def _manifest_entries() -> list[dict[str, Any]]:
    return [dict(entry) for entry in _load_scp_manifest().get("entries", []) if not entry.get("hidden")]


def _importable_manifest_entries() -> list[dict[str, Any]]:
    return [entry for entry in _manifest_entries() if entry.get("importable", True)]


def _entry_matches(entry: dict[str, Any], name: str) -> bool:
    return entry.get("name") == name or name in set(entry.get("aliases") or [])


def get_scp_catalog_entry(name: str) -> dict[str, Any]:
    """Return a curated SCP catalog entry by public name or alias."""
    for entry in _importable_manifest_entries():
        if _entry_matches(entry, name):
            return entry
    available = ", ".join(e["name"] for e in _importable_manifest_entries())
    raise ValueError(f"Unknown SCP dataset: {name!r}. Available: {available}")


def _expand_entry_files(entry: dict[str, Any], datadir: Path | None = None) -> list[Path]:
    """Resolve the curated manifest paths for one SCP entry."""
    if datadir is None:
        from spectra_sherpa.app.lib.scp_compat import get_preferred_scp_datadir

        datadir = get_preferred_scp_datadir()
    if datadir is None:
        return []

    files: list[Path] = []
    for rel in entry.get("files") or []:
        path = datadir / str(rel)
        if path.is_file():
            files.append(path)

    folder = entry.get("folder")
    patterns = entry.get("patterns") or []
    if folder and patterns:
        root = datadir / str(folder)
        if root.is_dir():
            for pattern in patterns:
                files.extend(path for path in sorted(root.glob(str(pattern))) if path.is_file())

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def _axis_values(dataset: SherpaDataset) -> np.ndarray | None:
    feature_axis = dataset.get_feature_axis()
    values = getattr(feature_axis, "values", None) if feature_axis is not None else None
    if values is None:
        return None
    arr = np.asarray(values, dtype=float)
    return arr.reshape(-1) if arr.ndim else arr.reshape(1)


def _axis_labels(dataset: SherpaDataset) -> list[str] | None:
    feature_axis = dataset.get_feature_axis()
    labels = getattr(feature_axis, "labels", None) if feature_axis is not None else None
    if labels is None:
        return None
    return [str(label) for label in labels]


def _axis_units(dataset: SherpaDataset) -> str:
    feature_axis = dataset.get_feature_axis()
    units = getattr(feature_axis, "units", None) if feature_axis is not None else None
    return str(units or "")


def _feature_axes_compatible(reference: SherpaDataset, candidate: SherpaDataset) -> bool:
    """Return True only when datasets can be stacked without regridding."""
    if candidate.n_features != reference.n_features:
        return False
    if _axis_units(candidate) != _axis_units(reference):
        return False

    ref_values = _axis_values(reference)
    cand_values = _axis_values(candidate)
    if ref_values is not None or cand_values is not None:
        if ref_values is None or cand_values is None:
            return False
        return bool(
            ref_values.shape == cand_values.shape
            and np.allclose(ref_values, cand_values, rtol=1e-8, atol=1e-10, equal_nan=True)
        )

    ref_labels = _axis_labels(reference)
    cand_labels = _axis_labels(candidate)
    if ref_labels is not None or cand_labels is not None:
        return ref_labels == cand_labels

    return True


def _axis_summary(dataset: SherpaDataset) -> str:
    values = _axis_values(dataset)
    if values is not None and values.size:
        units = _axis_units(dataset) or "no units"
        return f"{dataset.n_features} features, {units}, {values[0]:.6g} to {values[-1]:.6g}"
    labels = _axis_labels(dataset)
    if labels:
        return f"{dataset.n_features} labels, {_axis_units(dataset) or 'no units'}"
    return f"{dataset.n_features} features, {_axis_units(dataset) or 'no units'}"


def _sample_labels(dataset: SherpaDataset, file_path: Path) -> list[str]:
    axis = dataset.sample_axis
    labels = list(axis.labels) if axis is not None and axis.labels else []
    if len(labels) == dataset.n_samples:
        return clean_sample_labels(
            labels, dataset.n_samples, fallback_prefix=file_path.stem, source_name=file_path.stem
        )
    if dataset.n_samples == 1:
        return clean_sample_labels([dataset.title or file_path.stem], 1, fallback_prefix=file_path.stem)
    return clean_sample_labels(None, dataset.n_samples, fallback_prefix="Sample")


def _sample_table(dataset: SherpaDataset, file_path: Path) -> dict[str, list[Any]]:
    raw_labels = (
        list(dataset.sample_axis.labels) if dataset.sample_axis is not None and dataset.sample_axis.labels else []
    )
    if len(raw_labels) != dataset.n_samples:
        raw_labels = [dataset.title or file_path.stem] if dataset.n_samples == 1 else [""] * dataset.n_samples

    rows: list[dict[str, Any]] = []
    for raw_label in raw_labels:
        row = parse_sample_label_metadata(raw_label)
        row.setdefault("source_file", file_path.name)
        row.setdefault("source_path", str(file_path))
        rows.append(row)

    keys = sorted({key for row in rows for key in row})
    return {key: [row.get(key) for row in rows] for key in keys}


def _sample_time_axis(sample_table: dict[str, list[Any]], n_rows: int) -> tuple[np.ndarray | None, str | None]:
    values = sample_table.get("time_value")
    units = sample_table.get("time_units")
    if not values or not units or len(values) != n_rows or len(units) != n_rows:
        return None, None

    numeric_values: list[float] = []
    normalized_units: list[str] = []
    for value, unit in zip(values, units, strict=True):
        normalized = normalize_time_unit(unit)
        if value is None or normalized is None:
            return None, None
        try:
            numeric_values.append(float(value))
        except (TypeError, ValueError):
            return None, None
        normalized_units.append(normalized)

    unique_units = set(normalized_units)
    if len(unique_units) == 1:
        return np.asarray(numeric_values, dtype=np.float64), normalized_units[0]

    converted: list[float] = []
    for value, unit in zip(numeric_values, normalized_units, strict=True):
        scale = time_unit_seconds(unit)
        if scale is None:
            return None, None
        converted.append(value * scale)
    return np.asarray(converted, dtype=np.float64), "s"


def _candidate_score(dataset: SherpaDataset) -> tuple[int, int, int]:
    X = np.asarray(dataset.X)
    if np.iscomplexobj(X):
        return (-1, 0, 0)
    if X.ndim == 2:
        return (2, int(dataset.n_samples), int(dataset.n_samples * dataset.n_features))
    if X.ndim == 1:
        return (1, 1, int(dataset.n_features))
    return (0, 0, 0)


def _select_primary_dataset(candidates: list[SherpaDataset]) -> SherpaDataset | None:
    """Select the primary matrix when one SCP file contains several objects."""
    scored = [(score, dataset) for dataset in candidates if (score := _candidate_score(dataset))[0] > 0]
    if not scored:
        return None
    return max(scored, key=lambda item: item[0])[1]


def _concat_compatible_sherpa(datasets: list[tuple[SherpaDataset, Path]], *, title: str) -> SherpaDataset:
    """Concatenate loaded SCP datasets along the sample axis.

    Curated SCP bundles are only valid when every member shares the same full
    feature axis. Fail loudly on incompatibility instead of silently dropping or
    misaligning records.
    """
    if not datasets:
        raise ValueError("No loadable spectra found in SCP dataset")

    normalized: list[tuple[SherpaDataset, Path]] = []
    for dataset, path in datasets:
        X = np.asarray(dataset.X)
        if X.ndim == 1:
            X = X.reshape(1, -1)
            dataset = SherpaDataset(
                X,
                feature_axis=dataset.get_feature_axis(),
                sample_axis=dataset.sample_axis,
                domain=dataset.domain,
                provenance=dataset.provenance,
                quality=dataset.quality,
                backend=dataset.backend,
                title=dataset.title,
                units=dataset.units,
                is_time_series=dataset.is_time_series,
                data_role=dataset.data_role,
            )
        if np.asarray(dataset.X).ndim != 2:
            continue
        normalized.append((dataset, path))

    if not normalized:
        raise ValueError("SCP dataset did not contain a 2D matrix-compatible spectrum")

    first, first_path = normalized[0]
    for dataset, path in normalized[1:]:
        if not _feature_axes_compatible(first, dataset):
            raise ValueError(
                "SCP bundle contains incompatible feature axes and cannot be stacked without regridding: "
                f"{first_path.name} ({_axis_summary(first)}) vs {path.name} ({_axis_summary(dataset)})"
            )

    rows: list[np.ndarray] = []
    labels: list[str] = []
    sample_table_parts: dict[str, list[Any]] = {}
    for dataset, path in normalized:
        rows.append(np.asarray(dataset.X, dtype=np.float64).reshape(dataset.n_samples, dataset.n_features))
        labels.extend(_sample_labels(dataset, path))
        table = _sample_table(dataset, path)
        for key, values in table.items():
            sample_table_parts.setdefault(key, []).extend(values)

    n_rows = sum(
        np.asarray(dataset.X).reshape(dataset.n_samples, dataset.n_features).shape[0] for dataset, _ in normalized
    )
    labels = clean_sample_labels(labels, n_rows, fallback_prefix="Sample")
    sample_table = {
        key: values
        for key, values in sample_table_parts.items()
        if len(values) == n_rows and any(v is not None for v in values)
    }

    sample_values, sample_units = _sample_time_axis(sample_table, n_rows)
    sample_title = "Time" if sample_values is not None else "Samples"

    return SherpaDataset(
        np.vstack(rows),
        feature_axis=first.get_feature_axis(),
        sample_axis=SampleAxis(
            values=sample_values,
            labels=labels,
            units=sample_units,
            title=sample_title,
            sample_table=sample_table or None,
        ),
        domain=first.domain,
        provenance=first.provenance,
        quality=first.quality,
        backend="scp",
        title=title,
        units=first.units,
        is_time_series=first.is_time_series,
        data_role="X_spectra",
    )


def load_scp_reference_as_sherpa(name: str) -> SherpaDataset:
    """Load a curated SCP catalog entry into one SherpaDataset."""
    from spectra_sherpa.app.lib.scp_compat import require_scp, scp

    require_scp("SpectroChemPy reference import")
    entry = get_scp_catalog_entry(name)
    files = _expand_entry_files(entry)
    if not files:
        raise FileNotFoundError(f"SCP dataset files not found: {name}")

    loaded: list[tuple[SherpaDataset, Path]] = []
    for path in files:
        try:
            raw = scp.read(str(path))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipping unreadable SCP catalog file %s: %s", path, exc)
            continue
        candidates: list[Any]
        if hasattr(raw, "data"):
            candidates = [raw]
        else:
            try:
                candidates = [item for item in raw if hasattr(item, "data")]
            except TypeError:
                candidates = []
        converted: list[SherpaDataset] = []
        for candidate in candidates:
            try:
                dataset = from_nddataset(candidate)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Skipping non-convertible SCP dataset from %s: %s", path, exc)
                continue
            converted.append(dataset)
        selected = _select_primary_dataset(converted)
        if selected is not None:
            loaded.append((selected, path))

    return _concat_compatible_sherpa(loaded, title=str(entry.get("label") or entry["name"]))


def build_scp_catalog(force: bool = False) -> list[dict[str, Any]]:
    """Build the curated SpectroChemPy reference catalog.

    Returns a list of catalog entries, each with:
        name        unique key (e.g. "irdata/nh4y-activation.spg")
        label       human-readable label
        technique   spectral technique
        category    top-level folder (irdata, ramandata, ...)
        file_path   representative relative path from testdata root
        file_count  number of files (1 for single, N for group)
        entry_type  "single" or "group"
        description short description
    """
    global _catalog_cache
    if _catalog_cache is not None and not force:
        return _catalog_cache

    from spectra_sherpa.app.lib.scp_compat import get_preferred_scp_datadir

    entries: list[dict[str, Any]] = []
    datadir = get_preferred_scp_datadir()

    if datadir is None:
        logger.warning("No SpectroChemPy testdata directory found; using empty SCP catalog")
        _catalog_cache = entries
        return entries

    for entry in _importable_manifest_entries():
        files = _expand_entry_files(entry, datadir)
        if not files:
            continue
        public = {
            "name": entry["name"],
            "label": entry["label"],
            "technique": entry["technique"],
            "category": entry["category"],
            "file_path": str(entry.get("folder") or entry.get("files", [entry["name"]])[0]),
            "files": [path.relative_to(datadir).as_posix() for path in files],
            "file_count": len(files),
            "entry_type": entry.get("entry_type", "single"),
            "description": entry["description"],
            "axis_policy": entry.get("axis_policy"),
            "x_title": entry.get("x_title"),
            "x_units": entry.get("x_units"),
        }
        entries.append(public)

    _catalog_cache = entries
    return entries


# ---------------------------------------------------------------------------
# Legacy compatibility — SCP_CATALOG dict keyed by category name.
# ---------------------------------------------------------------------------

# Keep a minimal static fallback for the old category-level API
SCP_CATALOG: dict[str, dict[str, Any]] = {
    cat: {
        "label": meta["technique_label"],
        "technique": meta["technique"],
        "description": f"{meta['technique_label']} example datasets from SpectroChemPy testdata.",
    }
    for cat, meta in _CATEGORY_META.items()
}


def get_scp_dataset_info(name: str) -> dict[str, Any]:
    """Get metadata for a SpectroChemPy dataset.

    Supports curated bundle keys and legacy aliases (e.g. ``irdata`` and
    ``ramandata``) defined in ``data/scp_reference_catalog.json``.
    """
    entry = get_scp_catalog_entry(name)
    files = _expand_entry_files(entry)
    info: dict[str, Any] = {
        "name": entry["name"],
        "source": "spectrochempy",
        "is_spectra": infer_is_spectra(technique=entry.get("technique")),
        "label": entry["label"],
        "technique": entry["technique"],
        "category": entry["category"],
        "description": entry["description"],
        "file_path": str(entry.get("folder") or entry.get("files", [entry["name"]])[0]),
        "file_count": len(files),
        "entry_type": entry.get("entry_type", "single"),
        "axis_policy": entry.get("axis_policy"),
        "x_title": entry.get("x_title"),
        "x_units": entry.get("x_units"),
        "has_embedded_target": False,
        "target_type": None,
    }
    if not files:
        info["file_count"] = 0
        return info

    try:
        dataset = load_scp_reference_as_sherpa(name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("SCP detail preview failed for %s: %s", name, exc)
        return info

    X = np.asarray(dataset.X, dtype=float)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    info["n_samples"] = int(X.shape[0])
    info["n_features"] = int(X.shape[1])
    feature_axis = dataset.get_feature_axis()
    values = getattr(feature_axis, "values", None) if feature_axis is not None else None
    if values is not None:
        info["wavelengths"] = np.asarray(values, dtype=float).tolist()
    if feature_axis is not None:
        info["x_title"] = getattr(feature_axis, "title", None) or info.get("x_title")
        info["x_units"] = getattr(feature_axis, "units", None) or info.get("x_units")
    finite = X[np.isfinite(X)]
    if finite.size:
        info["data_min"] = float(np.min(finite))
        info["data_max"] = float(np.max(finite))
        info["data_mean"] = float(np.mean(finite))
    preview = build_catalog_preview(X, np.asarray(values, dtype=float) if values is not None else None)
    info["preview_spectra"] = preview["spectra"]
    if "wavelengths" in preview:
        info["wavelengths"] = preview["wavelengths"]
    return info
