"""Saved diagnostics retain the producing fit's exact review decisions."""

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.services import saved_model_diagnostics as module


@pytest.mark.asyncio
async def test_real_plsda_fit_artifact_and_retained_diagnostics_roundtrip(monkeypatch, tmp_path):
    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
    from spectra_sherpa.app.services import model_store, run_output_retention
    from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import _plsda_scientific_core
    from spectra_sherpa.app.services.dag.nodes.classification.plsda_sample_diagnostics import build_sample_diagnostics

    rng = np.random.default_rng(1203)
    labels = np.repeat(["a", "b", "c"], 12)
    matrix = rng.normal(size=(len(labels), 8))
    matrix[labels == "a", :3] += [1.0, 0.3, 0.2]
    matrix[labels == "b", :3] += [0.1, 1.0, 0.4]
    matrix[labels == "c", :3] += [0.2, 0.4, 1.0]
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.linspace(1000, 1700, 8), units="cm-1"),
        sample_axis=SampleAxis(labels=[f"obs-{i}" for i in range(len(labels))]),
        target=labels,
        target_context=TargetContext(target_type="categorical", target_names=["class"]),
    )
    core = _plsda_scientific_core(dataset, labels, parameters={"n_components": 2, "scale": True})
    artifact = core["artifact"]
    receipt = build_sample_diagnostics(core)
    state = artifact.to_fitted_state()
    store = model_store.ModelStore(tmp_path)
    monkeypatch.setattr(model_store, "_store", store)
    manifest, arrays = artifact.to_artifact()
    store.save_new("saved-plsda-real", manifest, arrays)
    monkeypatch.setattr(
        run_output_retention,
        "settings",
        replace(run_output_retention.settings, data_dir=tmp_path),
    )
    evidence = run_output_retention.retain_run_outputs(
        9,
        {"fit": {"fitted_state": state, "sample_diagnostics": receipt}},
        {},
    )
    assert all(item["state"] == "exact" for item in evidence["outputs"]["fit"].values())
    run = SimpleNamespace(id=41, user_id=9, evidence_completeness=evidence)
    model = SimpleNamespace(
        artifact_uid="saved-plsda-real",
        node_id="fit",
        training_scientific_digest=dataset.scientific_digest,
        n_components=artifact.effective_n_components,
        n_features=artifact.features,
    )
    saved = await module.saved_plsda_sample_diagnostics(run, model)
    assert saved["receipt_sha256"] == evidence["outputs"]["fit"]["sample_diagnostics"]["sha256"]
    assert saved["receipt"]["rows"] == receipt["rows"]


def _run():
    return SimpleNamespace(
        id=41,
        user_id=9,
        source_metadata={},
        evidence_completeness={
            "schema_version": 1,
            "outputs": {
                "__workflow__": {
                    "sample_review_provenance": {
                        "state": "exact",
                        "storage": "file",
                        "sha256": "a" * 64,
                        "byte_count": 64,
                        "format_version": 1,
                    }
                }
            },
        },
    )


def _receipt():
    return {
        "model_kind": "pls",
        "rows": [
            {"id": "cal-1", "role": "calibration"},
            {"id": "cal-2", "role": "excluded_projected"},
            {"id": "test-1", "role": "held_out_test"},
        ],
    }


@pytest.mark.asyncio
async def test_saved_diagnostics_use_fit_time_decisions(monkeypatch):
    async def receipt(_run, _node):
        return _receipt()

    monkeypatch.setattr(module, "retained_review_receipt", receipt)
    monkeypatch.setattr(
        module,
        "read_output",
        lambda _user, _item: {
            "pls-node": {
                "revision": 5,
                "marked": ["cal-1"],
                "excluded": ["cal-2"],
                "heldout_excluded": ["test-1"],
            }
        },
    )
    result = await module.saved_model_diagnostics(_run(), "pls-node")
    assert result["run_id"] == 41
    assert result["decision"] == {
        "marked": ["cal-1"],
        "excluded": ["cal-2"],
        "heldout_excluded": ["test-1"],
    }
    assert result["review_revision"] == 5
    assert result["decision_unavailable_reason"] is None


