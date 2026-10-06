"""Near-duplicate node logic is deduplicated, classified, and observable."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from spectra_sherpa.app.services.dag.nodes.transfer import DSNode, PDSNode, SWSNode

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_TOOL = Path(__file__).resolve().parents[1] / "tools/detect_node_duplication.py"
_EVIDENCE = _REPOSITORY_ROOT / "docs/evidence/canonical-node-near-duplicate-families.json"


def _load_tool():
    spec = importlib.util.spec_from_file_location("detect_node_duplication", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_checked_near_duplicate_evidence_is_current(monorepo_root: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(_TOOL), "--check-evidence", str(_EVIDENCE)],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_reported_pair_has_one_canonical_identity_and_classification(monorepo_root: Path) -> None:
    evidence = json.loads(_EVIDENCE.read_text(encoding="utf-8"))
    identities = [
        (
            pair["left"]["file"],
            pair["left"]["function"],
            pair["right"]["file"],
            pair["right"]["function"],
        )
        for pair in evidence["pairs"]
    ]
    assert len(identities) == len(set(identities)) == evidence["total_unique_pairs"]
    assert all(identity[:2] < identity[2:] for identity in identities)
    assert len({pair["pair_id"] for pair in evidence["pairs"]}) == len(identities)
    assert {pair["family_id"] for pair in evidence["pairs"]} == {family["family_id"] for family in evidence["families"]}
    assert evidence["total_families"] == len(evidence["families"])
    assert set(evidence["classification_counts"]) == {
        "plumbing",
        "structural_sibling",
        "verification_critical",
    }
    assert evidence["classification_counts"]["verification_critical"] == 0


def test_transfer_producers_inherit_one_envelope_verification_authority() -> None:
    assert DSNode.make_fitted_state_envelope is PDSNode.make_fitted_state_envelope
    assert PDSNode.make_fitted_state_envelope is SWSNode.make_fitted_state_envelope
    assert DSNode.verify_fitted_state_envelope is PDSNode.verify_fitted_state_envelope
    assert PDSNode.verify_fitted_state_envelope is SWSNode.verify_fitted_state_envelope

    tool = _load_tool()
    evidence = tool.build_evidence()
    transfer_envelope_pairs = [
        pair
        for pair in evidence["pairs"]
        if pair["classification"] == "verification_critical"
        and any("transfer/" in side["file"] for side in (pair["left"], pair["right"]))
    ]
    assert transfer_envelope_pairs == []
