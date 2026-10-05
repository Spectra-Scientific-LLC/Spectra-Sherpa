"""Builder-side file loading utilities used by the workbench."""

from __future__ import annotations

import os
from pathlib import Path

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.services.experiments import resolve_data_path


class BuilderService:
    """Resolve and load user-owned files without owning scientific synthesis."""

    def _resolve_payload_path(self, file_path: str) -> Path:
        """Resolve a file path from a payload without leaving the data root."""
        if os.path.isabs(file_path):
            path = Path(os.path.abspath(file_path))
        else:
            path = resolve_data_path(file_path)
        path = path.resolve(strict=False)
        if not path.is_relative_to(settings.data_dir):
            raise ValueError("File path must be within data directory")
        return path