@pytest.mark.asyncio
async def test_saved_diagnostics_refuse_decision_from_different_cohort(monkeypatch):
    async def receipt(_run, _node):
        return _receipt()

    monkeypatch.setattr(module, "retained_review_receipt", receipt)
    monkeypatch.setattr(
        module,
        "read_output",
        lambda _user, _item: {"pls-node": {"marked": ["unknown"], "excluded": ["cal-2"]}},
    )
    with pytest.raises(ValueError, match="do not match"):
        await module.saved_model_diagnostics(_run(), "pls-node")


@pytest.mark.asyncio
async def test_historical_scalar_only_decisions_do_not_claim_no_marks(monkeypatch):
    async def receipt(_run, _node):
        return _receipt()

    monkeypatch.setattr(module, "retained_review_receipt", receipt)
    monkeypatch.setattr(module, "read_output", lambda _user, _item: {"pls-node": {"revision": 2}})
    result = await module.saved_model_diagnostics(_run(), "pls-node")
    assert result["decision"]["marked"] is None
    assert "did not retain" in result["decision_unavailable_reason"]


@pytest.mark.asyncio
async def test_versioned_empty_snapshot_proves_no_review_decisions(monkeypatch):
    async def receipt(_run, _node):
        return {
            "model_kind": "pls",
            "rows": [
                {"id": "cal-1", "role": "calibration"},
                {"id": "test-1", "role": "held_out_test"},
            ],
        }

    monkeypatch.setattr(module, "retained_review_receipt", receipt)
    monkeypatch.setattr(module, "read_output", lambda _user, _item: {})
    run = _run()
    run.source_metadata = {"sample_review_snapshot_version": 2}
    result = await module.saved_model_diagnostics(run, "pls-node")
    assert result["decision"] == {"marked": [], "excluded": [], "heldout_excluded": []}
    assert result["decision_unavailable_reason"] is None


@pytest.mark.asyncio
async def test_versioned_empty_snapshot_rejects_receipt_with_excluded_projection(monkeypatch):
    async def receipt(_run, _node):
        return _receipt()

    monkeypatch.setattr(module, "retained_review_receipt", receipt)
    monkeypatch.setattr(module, "read_output", lambda _user, _item: {})
    run = _run()
    run.source_metadata = {"sample_review_snapshot_version": 2}
    with pytest.raises(ValueError, match="exclusion decisions"):
        await module.saved_model_diagnostics(run, "pls-node")


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [True, False])
async def test_versioned_metadata_without_exact_snapshot_cannot_prove_empty_decisions(monkeypatch, missing):
    async def receipt(_run, _node):
        return _receipt()

    monkeypatch.setattr(module, "retained_review_receipt", receipt)
    run = _run()
    run.source_metadata = {"sample_review_snapshot_version": 2}
    if missing:
        run.evidence_completeness["outputs"]["__workflow__"] = {}
    else:
        run.evidence_completeness["outputs"]["__workflow__"]["sample_review_provenance"] = {
            "state": "missing",
            "reason": "The snapshot was not retained",
        }
    result = await module.saved_model_diagnostics(run, "pls-node")
    assert result["decision"] == {"marked": None, "excluded": None, "heldout_excluded": None}
    assert result["decision_unavailable_reason"] is not None


@pytest.mark.asyncio
async def test_later_review_edit_cannot_change_producing_runs_retained_decisions(monkeypatch, tmp_path):
    from spectra_sherpa.app.services import run_output_retention

    async def receipt(_run, _node):
        return _receipt()

    monkeypatch.setattr(module, "retained_review_receipt", receipt)
    monkeypatch.setattr(
        run_output_retention,
        "settings",
        replace(run_output_retention.settings, data_dir=tmp_path),
    )
    mutable_workflow_decisions = {
        "pls-node": {"revision": 4, "marked": ["cal-1"], "excluded": ["cal-2"], "heldout_excluded": []}
    }
    evidence = run_output_retention.retain_run_outputs(
        9, {"__workflow__": {"sample_review_provenance": mutable_workflow_decisions}}, {}
    )
    assert evidence["outputs"]["__workflow__"]["sample_review_provenance"]["state"] == "exact"
    # A later workflow revision is mutable, while the producing run points to
    # the prior immutable, checksum-verified output.
    mutable_workflow_decisions["pls-node"] = {
        "revision": 5,
        "marked": ["test-1"],
        "excluded": ["cal-2"],
        "heldout_excluded": ["test-1"],
    }
    run = _run()
    run.source_metadata = {"sample_review_snapshot_version": 2}
    run.evidence_completeness = evidence
    result = await module.saved_model_diagnostics(run, "pls-node")
    assert result["review_revision"] == 4
    assert result["decision"] == {"marked": ["cal-1"], "excluded": ["cal-2"], "heldout_excluded": []}


