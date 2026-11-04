"""Exact source-bound continuity; old inputs are never relabeled current fits."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.historical_contracts import HistoricalReconstructionContext
from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationGraphError,
    assert_admitted_validation_graph,
    validation_graph_from_dict,
)
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core import contract_compatibility as compatibility
from spectra_sherpa.core.contract_compatibility import inspection_predecessor_catalog

ROOT = Path(__file__).parents[1]
PROFILE = "4e75fd88112e9b46d8adbcf860dcc9598b994b48f9d36716651a9ede139cfd68"
CHANGED = {"model.pca", "model.fitted_pls", "classification.plsda", "diagnostics.plsda_permutation"}


def captured():
    raw = (Path(__file__).parent / "fixtures/prebaseline_cv_registry.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "290dcb5eb7733754677acb73ed092e128228db82e3fc6913d8ed09c6cf4218c5"
    return json.loads(raw)


@pytest.fixture(autouse=True)
def _types():
    if not type_registry.is_loaded:
        type_registry.load(ROOT / "src/spectra_sherpa/app/types")


def test_only_four_exact_contracts_and_managed_profile_change():
    before = captured()
    live = {
        m.node_type: m.resolved_execution_contract()
        for m in node_registry.list_nodes()
        if m.resolved_execution_contract() is not None
    }
    assert set(live) == set(before["contracts"])
    assert {op for op, c in live.items() if c.digest != before["contracts"][op]} == CHANGED
    archived = inspection_predecessor_catalog(PROFILE)
    for op in CHANGED:
        old = archived["contracts"][op]["payload"]
        current = live[op].as_dict()
        assert {key for key in old if old[key] != current[key]} == {
            "implementation_digest",
            "implementation_components",
        }
        old_components = {c["component_id"]: c["digest"] for c in old["implementation_components"]}
        new_components = {c["component_id"]: c["digest"] for c in current["implementation_components"]}
        assert {key for key in old_components if old_components[key] != new_components[key]} == {
            "spectra_sherpa.app.services.dag.nodes.modeling.component_validation"
        }
    profile = managed_optimization_profile()
    assert profile.profile_version == "10" and before["profile"]["profile_version"] == "9"
    assert profile.digest != PROFILE
    assert set(profile.operation_ids) == set(before["profile"]["operations"])
    assert {op for op, digest in before["profile"]["operations"].items() if live[op].digest != digest} == {
        "model.fitted_pls",
        "classification.plsda",
    }


def test_old_catalogs_keep_exact_bytes_and_every_profile_still_inspects():
    for name, expected in captured()["catalog_sha256"].items():
        raw = (ROOT / "src/spectra_sherpa/core" / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected
        profile = json.loads(raw)["profile"]
        assert HistoricalReconstructionContext(profile["profile_digest"]).profile().digest == profile["profile_digest"]
    context = HistoricalReconstructionContext(PROFILE)
    assert context.profile().digest == PROFILE
    assert context.added_pls_parameters() == set()
    for op in CHANGED:
        old = captured()["contracts"][op]
        assert context.contract(op, old).digest == old
        with pytest.raises(ValidationGraphError):
            context.contract(op, node_registry.get_metadata(op).resolved_execution_contract().digest)


def test_old_automatic_parameters_reopen_but_graph_never_executes():
    context = HistoricalReconstructionContext(PROFILE)
    old = context.reconstruct(
        [
            WorkflowNode(
                "pls",
                "model.fitted_pls",
                {
                    "component_fit_mode": "one_standard_error",
                    "n_components": 3,
                    "component_cv_folds": 5,
                    "component_curve_max": 4,
                },
            )
        ],
        [],
    )
    assert context.graph(old.as_dict()).as_dict() == old.as_dict()
    assert old.nodes[0].parameters["component_fit_mode"] == "one_standard_error"
    with pytest.raises(ValidationGraphError):
        assert_admitted_validation_graph(old)
    with pytest.raises(ValidationGraphError):
        validation_graph_from_dict(old.as_dict())
    forged = deepcopy(old.as_dict())
    forged["nodes"][0]["contract_digest"] = "f" * 64
    with pytest.raises(ValidationGraphError):
        context.graph(forged)


@pytest.mark.parametrize("entry", compatibility._BASELINE_CV_APPLICATION_PREDECESSORS)
def test_exact_direct_saved_state_rows_no_reverse_unknown_or_serializer_alias(entry):
    assert compatibility.saved_state_predecessor_is_compatible(
        entry.predecessor_digest, entry.consumer_digest, operation_id=entry.operation_id, serializer=entry.serializer
    )
    assert not compatibility.saved_state_predecessor_is_compatible(
        entry.consumer_digest, entry.predecessor_digest, operation_id=entry.operation_id, serializer=entry.serializer
    )
    assert not compatibility.saved_state_predecessor_is_compatible(
        "f" * 64, entry.consumer_digest, operation_id=entry.operation_id, serializer=entry.serializer
    )
    assert not compatibility.saved_state_predecessor_is_compatible(
        entry.predecessor_digest, entry.consumer_digest, operation_id=entry.operation_id, serializer="wrong/1"
    )


@pytest.mark.parametrize("operation", ["model.pca", "model.fitted_pls", "classification.plsda"])
def test_genuinely_prepatch_fitted_models_apply_without_refit_or_rewriting(operation, monkeypatch):
    raw = (Path(__file__).parent / "fixtures/prebaseline_cv_fitted_models.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "ab619407c56be5d1e333c9947d5e09530d0c201b52697c349f2cf87f954cf368"
    fixture = json.loads(raw)
    case = fixture["cases"][operation]
    assert case["contract_digest"] == captured()["contracts"][operation]
    state = deepcopy(case["state"])
    ds = SherpaDataset(
        X=np.asarray(fixture["X"]), feature_axis=SpectralAxis(values=np.asarray(fixture["axis"]), units="cm-1")
    )
    node = node_registry.create_node(operation, "apply", {"n_components": "2" if operation == "model.pca" else 2})
    monkeypatch.setattr(type(node), "fit_fitted_state", lambda *a, **kw: pytest.fail("application refit"))
    actual = node.apply_fitted_state(ds, state)
    np.testing.assert_allclose(actual, np.asarray(case["prediction"]), rtol=1e-12, atol=1e-12)
    assert state == case["state"]
    if operation == "model.fitted_pls":
        from spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model import (
            STATE_ARRAY,
            apply_saved_native_model,
        )

        payload = json.loads(case["native_payload_utf8"])
        assert payload["source_contract_digest"] == case["contract_digest"]
        arrays = {STATE_ARRAY: np.frombuffer(case["native_payload_utf8"].encode(), dtype=np.uint8)}
        applied = apply_saved_native_model(case["manifest"], arrays, ds, ds.X)
        np.testing.assert_allclose(applied["predictions"], actual, rtol=1e-12, atol=1e-12)
        payload["source_contract_digest"] = "f" * 64
        arrays = {STATE_ARRAY: np.frombuffer(json.dumps(payload).encode(), dtype=np.uint8)}
        with pytest.raises(ValueError, match="contract is incompatible"):
            apply_saved_native_model(case["manifest"], arrays, ds, ds.X)


def test_new_catalog_requires_exact_integrity(monkeypatch):
    class Changed:
        def joinpath(self, _):
            return self

        def read_bytes(self):
            return b"{}"

    monkeypatch.setattr(compatibility, "files", lambda _: Changed())
    with pytest.raises(ValueError, match="catalog digest mismatch"):
        inspection_predecessor_catalog(PROFILE)


@pytest.mark.parametrize("operation", sorted(CHANGED))
@pytest.mark.parametrize("field", ["semantic_outputs", "parameter_schema_digest", "runtime_requirements"])
def test_exact_prebaseline_reader_rejects_declaration_drift(operation, field, monkeypatch):
    from types import SimpleNamespace

    context = HistoricalReconstructionContext(PROFILE)
    metadata = node_registry.get_metadata(operation)
    current = metadata.resolved_execution_contract()
    payload = dict(current.payload)
    payload[field] = () if field != "parameter_schema_digest" else "f" * 64
    monkeypatch.setattr(
        metadata, "resolved_execution_contract", lambda: SimpleNamespace(digest=current.digest, payload=payload)
    )
    with pytest.raises(ValidationGraphError, match="scientific declarations changed"):
        context.contract(operation, captured()["contracts"][operation])


def test_historical_profile_cannot_be_rebound_to_new_version():
    context = HistoricalReconstructionContext(PROFILE)
    with pytest.raises(ValidationGraphError, match="unknown historical managed profile"):
        context.require_profile({"profile_id": "first_party_pls", "profile_version": "10", "profile_digest": PROFILE})


def test_exact_prebaseline_catalog_is_explicitly_packaged():
    import tomllib

    includes = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["poetry"]["include"]
    assert {
        "path": "src/spectra_sherpa/core/contract_predecessors_baseline_cv.json",
        "format": ["sdist", "wheel"],
    } in includes
