"""Bind saved-model diagnostic plots to the exact producing run and review revision."""

from __future__ import annotations

import hashlib
import json
import math
from asyncio import to_thread
from typing import Any

from spectra_sherpa.app.schemas.run_evidence import RunEvidence
from spectra_sherpa.app.services.retained_review_receipt import retained_review_receipt
from spectra_sherpa.app.services.run_output_retention import read_output


async def saved_plsda_sample_diagnostics(run: Any, model: Any) -> dict[str, Any]:
    """Read a classifier's exact retained sample terms and bind them to its artifact."""

    from spectra_sherpa.app.services.dag.nodes.classification.plsda_sample_diagnostics import MAX_BYTES, SCHEMA
    from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import SherpaPLSDAArtifact
    from spectra_sherpa.app.services.model_store import get_model_store

    evidence = RunEvidence.model_validate(run.evidence_completeness)
    outputs = evidence.outputs.get(model.node_id, {})
    retained = {}
    for name, limit in (("sample_diagnostics", MAX_BYTES + 64 * 1024), ("fitted_state", 6 * 1024 * 1024)):
        item = outputs.get(name)
        if (
            item is None
            or item.state != "exact"
            or item.storage != "file"
            or not item.byte_count
            or item.byte_count > limit
        ):
            raise ValueError(f"Exact PLS-DA {name} was not retained")
        retained[name] = await to_thread(read_output, run.user_id, item)
    receipt, state = retained["sample_diagnostics"], retained["fitted_state"]
    if not isinstance(receipt, dict) or not isinstance(state, dict):
        raise ValueError("Saved PLS-DA diagnostic values are malformed")
    if receipt.get("schema_version") != SCHEMA or receipt.get("model_kind") != "plsda":
        raise ValueError(receipt.get("unavailable_reason") or "Unsupported PLS-DA sample diagnostic receipt")
    digest = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    if receipt.get("fitted_state_sha256") != digest:
        raise ValueError("PLS-DA sample diagnostics differ from the producing fitted state")
    artifact = SherpaPLSDAArtifact.from_fitted_state(state)
    manifest, arrays = await to_thread(get_model_store().load, model.artifact_uid, verify=True)
    stored = SherpaPLSDAArtifact.from_artifact(manifest, arrays)
    if stored.to_fitted_state() != state:
        raise ValueError("PLS-DA run fitted state differs from the verified saved artifact")
    screening = artifact.screening
    if screening is None:
        raise ValueError("PLS-DA fitted state has no screening reference")
    expected_screening = {
        "reference_count": screening["reference_samples"],
        "t2_limit": screening["t2_limit"],
        "q_limit": screening["q_limit"],
        "screening_method": screening["method"],
        "q_limit_method": screening.get("q_limit_method", "empirical_calibration_quantile"),
        "score_covariance_rank": screening["score_covariance_rank"],
        "rank_tolerance": screening["rank_tolerance"],
        "t2_unavailable_reason": screening["t2_unavailable_reason"],
        "q_unavailable_reason": screening["q_unavailable_reason"],
    }
    if any(receipt.get(key) != expected for key, expected in expected_screening.items()):
        raise ValueError("PLS-DA sample diagnostic limits differ from the fitted screening state")
    if (
        receipt.get("components") != artifact.effective_n_components
        or receipt.get("feature_count") != artifact.features
    ):
        raise ValueError("PLS-DA sample diagnostics contradict the fitted classifier")
    if receipt.get("source_execution_digest") != model.training_scientific_digest:
        raise ValueError("PLS-DA sample diagnostics differ from the saved model's training data")
    if (model.n_components is not None and receipt.get("components") != model.n_components) or receipt.get(
        "feature_count"
    ) != model.n_features:
        raise ValueError("PLS-DA diagnostic dimensions differ from the saved model")
    rows = receipt.get("rows")
    if not isinstance(rows, list) or len(rows) != receipt.get("reference_count"):
        raise ValueError("PLS-DA diagnostic reference population is malformed")
    identities = [row.get("id") for row in rows if isinstance(row, dict)]
    if len(identities) != len(rows) or len(set(identities)) != len(rows):
        raise ValueError("PLS-DA diagnostic observation identities are malformed")
    for row in rows:
        if not isinstance(row["id"], str) or not row["id"] or row.get("role") != "calibration":
            raise ValueError("PLS-DA diagnostic observation custody is malformed")
        scores = row.get("scores")
        if (
            not isinstance(scores, list)
            or len(scores) != artifact.effective_n_components
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in scores)
        ):
            raise ValueError("PLS-DA diagnostic score vector is malformed")
        terms = row.get("terms")
        if not isinstance(terms, dict) or not isinstance(terms.get("variables"), list):
            raise ValueError("PLS-DA diagnostic variable terms are malformed")
        variables = terms["variables"]
        indices = [term[0] for term in variables if isinstance(term, list) and len(term) == 3]
        if (
            len(indices) != len(variables)
            or len(set(indices)) != len(indices)
            or any(type(index) is not int or not 0 <= index < artifact.features for index in indices)
        ):
            raise ValueError("PLS-DA diagnostic variable identities are malformed")
        if any(type(term[1]) not in (int, float) or term[1] < 0 for term in variables):
            raise ValueError("PLS-DA Q contributions must be nonnegative")
        omitted_absolute = terms.get("omitted_t2_absolute")
        omitted_signed = terms.get("omitted_t2")
        if omitted_signed is not None and (
            type(omitted_absolute) not in (int, float)
            or not math.isfinite(omitted_absolute)
            or omitted_absolute + 1e-10 < abs(omitted_signed)
        ):
            raise ValueError("PLS-DA signed T² omission exceeds its absolute mass")
        for total, term_index, omitted in (("q", 1, "omitted_q"), ("t2", 2, "omitted_t2")):
            expected = row.get(total)
            values = [term[term_index] for term in variables]
            if expected is None:
                if total != "t2" or any(value is not None for value in values) or terms.get(omitted) is not None:
                    raise ValueError("PLS-DA unavailable T² decomposition is inconsistent")
                continue
            if not all(
                type(value) in (int, float) and math.isfinite(value)
                for value in [expected, *values, terms.get(omitted)]
            ):
                raise ValueError("PLS-DA diagnostic variable terms are nonfinite")
            if not math.isclose(sum(values) + terms[omitted], expected, rel_tol=1e-9, abs_tol=1e-10):
                raise ValueError("PLS-DA diagnostic variable terms do not reconstruct their statistic")
        if row.get("outside_t2") != (None if row["t2"] is None else row["t2"] > screening["t2_limit"]) or row.get(
            "outside_q"
        ) != (None if screening["q_limit"] is None else row["q"] > screening["q_limit"]):
            raise ValueError("PLS-DA screening flags contradict the fitted limits")
    return {
        "run_id": run.id,
        "node_id": model.node_id,
        "receipt_sha256": outputs["sample_diagnostics"].sha256,
        "receipt": receipt,
        "reference_value_evidence": manifest.get("reference_value_evidence"),
    }


