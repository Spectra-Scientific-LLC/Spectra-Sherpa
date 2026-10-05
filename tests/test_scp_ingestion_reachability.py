from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "packages" / "spectra-sherpa" / "tools" / "generate_scp_ingestion_reachability.py"
EVIDENCE = ROOT / "docs" / "evidence" / "scp-ingestion-reachability.json"


def _module():
    spec = importlib.util.spec_from_file_location("scp_ingestion_reachability", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reachability_evidence_exactly_matches_retained_tree():
    expected = _module().document()
    assert json.loads(EVIDENCE.read_text()) == expected
    assert expected["records"]
    assert set(expected["counts"]) == {
        "algorithm_keep_optional",
        "historical_test_update",
        "optional_dependency_gate",
    }


def test_optional_algorithm_set_is_exact_and_narrow():
    document = json.loads(EVIDENCE.read_text())
    optional_paths = {
        record["path"] for record in document["records"] if record["classification"] == "algorithm_keep_optional"
    }
    assert optional_paths == {
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/efa_nodes.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/mcr_nodes.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/simplisma_nodes.py",
        "packages/spectra-sherpa/src/spectra_sherpa/interoperability/spectrochempy_adapter.py",
    }


def test_optional_dependency_gate_set_is_exact_and_contains_the_catalog_projection():
    document = json.loads(EVIDENCE.read_text())
    gate_paths = {
        record["path"] for record in document["records"] if record["classification"] == "optional_dependency_gate"
    }
    assert gate_paths == {
        "packages/spectra-sherpa/src/spectra_sherpa/app/api/v1/routes/workflows/catalog.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/schemas/workflows.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/node_base.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/node_catalog_contract.py",
    }
