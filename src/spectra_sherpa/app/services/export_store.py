from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spectra_sherpa.app.core.app_paths import get_app_data_paths
from spectra_sherpa.app.core.config import settings


def save_python_workflow_export(workflow_id: int, workflow_name: str, python_code: str) -> Path:
    """Persist a workflow Python export under the app data directory."""
    path = get_app_data_paths(settings.data_dir).workflow_python_export_path(workflow_id, workflow_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(python_code, encoding="utf-8")
    return path


def save_jupyter_workflow_export(workflow_id: int, workflow_name: str, notebook: dict[str, Any]) -> Path:
    """Persist a workflow Jupyter export under the app data directory."""
    path = get_app_data_paths(settings.data_dir).workflow_jupyter_export_path(workflow_id, workflow_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")
    return path
