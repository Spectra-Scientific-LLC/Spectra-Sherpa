from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT = REPO_ROOT / "docs" / "evidence" / "unified-matlab-dso-qualification.json"
TOOL = REPO_ROOT / "tools" / "qualify_unified_matlab_dso.py"


def test_checked_unified_matlab_dso_qualification_is_current_and_bounded() -> None:
    subprocess.run([sys.executable, str(TOOL), "--check"], cwd=REPO_ROOT, check=True)

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["schema_version"] == "spectrasherpa-unified-matlab-dso-qualification/1"
    assert report["execution"]["shape"] == [2, 3, 4]
    assert report["execution"]["v5_equals_v73_science"] is True
    assert report["execution"]["spectrochempy_loaded_after"] is False
    assert report["execution"]["target_absent"] is True
    assert report["compatibility_boundary"] == {
        "current_wire": "SherpaDataset/3.0",
        "retired_wire_versions": ["versionless", "1.0", "2.0"],
        "retired_artifact_policy": "explicit_refusal_and_source_reimport",
        "compatibility_adapter_present": False,
    }
    assert "a genuine vendor-produced MATLAB v7.3 PLS_Toolbox DSO fixture" in report["nonclaims"]
    assert all("/Users/" not in value for value in _text_values(report))

    authority = report["implementation"]["source_files"]
    for relative, receipt in authority.items():
        payload = (REPO_ROOT / relative).read_bytes()
        assert len(payload) == receipt["size_bytes"]
        assert hashlib.sha256(payload).hexdigest() == receipt["sha256"]


def test_checked_qualification_does_not_require_historical_git_objects() -> None:
    env = dict(os.environ)
    env["PATH"] = ""
    subprocess.run(
        [sys.executable, str(TOOL), "--check"],
        cwd=REPO_ROOT,
        check=True,
        env=env,
    )


def _text_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _text_values(item)
    elif isinstance(value, str):
        yield value
