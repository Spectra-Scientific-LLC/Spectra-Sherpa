from __future__ import annotations

import json
from types import SimpleNamespace

from spectra_sherpa.app.core.app_paths import get_app_data_paths


def test_app_data_paths_define_export_and_dialog_subdirectories(tmp_path) -> None:
    paths = get_app_data_paths(tmp_path)

    assert paths.python_exports_dir == tmp_path / "exports" / "python"
    assert paths.jupyter_exports_dir == tmp_path / "exports" / "jupyter"
    assert paths.llm_conversations_state == tmp_path / "llm_dialogs" / "conversations.json"
    assert paths.llm_rate_limits_state == tmp_path / "rate_limits" / "llm.json"


def test_export_store_saves_python_and_jupyter_exports(monkeypatch, tmp_path) -> None:
    import spectra_sherpa.app.services.export_store as export_store

    monkeypatch.setattr(export_store, "settings", SimpleNamespace(data_dir=tmp_path))

    python_path = export_store.save_python_workflow_export(7, "IR Workflow", "print('ok')\n")
    notebook_path = export_store.save_jupyter_workflow_export(7, "IR Workflow", {"nbformat": 4, "cells": []})

    assert python_path == tmp_path / "exports" / "python" / "workflow_7_ir_workflow.py"
    assert python_path.read_text(encoding="utf-8") == "print('ok')\n"

    assert notebook_path == tmp_path / "exports" / "jupyter" / "workflow_7_ir_workflow.ipynb"
    assert json.loads(notebook_path.read_text(encoding="utf-8"))["nbformat"] == 4
