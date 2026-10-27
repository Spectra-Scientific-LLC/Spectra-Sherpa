"""A native saved PLS model must be assessed on its exact external population."""

from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dataset_views import receipt_sha256
from spectra_sherpa.app.services.model_store import ModelStore
from spectra_sherpa.app.services.saved_model_qualification import assess_saved_model, qualification_status
from spectra_sherpa.sdk.analytical_qualification import decide_qualification
from spectra_sherpa.sdk.saved_model_qualification import SavedModelApplicationPlan, retain_pls_training_specimens
from tests.test_analytical_qualification import context, policy
from tests.test_prediction_uncertainty import METHOD


@pytest.mark.asyncio
async def test_native_saved_model_assessment_requires_exact_external_identity(tmp_path, monkeypatch):
    import spectra_sherpa.app.services.model_store as model_store
    import spectra_sherpa.app.services.saved_model_qualification as service

    rng = np.random.default_rng(602)
    X = rng.normal(size=(36, 6))
    y = X[:, 0] + X[:, 1] * 2
    train = SherpaDataset(
        X=X,
        target=y,
        sample_axis=SampleAxis(labels=[f"fit-{index}" for index in range(len(X))]),
        feature_axis=SpectralAxis(values=np.arange(6.0) + 1000, units="nm"),
        target_context=TargetContext(target_type="continuous", target_names=["response"], target_units="percent"),
    )
    output = (await FittedPLSV2Node("fit", {"n_components": 2}).execute(input_data=train)).outputs
    store = ModelStore(tmp_path)
    executor = DAGExecutor(runtime=SimpleNamespace(require_model_artifact_writer=lambda: store))
    executor.results["fit"] = output
    await executor._process_model_artifact("fit", named_inputs={"default": train})
    uid = executor.saved_artifacts[0]["artifact_uid"]
    integrity = executor.saved_artifacts[0]["integrity_hash"]
    monkeypatch.setattr(model_store, "get_model_store", lambda: store)
    monkeypatch.setattr(service, "get_model_store", lambda: store)
    manifest, arrays = store.load(uid, verify=True)
    model = SimpleNamespace(
        artifact_uid=uid,
        integrity_hash=integrity,
        model_type="pls",
        training_scientific_digest=manifest["training_scientific_digest"],
        training_dataset_id=1,
        artifact_origin=None,
    )
    plan = SavedModelApplicationPlan.from_verified_snapshot(model, manifest, arrays)
    assert plan.training_specimen_count == 36
    from spectra_sherpa.app.services import model_outlier_challenge as challenge_service

    monkeypatch.setattr(challenge_service, "get_model_store", lambda: store)
    challenge = SherpaDataset(
        X=np.asarray(train.X) + 20,
        target=train.target,
        feature_axis=train.feature_axis,
        target_context=train.target_context,
    )
    challenge.sample_axis = SampleAxis(labels=[f"challenge-{i}" for i in range(len(X))])
    challenge_result, challenge_plan = await challenge_service.assess_outlier_challenge(
        model, challenge, outlier_type="known matrix change", label_basis="independent preparation record"
    )
    assert challenge_plan == plan
    assert challenge_result["evaluated_count"] == 36
    assert challenge_result["detected"] > 0
    assert challenge_result["ordinary_validation_rmsep"] is None
    assert store.load(uid, verify=True)[0] == manifest
    with pytest.raises(ValueError, match="overlap"):
        await challenge_service.assess_outlier_challenge(model, train, outlier_type="test", label_basis="lab")
    declared_policy = policy(response_identity=manifest["response_identity"])
    declared_context = context(reference_method={**METHOD, "response_identity": manifest["response_identity"]})
    external = SherpaDataset(
        X=X[:24] + 0.01,
        target=y[:24],
        sample_axis=SampleAxis(labels=[f"validation-{index}" for index in range(24)]),
        feature_axis=SpectralAxis(values=np.arange(6.0) + 1000, units="nm"),
        target_context=TargetContext(target_type="continuous", target_names=["response"], target_units="percent"),
    )
    view_receipt = {"selected_file_ids": [2], "source_manifest_sha256": "b" * 64}
    view_digest = receipt_sha256(view_receipt)
    with pytest.raises(ValueError, match="distinct"):
        await assess_saved_model(
            model,
            external,
            validation_experiment_id=1,
            validation_view_digest=view_digest,
            validation_source_manifest_digest="b" * 64,
            policy=declared_policy,
            context=declared_context,
        )
    external.sample_axis = SampleAxis(labels=["fit-0", *[f"validation-{index}" for index in range(1, 24)]])
    with pytest.raises(ValueError, match="overlap"):
        await assess_saved_model(
            model,
            external,
            validation_experiment_id=2,
            validation_view_digest=view_digest,
            validation_source_manifest_digest="b" * 64,
            policy=declared_policy,
            context=declared_context,
        )
    external.sample_axis = SampleAxis(labels=[f"validation-{index}" for index in range(24)])
    original_target_context = external.target_context
    for units in (None, "wrong unit"):
        external.target_context = original_target_context.model_copy(update={"target_units": units})
        with pytest.raises(ValueError, match="reference identity or units|target units"):
            await assess_saved_model(
                model,
                external,
                validation_experiment_id=2,
                validation_view_digest=view_digest,
                validation_source_manifest_digest="b" * 64,
                policy=declared_policy,
                context=declared_context,
            )
    external.target_context = original_target_context
    dossier, observed_plan = await assess_saved_model(
        model,
        external,
        validation_experiment_id=2,
        validation_view_digest=view_digest,
        validation_source_manifest_digest="b" * 64,
        policy=declared_policy,
        context=declared_context,
    )
    assert observed_plan == plan
    assert dossier.application_plan_digest == plan.application_plan_digest
    assert dossier.calculation["effective_fitted_components"] == 2
    from spectra_sherpa.app.services.dataset_use import dossier_dataset_use
    from spectra_sherpa.sdk.analytical_qualification import QualificationDossier

    usage = dossier_dataset_use(dossier)
    # The existing dossier transport, not a new history store, carries these
    # exact identities across export/import and presentation-name changes.
    imported_dossier = QualificationDossier.load(dossier.canonical_bytes())
    assert dossier_dataset_use(imported_dossier) == usage
    assert usage["populations"][0]["identity"] == dossier.original_cohort_digest
    assert usage["populations"][0]["results_revealed"] is True
    assert usage["populations"][0]["known_fit_overlap_count"] == 0
    assert usage["independence"] == "not_established_by_usage_history"
    contradictory, _ = await assess_saved_model(
        model,
        external,
        validation_experiment_id=2,
        validation_view_digest=view_digest,
        validation_source_manifest_digest="b" * 64,
        policy=declared_policy,
        context=declared_context,
        independence_evidence={
            "schema_version": "spectrasherpa.recorded-independence/1",
            "populations": [],
            "model_frozen_at": "2026-10-02T00:00:00Z",
            "policy_frozen_at": "2026-09-01T00:00:00Z",
            "validation_acquired_from": "2026-10-01T00:00:00Z",
        },
    )
    assert contradictory.assessment == "criteria_not_met"
    assert any(
        item["name"] == "recorded_model_chronology" and item["state"] == "not_met" for item in contradictory.criteria
    )
    view = SimpleNamespace(id=7, selection=view_receipt, selection_sha256=view_digest, deleted_at=None)
    assessment = SimpleNamespace(
        id=1,
        kind="assessment",
        payload={"dossier": dossier.model_dump(), "plan": plan.model_dump()},
        record_digest=dossier.record_digest,
        model_integrity_hash=plan.artifact_digest,
        manifest_digest=plan.manifest_digest,
        application_plan_digest=plan.application_plan_digest,
        validation_view_id=view.id,
        validation_view_digest=view.selection_sha256,
    )
    dossier._computed_here = True
    decision = (
        decide_qualification(
            dossier,
            decision="accepted_under_declared_policy",
            actor="user:1",
            recorded_at="2026-10-14T00:00:00Z",
            reason="Reviewed exact synthetic policy and source",
        )
        if dossier.assessment == "criteria_met"
        else None
    )
    records = [assessment]
    if decision is not None:
        records.append(
            SimpleNamespace(
                id=2,
                kind="decision",
                parent_digest=dossier.record_digest,
                record_digest=decision.decision_digest,
                payload={"decision": decision.model_dump()},
            )
        )
    current = qualification_status(
        model, manifest, arrays, records, view, source_verified=True, current_dataset=external
    )
    assert current["external_validation"]["count"] == 24
    assert current["external_validation"]["responses"][0]["rmse"] >= 0
    if decision is not None:
        assert current["state"] == "accepted_under_declared_policy"
    assert qualification_status(model, manifest, arrays, records, view, source_verified=False)["state"] == "stale"
    assert (
        qualification_status(model, manifest, arrays, records, view, source_verified=None)["state"]
        == "current_source_unverified"
    )
    assert (
        qualification_status(
            model,
            manifest,
            arrays,
            records,
            view,
            source_verified=True,
            current_dataset=external,
            selection_present=True,
            selected_view_digest=None,
        )["state"]
        == "stale_for_selected_dataset"
    )
    changed = external.with_data(external.X + 0.2)
    assert (
        qualification_status(model, manifest, arrays, records, view, source_verified=True, current_dataset=changed)[
            "state"
        ]
        == "stale"
    )
    external.sample_axis = SampleAxis(labels=[f"changed-{index}" for index in range(24)])
    assert (
        qualification_status(model, manifest, arrays, records, view, source_verified=True, current_dataset=external)[
            "state"
        ]
        == "stale"
    )
    external.sample_axis = SampleAxis(labels=[f"validation-{index}" for index in range(24)])
    assessment.record_digest = "f" * 64
    assert (
        qualification_status(model, manifest, arrays, records, view, source_verified=True, current_dataset=external)[
            "state"
        ]
        == "stale"
    )
    manifest["training_specimen_ids"] = [f"fake-{index}" for index in range(36)]
    with pytest.raises(ValueError, match="contradict stored model bytes"):
        SavedModelApplicationPlan.from_verified_snapshot(model, manifest, arrays)


def test_oversized_fitted_specimen_register_is_not_retained():
    dataset = SherpaDataset(
        X=np.ones((40, 2)),
        sample_axis=SampleAxis(labels=[f"fit-{index}-" + "x" * 4000 for index in range(40)]),
    )
    artifact: dict = {"metadata": {}, "arrays": {}}
    retain_pls_training_specimens(artifact, dataset)
    assert "training_specimen_ids" not in artifact["metadata"]
