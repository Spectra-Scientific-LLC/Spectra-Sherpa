"""The public snapshot comes from OSS alone, in a disposable profile."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_openapi_is_current_without_starting_user_profile(tmp_path):
    profile = tmp_path / "must-not-be-created"
    env = {
        **os.environ,
        "APP_MODE": "enterprise",
        "SITE_PROFILE": "demo",
        "DATA_DIR": str(profile),
        "DATABASE_URL": "postgresql+asyncpg://invalid:invalid@invalid/invalid",
        "PYTHONPATH": str(ROOT / "src"),
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/dump_openapi.py"), "--check"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not profile.exists()


def test_public_snapshot_covers_consumers_but_not_private_routes():
    schema = json.loads((ROOT / "frontend/contracts/openapi-v1.json").read_text(encoding="utf-8"))
    paths = schema["paths"]
    for path in ("/api/v1/workflows", "/api/v1/experiments", "/api/v1/runs", "/api/v1/deploy/watches"):
        assert path in paths
    for path in paths:
        assert not any(part in path for part in ("/optimize/", "/billing/", "/campaigns/", "/admin/"))
    # These stable references drive generated transport types, not UI behavior.
    for name in ("WorkflowDetail", "ExperimentFileOut", "ExecutionRunOut", "FolderWatchOut"):
        assert name in schema["components"]["schemas"]


def test_openapi_check_refuses_stale_file_without_overwriting_it(tmp_path):
    target = tmp_path / "contract.json"
    target.write_text('{"stale":true}\n', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/dump_openapi.py"), "--check", "--output", str(target)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 1
    assert "make generate" in result.stderr
    assert target.read_text(encoding="utf-8") == '{"stale":true}\n'
