"""Structural guards for the fixed run-evidence acceptance inventory.

These checks qualify the specification, not historical result retention.
"""

import ast
import json
from pathlib import Path

TESTS = Path(__file__).parent
APP = TESTS.parent / "src" / "spectra_sherpa" / "app"


def test_run_evidence_fixture_inventory_is_explicit_and_traceable():
    inventory = json.loads((TESTS / "fixtures" / "run_evidence_journeys.json").read_text(encoding="utf-8"))
    assert inventory["schema"] == "run-evidence-journeys/v1"
    assert set(inventory["outcomes"]) == {"success", "partial_failure", "total_failure", "historical_incomplete"}
    fixtures = inventory["fixtures"]
    assert {fixture["id"] for fixture in fixtures} == {
        "pca",
        "pls",
        "classification",
        "hca",
        "transformed_data",
        "model_application",
    }
    for fixture in fixtures:
        for key in ("outputs", "labels", "validation", "retention", "interpretation"):
            assert fixture[key], (fixture["id"], key)
        for test in fixture["producer_tests"]:
            assert (TESTS / test).is_file(), test


def test_production_execution_run_writers_declare_kind():
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "ExecutionRun":
                continue
            keywords = {keyword.arg for keyword in node.keywords}
            if None in keywords:
                # The shared finalizer supplies one explicit run_data mapping.
                assert path.name == "_helpers.py"
                assert any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "dict"
                    and "run_kind" in {keyword.arg for keyword in call.keywords}
                    for call in ast.walk(tree)
                )
            else:
                assert "run_kind" in keywords, f"{path}:{node.lineno} inherits an ambiguous default"


def test_folder_watch_records_inference_not_training():
    tree = ast.parse((APP / "services" / "folder_watch_service.py").read_text(encoding="utf-8"))
    writers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ExecutionRun"
    ]
    assert len(writers) == 1
    kind = next(keyword.value for keyword in writers[0].keywords if keyword.arg == "run_kind")
    assert isinstance(kind, ast.Constant) and kind.value == "batch_inference"
