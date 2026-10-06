from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "contributor_node.py"
    spec = importlib.util.spec_from_file_location("contributor_node_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_assigns_real_scientific_evidence_to_pca(monorepo_root: Path) -> None:
    module = _load_module()
    row = module._manifest_row("model.pca")
    assert row is not None
    assert row["node_type"] == "model.pca"
    assert {Path(entry["path"]).name for entry in row["evidence_files"]} == {
        "test_c2_pca_contract.py",
        "test_phase1c_consumer_projects.py",
        "test_canonical_model_artifact_lifecycle.py",
    }


def test_unknown_node_names_the_canonical_dotted_syntax() -> None:
    module = _load_module()
    with pytest.raises(SystemExit, match=r"NODE=model\.pca or NODE=preprocess\.normalize"):
        module._require_node("not.a.node")


def test_qualify_dispatches_to_retained_authorities_after_focused_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    events: list[object] = []
    monkeypatch.setattr(module, "_require_node", lambda node_type: events.append(("node", node_type)))
    monkeypatch.setattr(module, "run_tests", lambda node_type: events.append(("tests", node_type)))
    monkeypatch.setattr(module, "_manifest_row", lambda node_type: {"node_type": node_type})
    monkeypatch.setattr(module, "_run", lambda command: events.append(tuple(command)))

    module.qualify("model.pca")

    assert events[:2] == [("node", "model.pca"), ("tests", "model.pca")]
    commands = [event for event in events[2:] if isinstance(event, tuple)]
    assert any("generate_node_readiness_audit.py" in " ".join(command) and "--check" in command for command in commands)
    assert any("qualify_canonical_node_baseline.py" in " ".join(command) and "check" in command for command in commands)