async def saved_model_diagnostics(run: Any, node_id: str) -> dict[str, Any]:
    receipt = await retained_review_receipt(run, node_id)
    rows = receipt.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("The source run has no exact sample-level diagnostic rows.")
    identities = {row.get("id") for row in rows if isinstance(row, dict)}
    if len(identities) != len(rows) or not all(isinstance(identity, str) and identity for identity in identities):
        raise ValueError("Saved diagnostic observation identities are invalid.")

    evidence = RunEvidence.model_validate(run.evidence_completeness)
    item = evidence.outputs.get("__workflow__", {}).get("sample_review_provenance")
    snapshot: dict[str, Any] = {}
    exact_snapshot = False
    if item is not None and item.state == "exact" and item.storage == "file":
        if not item.byte_count or item.byte_count > 1024 * 1024:
            raise ValueError("Saved review decision evidence exceeds the read budget.")
        value = await to_thread(read_output, run.user_id, item)
        if not isinstance(value, dict):
            raise ValueError("Saved review decision evidence is malformed.")
        exact_snapshot = True
        snapshot = value.get(node_id, {})
        if not isinstance(snapshot, dict):
            raise ValueError("Saved review decision evidence is malformed.")

    # Version 2 proves that the execution admission lock observed no decision
    # when the node is absent. Older runs cannot distinguish that from missing
    # historical custody and must not silently present an empty decision.
    exact_empty = exact_snapshot and (run.source_metadata or {}).get("sample_review_snapshot_version") == 2
    decision = {
        "marked": [] if exact_empty and not snapshot else None,
        "excluded": [] if exact_empty and not snapshot else None,
        "heldout_excluded": [] if exact_empty and not snapshot else None,
    }
    if snapshot:
        for key in decision:
            value = snapshot.get(key)
            if value is None:
                continue  # Historical scalar-only provenance cannot recreate exact marks.
            if not isinstance(value, list) or any(not isinstance(identity, str) for identity in value):
                raise ValueError("Saved review decision identities are malformed.")
            if len(set(value)) != len(value) or not set(value).issubset(identities):
                raise ValueError("Saved review decisions do not match the producing run.")
            decision[key] = value
    excluded_rows = {row["id"] for row in rows if row.get("role") == "excluded_projected"}
    if decision["excluded"] is not None and set(decision["excluded"]) != excluded_rows:
        raise ValueError("Saved exclusion decisions differ from the fitted model cohort.")
    heldout = {row["id"] for row in rows if row.get("role") == "held_out_test"}
    if decision["heldout_excluded"] is not None and not set(decision["heldout_excluded"]).issubset(heldout):
        raise ValueError("Saved held-out review decisions differ from the original test cohort.")

    return {
        "run_id": run.id,
        "node_id": node_id,
        "receipt": receipt,
        "decision": decision,
        "review_revision": snapshot.get("revision") if snapshot else None,
        "post_review": snapshot.get("post_review") if snapshot else False,
        "decision_unavailable_reason": (
            None
            if all(value is not None for value in decision.values())
            else "This historical run did not retain exact outlier mark decisions."
        ),
    }