@pytest.mark.asyncio
async def test_saved_plsda_terms_require_exact_fitted_state_and_training_digest(monkeypatch):
    from spectra_sherpa.app.services import model_store
    from spectra_sherpa.app.services.dag.nodes.classification import plsda_state

    screening = {
        "reference_samples": 1,
        "t2_limit": 2.0,
        "q_limit": 1.0,
        "method": "fixture_screening",
        "q_limit_method": "fixture_q",
        "score_covariance_rank": 2,
        "rank_tolerance": 1e-12,
        "t2_unavailable_reason": None,
        "q_unavailable_reason": None,
    }
    monkeypatch.setattr(
        plsda_state.SherpaPLSDAArtifact,
        "from_fitted_state",
        lambda _state: SimpleNamespace(effective_n_components=2, features=8, screening=screening),
    )
    state = {"serializer": "fitted", "coefficients": [1, 2]}
    digest = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt = {
        "schema_version": "spectrasherpa-plsda-sample-diagnostics/1",
        "model_kind": "plsda",
        "fitted_state_sha256": digest,
        "source_execution_digest": "b" * 64,
        "components": 2,
        "feature_count": 8,
        "reference_count": 1,
        "t2_limit": 2.0,
        "q_limit": 1.0,
        "screening_method": "fixture_screening",
        "q_limit_method": "fixture_q",
        "score_covariance_rank": 2,
        "rank_tolerance": 1e-12,
        "t2_unavailable_reason": None,
        "q_unavailable_reason": None,
        "rows": [
            {
                "id": "obs-1",
                "role": "calibration",
                "scores": [0.1, 0.2],
                "q": 0.3,
                "t2": 1.0,
                "outside_t2": False,
                "outside_q": False,
                "terms": {
                    "variables": [[0, 0.2, 0.6]],
                    "omitted_q": 0.1,
                    "omitted_t2": 0.4,
                    "omitted_t2_absolute": 0.4,
                },
            }
        ],
    }
    run = _run()
    run.evidence_completeness["outputs"]["fit"] = {
        name: {
            "state": "exact",
            "storage": "file",
            "sha256": "a" * 64,
            "byte_count": 64,
            "format_version": 1,
        }
        for name in ("sample_diagnostics", "fitted_state")
    }
    monkeypatch.setattr(
        plsda_state.SherpaPLSDAArtifact,
        "from_artifact",
        lambda _manifest, _arrays: SimpleNamespace(to_fitted_state=lambda: state),
    )
    monkeypatch.setattr(
        model_store, "get_model_store", lambda: SimpleNamespace(load=lambda *_args, **_kwargs: ({}, {}))
    )
    model = SimpleNamespace(
        artifact_uid="saved-1",
        node_id="fit",
        training_scientific_digest="b" * 64,
        n_components=None,
        n_features=8,
    )
    # RunEvidence validates and copies output entries, so dispatch by call order.
    values = iter([receipt, state])
    monkeypatch.setattr(module, "read_output", lambda _user, _item: next(values))
    result = await module.saved_plsda_sample_diagnostics(run, model)
    assert result["receipt"]["rows"][0]["id"] == "obs-1"
    values = iter([{**receipt, "fitted_state_sha256": "0" * 64}, state])
    with pytest.raises(ValueError, match="fitted state"):
        await module.saved_plsda_sample_diagnostics(run, model)
    bad = {**receipt, "rows": [{**receipt["rows"][0], "q": 0.7}]}
    values = iter([bad, state])
    with pytest.raises(ValueError, match="do not reconstruct"):
        await module.saved_plsda_sample_diagnostics(run, model)
    values = iter([{**receipt, "t2_limit": 0.5}, state])
    with pytest.raises(ValueError, match="fitted screening state"):
        await module.saved_plsda_sample_diagnostics(run, model)
    values = iter([{**receipt, "rows": [{**receipt["rows"][0], "outside_q": True}]}, state])
    with pytest.raises(ValueError, match="screening flags"):
        await module.saved_plsda_sample_diagnostics(run, model)
