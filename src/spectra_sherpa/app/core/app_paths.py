from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return cleaned or "workflow"


@dataclass(frozen=True)
class AppDataPaths:
    """Canonical layout for app-owned state and generated outputs."""

    root: Path
    database: Path
    startup_lock: Path
    secret_key: Path
    experiments_dir: Path
    calibrations_dir: Path
    user_dir: Path
    references_dir: Path
    spectrochempy_reference_pdf: Path
    nist_library_dir: Path
    nist_downloads_dir: Path
    exports_dir: Path
    python_exports_dir: Path
    jupyter_exports_dir: Path
    llm_dialogs_dir: Path
    llm_conversations_state: Path
    rate_limits_dir: Path
    llm_rate_limits_state: Path
    execution_rate_limits_state: Path
    demo_dir: Path
    demo_limits_state: Path

    def auth_rate_limit_state(self, scope: str) -> Path:
        return self.rate_limits_dir / f"auth_{scope}.json"

    def workflow_python_export_path(self, workflow_id: int, workflow_name: str) -> Path:
        slug = _slugify(workflow_name)
        return self.python_exports_dir / f"workflow_{workflow_id}_{slug}.py"

    def workflow_jupyter_export_path(self, workflow_id: int, workflow_name: str) -> Path:
        slug = _slugify(workflow_name)
        return self.jupyter_exports_dir / f"workflow_{workflow_id}_{slug}.ipynb"


def get_app_data_paths(root: Path) -> AppDataPaths:
    root = root.expanduser().resolve()
    references_dir = root / "references"
    exports_dir = root / "exports"
    rate_limits_dir = root / "rate_limits"
    demo_dir = root / "demo"
    llm_dialogs_dir = root / "llm_dialogs"
    nist_library_dir = root / "nist_library"

    return AppDataPaths(
        root=root,
        database=root / "spectra_platform.db",
        startup_lock=root / ".startup.lock",
        secret_key=root / ".secret_key",
        experiments_dir=root / "experiments",
        calibrations_dir=root / "calibrations",
        user_dir=root / "user",
        references_dir=references_dir,
        spectrochempy_reference_pdf=references_dir / "spectrochempy_testdata_reference.pdf",
        nist_library_dir=nist_library_dir,
        nist_downloads_dir=nist_library_dir / "downloaded",
        exports_dir=exports_dir,
        python_exports_dir=exports_dir / "python",
        jupyter_exports_dir=exports_dir / "jupyter",
        llm_dialogs_dir=llm_dialogs_dir,
        llm_conversations_state=llm_dialogs_dir / "conversations.json",
        rate_limits_dir=rate_limits_dir,
        llm_rate_limits_state=rate_limits_dir / "llm.json",
        execution_rate_limits_state=rate_limits_dir / "execution.json",
        demo_dir=demo_dir,
        demo_limits_state=demo_dir / "limits.json",
    )
