"""Application policy adapter for Eigenvector Research public datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.lib import eigenvector


def _runtime_data_dir() -> Path:
    return Path(settings.data_dir) / "reference_cache" / "eigenvector"


def load_eigenvector_dataset(name: str, data_dir: Path | None = None) -> dict[str, Any]:
    """Load from locally supplied files; Eigenvector data is never downloaded."""

    return eigenvector.load_eigenvector_dataset(
        name,
        data_dir=data_dir,
        runtime_data_dir=_runtime_data_dir(),
    )


def get_dataset_info(name: str, data_dir: Path | None = None) -> dict[str, Any]:
    """Describe a dataset from locally supplied files."""

    return eigenvector.get_dataset_info(
        name,
        data_dir=data_dir,
        runtime_data_dir=_runtime_data_dir(),
    )


__all__ = ["get_dataset_info", "load_eigenvector_dataset"]
