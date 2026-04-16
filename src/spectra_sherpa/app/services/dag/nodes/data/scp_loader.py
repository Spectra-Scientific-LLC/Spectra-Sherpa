"""
SCPLoader - SpectroChemPy example dataset loader.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base_loader import BaseLoader
from spectra_sherpa.app.lib.scp_compat import (
    require_scp,
    scp,
    _SCP_KNOWN_DEFAULTS,
    get_scp_datadirs,
    resolve_scp_path,
    _normalize_scp_read_output,
    _try_load_first_file,
)


class SCPLoader(BaseLoader):
    """SpectroChemPy example dataset loader."""

    async def load_raw(self) -> Any:
        """Load raw data from SpectroChemPy example dataset."""
        require_scp("SpectroChemPy example datasets")
        
        example_name = self.context.parameters.get("example_dataset", "irdata")
        example_file = self.context.parameters.get("example_file", "")
        
        # If a specific file is requested, load it directly.
        if example_file:
            full_file_path = f"{example_name}/{example_file}" if "/" not in example_file else example_file
            return self._load_custom_file(full_file_path)

        # Try known, verified defaults first.
        if example_name in _SCP_KNOWN_DEFAULTS:
            rel_path, reader_name = _SCP_KNOWN_DEFAULTS[example_name]
            resolved = resolve_scp_path(rel_path)
            if resolved is not None:
                reader_fn = getattr(scp, reader_name, None)
                if callable(reader_fn):
                    try:
                        dataset = _normalize_scp_read_output(reader_fn(str(resolved)))
                    except Exception:
                        dataset = None
                    if dataset is not None:
                        return dataset

        # Generic fallback: first loadable file in dataset folder.
        for datadir in get_scp_datadirs():
            folder = datadir / example_name
            if not folder.exists() or not folder.is_dir():
                continue
            dataset = _try_load_first_file(folder)
            if dataset is not None:
                return dataset

        raise ValueError(
            f"No loadable files found for '{example_name}'.\n"
            "Ensure SpectroChemPy data is downloaded:\n"
            '  python -c "from spectra_sherpa.app.lib.scp_compat import download_testdata; download_testdata()"'
        )
    
    def _load_custom_file(self, file_path: str) -> Any:
        """Load a custom file from the SpectroChemPy data directory."""
        requested_path = Path(file_path).expanduser()
        candidate_paths = []

        if requested_path.is_absolute():
            candidate_paths.append(requested_path)
        else:
            candidate_paths.extend(datadir / file_path for datadir in get_scp_datadirs())

        full_path = next((path for path in candidate_paths if path.exists()), None)
        if full_path is None:
            attempted = "\n".join(f"  - {path}" for path in candidate_paths)
            raise ValueError(
                f"File not found: {file_path}\n"
                f"Attempted paths:\n{attempted}\n"
                "Please verify the file exists in the SpectroChemPy data directory."
            )

        try:
            # For directories (Bruker NMR format), read the directory
            if full_path.is_dir():
                dataset = _normalize_scp_read_output(scp.read(str(full_path)))
                if dataset is None:
                    raise ValueError(f"Could not read directory: {full_path}")
                return dataset
            
            # For files, use appropriate reader
            return _normalize_scp_read_output(scp.read(str(full_path)))
        except Exception as e:
            raise ValueError(
                f"Failed to load SpectroChemPy file {file_path}: {str(e)}"
            ) from e