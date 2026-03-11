"""SpectroChemPy example dataset catalog and metadata.

Scans the SpectroChemPy testdata directories at runtime to build a
file-level catalog.  Each entry represents either a single loadable file
or a subdirectory group of related files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category metadata (technique labels for each top-level testdata folder)
# ---------------------------------------------------------------------------

_CATEGORY_META: dict[str, dict[str, str]] = {
    "irdata": {"technique": "FTIR", "technique_label": "IR Spectroscopy"},
    "ramandata": {"technique": "Raman", "technique_label": "Raman Spectroscopy"},
    "nmrdata": {"technique": "NMR", "technique_label": "NMR Spectroscopy"},
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
    # nmrdata nested Bruker examples
    "nmrdata/bruker/tests/nmr/topspin_1d/1": "Bruker TopSpin 1D",
    "nmrdata/bruker/tests/nmr/topspin_2d/1": "Bruker TopSpin 2D",
    "nmrdata/bruker/tests/nmr/h3po4/4": "Bruker H3PO4",
    "nmrdata/bruker/tests/nmr/cadmium/100": "Bruker Cadmium",
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

        rel = f"{category_name}/{item.relative_to(category_dir)}"
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


def build_scp_catalog(force: bool = False) -> list[dict[str, Any]]:
    """Build a file-level catalog of SpectroChemPy testdata.

    Returns a list of catalog entries, each with:
        name        unique key (e.g. "irdata/nh4y-activation.spg")
        label       human-readable label
        technique   spectral technique
        category    top-level folder (irdata, ramandata, ...)
        file_path   relative path from testdata root
        file_count  number of files (1 for single, N for group)
        entry_type  "single" or "group"
        description short description
    """
    global _catalog_cache
    if _catalog_cache is not None and not force:
        return _catalog_cache

    from spectra_sherpa.app.lib.scp_compat import get_scp_datadirs

    entries: list[dict[str, Any]] = []
    scanned = False

    for datadir in get_scp_datadirs():
        if not datadir.exists():
            continue
        scanned = True

        for category_dir in sorted(datadir.iterdir()):
            if not category_dir.is_dir():
                continue
            cat_name = category_dir.name
            if cat_name in _SKIP_CATEGORIES or cat_name.startswith((".", "_")):
                continue

            meta = _CATEGORY_META.get(cat_name, {"technique": "Various", "technique_label": cat_name})
            technique = meta["technique"]

            # Scan root-level files in the category
            root_files = []
            subdirs = []
            for item in sorted(category_dir.iterdir()):
                if item.name in _IGNORE_NAMES or item.name.startswith("."):
                    continue
                if item.is_file() and _is_spectral_file(item):
                    root_files.append(item)
                elif item.is_dir():
                    subdirs.append(item)

            # Add individual root files as entries
            for f in root_files:
                rel = f"{cat_name}/{f.name}"
                entries.append(
                    {
                        "name": rel,
                        "label": _label_for(rel, is_dir=False),
                        "technique": _TECHNIQUE_OVERRIDES.get(rel, technique),
                        "category": cat_name,
                        "file_path": rel,
                        "file_count": 1,
                        "entry_type": "single",
                        "description": f"{f.suffix.lstrip('.').upper() or 'data'} file from {meta['technique_label']}",
                    }
                )

            # Add subdirectories as group entries (or expand to individual files)
            for d in subdirs:
                fc = _count_data_files(d)
                if cat_name == "nmrdata" and fc == 0 and _contains_nested_nmr_dataset(d):
                    entries.extend(_find_nested_nmr_entries(category_dir, cat_name, meta["technique_label"]))
                    continue
                if fc == 0:
                    continue
                rel = f"{cat_name}/{d.name}"

                # Expand directories whose files are standalone datasets
                if rel in _EXPAND_AS_INDIVIDUAL:
                    for child in sorted(d.iterdir()):
                        if not child.is_file() or child.name in _IGNORE_NAMES or child.name.startswith("."):
                            continue
                        if not _is_spectral_file(child):
                            continue
                        child_rel = f"{rel}/{child.name}"
                        entries.append(
                            {
                                "name": child_rel,
                                "label": _label_for(child_rel, is_dir=False),
                                "technique": _TECHNIQUE_OVERRIDES.get(child_rel, technique),
                                "category": cat_name,
                                "file_path": child_rel,
                                "file_count": 1,
                                "entry_type": "single",
                                "description": (
                                    f"{child.suffix.lstrip('.').upper()} time-series file "
                                    f"from {meta['technique_label']}"
                                ),
                            }
                        )
                    continue

                entries.append(
                    {
                        "name": rel,
                        "label": _label_for(rel, is_dir=True, file_count=fc),
                        "technique": technique,
                        "category": cat_name,
                        "file_path": rel + "/",
                        "file_count": fc,
                        "entry_type": "group",
                        "description": f"Folder with {fc} files from {meta['technique_label']}",
                    }
                )

        # Only scan the first valid datadir (avoid duplicates)
        break

    if not scanned:
        logger.warning("No SpectroChemPy testdata directory found; using empty SCP catalog")

    _catalog_cache = entries
    return entries


# ---------------------------------------------------------------------------
# Legacy compatibility — SCP_CATALOG dict keyed by category name
# (used by builder.py get_reference_dataset_info for detail lookups)
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

    Supports both file-level keys (e.g. "irdata/nh4y-activation.spg")
    and legacy category keys (e.g. "irdata").
    """
    # Try file-level lookup first
    catalog = build_scp_catalog()
    for entry in catalog:
        if entry["name"] == name:
            return {"source": "spectrochempy", **entry}

    # Fall back to category-level lookup
    if name in SCP_CATALOG:
        return {"name": name, "source": "spectrochempy", **SCP_CATALOG[name]}

    raise ValueError(f"Unknown SCP dataset: {name!r}. " f"Available: {', '.join(e['name'] for e in catalog)}")
