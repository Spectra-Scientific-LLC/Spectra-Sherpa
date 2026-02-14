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
        "label": "Raman: LabSpec Series",
        "technique": "Raman",
        "description": (
            "Raman spectroscopy data from LabSpec instruments. "
            "Demonstrates Raman scattering analysis workflows."
        ),
    },
    "nmrdata": {
        "label": "NMR: Bruker TopSpin 1D",
        "technique": "NMR",
        "description": (
            "1D NMR spectra from Bruker TopSpin. "
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
