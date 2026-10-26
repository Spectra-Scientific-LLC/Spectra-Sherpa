"""Generate original, redistributable spectral acceptance data (not provider data).

These tiny mixtures exercise the Lavender/Corn presentation failure modes. They
do not reproduce either provider dataset and must never be reported as doing so.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis  # noqa: E402
from spectra_sherpa.app.lib.export_artifact import build_export_artifact  # noqa: E402
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, TargetContext  # noqa: E402


def generate(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, technique, units, axis in (
        ("mixture-ir", "FTIR", "cm^-1", np.linspace(1800, 900, 13)),
        ("moisture-nir", "NIR", "nm", np.linspace(1100, 2300, 13)),
    ):
        # Distinct dimensions and asymmetric peaks make a transposition visible.
        n = 24
        component = np.array([[0.1 + np.exp(-(((j - peak) / 1.6) ** 2)) for j in range(13)] for peak in (2, 6, 10)])
        weights = np.array([[1 + i / 24, 0.4 + (i % 5) / 5, 0.2 + (i % 7) / 7] for i in range(n)])
        values = weights @ component
        labels = [f"{name}-{i + 1:02d}" for i in range(n)]
        mask = [i not in {1, 22} for i in range(n)]
        response = 8 + weights[:, 0] * 2 + weights[:, 1] * 0.7
        dataset = SherpaDataset(
            X=values,
            sample_axis=SampleAxis(
                labels=labels,
                sample_table={"sample_id": labels},
                include_mask=mask,
                exclusion_reasons=[None if included else "Acceptance exclusion" for included in mask],
            ),
            feature_axis=SpectralAxis(
                values=axis, units=units, title="Wavenumber" if technique == "FTIR" else "Wavelength"
            ),
            target=response if name == "moisture-nir" else None,
            target_context=(
                TargetContext(
                    target_type="continuous", target_name="Moisture", target_names=["Moisture"], target_units="wt %"
                )
                if name == "moisture-nir"
                else None
            ),
            domain=DomainContext(technique=technique),
            title=f"Synthetic acceptance {name}",
            units="absorbance",
            data_role="X_spectra",
        )
        artifact = build_export_artifact(dataset, filename=f"{name}.csv", format="portable_csv")
        (destination / f"{name}.csv").write_text(str(artifact["content"]), encoding="utf-8")
        expected = {
            "provenance": "Original deterministic synthetic mixture; not Lavender or Corn provider data",
            "labels": labels,
            "included": mask,
            "axis": axis.tolist(),
            "axis_units": units,
            "values": values.tolist(),
            "target": response.tolist() if name == "moisture-nir" else None,
            "target_units": "wt %" if name == "moisture-nir" else None,
        }
        (destination / f"{name}.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    generate(ROOT / "frontend/e2e/scientific/fixtures")
