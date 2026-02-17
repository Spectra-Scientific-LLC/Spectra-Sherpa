"""SpectroChemPy example dataset catalog and metadata."""
from __future__ import annotations

from typing import Any

SCP_CATALOG: dict[str, dict[str, Any]] = {
    "irdata": {
        "label": "IR: NH4Y Zeolite Activation",
        "technique": "FTIR",
        "description": (
            "Infrared spectra of NH4Y zeolite during thermal activation. "
            "Monitors structural changes via mid-IR absorption bands."
        ),
    },
    "ramandata": {
        "label": "Raman Spectroscopy",
        "technique": "Raman",
        "description": (
            "Raman spectroscopy data from various instruments. "
            "Demonstrates Raman scattering analysis workflows."
        ),
    },
    "nmrdata": {
        "label": "NMR: Bruker TopSpin",
        "technique": "NMR",
        "description": (
            "NMR spectra from Bruker TopSpin. "
            "Demonstrates NMR processing pipelines (phasing, baseline, integration)."
        ),
    },
    "galacticdata": {
        "label": "Galactic SPC Files",
        "technique": "Various",
        "description": (
            "Legacy Galactic SPC format spectral files. "
            "Demonstrates cross-format compatibility."
        ),
    },
    "agirdata": {
        "label": "Agilent IR (AGIR)",
        "technique": "FTIR",
        "description": (
            "Agilent FTIR instrument data files. "
            "Demonstrates Agilent-format spectral I/O."
        ),
    },
    # dscdata excluded: the sole file (AEM_210311.txt) is UTF-16 encoded
    # and not parseable by spectrochempy 0.8.x readers.
    "matlabdata": {
        "label": "MATLAB Datasets",
        "technique": "Various",
        "description": (
            "Spectral data stored in MATLAB .mat format. "
            "Demonstrates MATLAB file import capabilities."
        ),
    },
    "msdata": {
        "label": "Mass Spectrometry",
        "technique": "MS",
        "description": (
            "Mass spectrometry datasets across instruments and formats. "
            "Demonstrates MS data import workflows."
        ),
    },
}


def get_scp_dataset_info(name: str) -> dict[str, Any]:
    """Get metadata for a SpectroChemPy example dataset category."""
    if name not in SCP_CATALOG:
        raise ValueError(
            f"Unknown SCP dataset: {name!r}. "
            f"Available: {', '.join(SCP_CATALOG)}"
        )

    entry = SCP_CATALOG[name]
    return {
        "name": name,
        "source": "spectrochempy",
        **entry,
    }
