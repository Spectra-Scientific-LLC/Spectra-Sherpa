"""Exact application continuity for the typed PLS-DA diagnostic identity fix."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.core import contract_compatibility as authority
from spectra_sherpa.sdk.fitted_state_custody import (
    DATA_FREE_APPLICATION_STATE,
    FittedStateCustodyError,
    fitted_state_custody_capability,
)

OLD = "65017fa4efd2c518f7f07dbdd12c332cb472b13ee6b734b69f4c9569aa445b7f"
NEW = "b4910376c363b3564a1fb959b52ab75ca93b7744f5b15d19caa582258ca43f43"
PROFILE = "d82af6a5a5b9922b1c57531d3ce9d121ad6e7c6f80ee3dc6bb24119f6b2f24c9"
SERIALIZER = "spectrasherpa.sherpa-plsda-state/5"
ROOT = Path(__file__).resolve().parents[1]


def test_catalog_is_minimal_integrity_pinned_and_explicitly_packaged():
    path = "src/spectra_sherpa/core/contract_predecessors_plsda_identity.json"
    raw = (ROOT / path).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "8180787692c1f5162a0e8b0077dca5cfc530bfc8b1bbf7babe0050936dd5364d"
    catalog = authority.inspection_predecessor_catalog(PROFILE)
    assert catalog == json.loads(raw)
    assert set(catalog["contracts"]) == {"classification.plsda"}
    assert catalog["current_contracts"] == {"classification.plsda": OLD}
    assert len(catalog["profile"]["operations"]) == 22
    assert catalog["source"]["capture_sha256"] == ("9043dc62396e48c63c8d20c290dbe3cfeb7d4734d9776d879e752b5c9f5b6547")
    includes = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["poetry"]["include"]
    assert {"path": path, "format": ["sdist", "wheel"]} in includes
    catalog["profile"]["operations"].clear()
    assert len(authority.inspection_predecessor_catalog(PROFILE)["profile"]["operations"]) == 22


def test_catalog_integrity_tampering_is_refused(monkeypatch, tmp_path):
    (tmp_path / "contract_predecessors_plsda_identity.json").write_text("{}")
    monkeypatch.setattr(authority, "files", lambda _: tmp_path)
    with pytest.raises(ValueError, match="catalog digest mismatch"):
        authority.inspection_predecessor_catalog(PROFILE)


def test_exact_fourteen_direct_pairs_preserve_old_pairs():
    previous = tuple(
        e for e in authority._PREPROCESSING_APPLICATION_PREDECESSORS if e.operation_id == "classification.plsda"
    )
    entries = authority._PLSDA_DIAGNOSTIC_IDENTITY_PREDECESSORS
    assert len(previous) == 13
    assert len(entries) == 14
    assert {e.predecessor_digest for e in entries} == {e.predecessor_digest for e in previous} | {OLD}
    assert {(e.operation_id, e.consumer_digest, e.serializer) for e in entries} == {
        ("classification.plsda", NEW, SERIALIZER)
    }
    for entry in previous:
        assert authority.saved_state_predecessor_is_compatible(
            entry.predecessor_digest, OLD, operation_id=entry.operation_id, serializer=SERIALIZER
        )


@pytest.mark.parametrize(
    "entry", authority._PLSDA_DIAGNOSTIC_IDENTITY_PREDECESSORS, ids=lambda e: e.predecessor_digest[:8]
)
def test_pairs_are_directional_exact_and_serializer_scoped(entry):
    assert authority.saved_state_predecessor_is_compatible(entry.predecessor_digest, NEW, serializer=SERIALIZER)
    assert authority.saved_state_predecessor_is_compatible(
        entry.predecessor_digest, NEW, operation_id="classification.plsda"
    )
    for before, after, operation, serializer in (
        (NEW, entry.predecessor_digest, "classification.plsda", SERIALIZER),
        ("f" * 64, NEW, "classification.plsda", SERIALIZER),
        (entry.predecessor_digest, "f" * 64, "classification.plsda", SERIALIZER),
        (entry.predecessor_digest, NEW, "classification.knn", SERIALIZER),
        (entry.predecessor_digest, NEW, "classification.plsda", "spectrasherpa.sherpa-plsda-state/4"),
    ):
        assert not authority.saved_state_predecessor_is_compatible(
            before, after, operation_id=operation, serializer=serializer
        )
    assert not authority.saved_state_predecessor_is_compatible(entry.predecessor_digest, NEW)


def test_current_contract_and_state_custody_are_exact_and_other_consumers_unchanged():
    current = node_registry.get_metadata("classification.plsda").resolved_execution_contract()
    assert current.digest == NEW
    assert current.payload["fitted_state_serializer"] == SERIALIZER
    for digest in (OLD, NEW):
        assert fitted_state_custody_capability(SERIALIZER, digest).custody_class == DATA_FREE_APPLICATION_STATE
    for serializer, digest in ((SERIALIZER, "f" * 64), ("spectrasherpa.sherpa-plsda-state/4", NEW)):
        with pytest.raises(FittedStateCustodyError):
            fitted_state_custody_capability(serializer, digest)
    for operation, digest in {
        "classification.apply_plsda": "7119b21c01593405c2cd90227beffb65d72285841ebb4ac59aa181617c5560c8",
        "diagnostics.plsda_permutation": "cefd94b6d587d017f5ec33a99d4443c2ea715d9294d5140e7045aae0ea9a80ec",
    }.items():
        assert node_registry.get_metadata(operation).resolved_execution_contract().digest == digest
