"""Bounded additive explanations of canonical saved PLS predictions, never a fit."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from spectra_sherpa.app.services.dag.fitted_input_identity import require_fitted_input_identity

MAX_FEATURES = 20000
MAX_TARGETS = 16
MAX_RECORDS = 60000
MAX_PROFILE_CELLS = 100000
MAX_WORK = 100_000_000
MAX_BYTES = 6 * 1024 * 1024


def _digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def build_explanations(state, model_digest, source_contract_digest, populations, rows, preprocessing, saved_loadings):
    """The caller has verified the producer envelope; populations are exact inputs.

    Coefficients already incorporate internal X/Y scaling. Decompose the affine
    prediction in PLS-input units, checking every sum against canonical outputs.
    Never divide by the diagnostic scale again or interpret this as residual error.
    """
    p, targets, components = state["features"], state["targets"], state["effective_n_components"]
    observations = sum(ds.shape[0] for ds in populations)
    if (
        not 1 <= p <= MAX_FEATURES
        or not 1 <= targets <= MAX_TARGETS
        or not 1 <= components <= 64
        or observations * targets > MAX_RECORDS
        or observations * p * targets > MAX_WORK
    ):
        raise ValueError("PLS explanations exceed the bounded variable, response or calculation budget.")
    reference_ids = [r["id"] for r in rows if r["role"] == "calibration"]
    if len(reference_ids) != state["reference_samples"] or list(populations[0].sample_axis.labels) != reference_ids:
        raise ValueError("PLS explanation calibration identity/order differs from the fitted reference.")
    expected = {r["id"]: r for r in rows}
    if len(expected) != len(rows):
        raise ValueError("PLS explanation observation identities are duplicated.")
    coefficients = np.asarray(state["coefficients"], dtype=float)
    offset = np.asarray(state["feature_offset"], dtype=float).reshape(p)
    baseline = np.asarray(state["prediction_offset"], dtype=float).reshape(targets)
    loadings = np.asarray(state["diagnostic_state"]["reconstruction"], dtype=float).T
    if not np.array_equal(loadings, np.asarray(saved_loadings, dtype=float)):
        raise ValueError("PLS explanation loadings differ from the retained fitted output.")
    axis = populations[0].feature_axis
    labels = list(axis.labels) if axis is not None and axis.labels is not None else None
    if labels and sum(len(x) for x in labels) > MAX_BYTES // 4:
        raise ValueError("PLS explanation feature labels exceed the evidence budget.")
    count = min(20, max(1, MAX_RECORDS // (observations * targets)))
    evidence = {}
    input_digests = []
    for dataset in populations:
        require_fitted_input_identity(dataset, state["input_identity"], features=p)
        ids = list(dataset.sample_axis.labels)
        if len(set(ids)) != len(ids) or any(i in evidence or i not in expected for i in ids):
            raise ValueError("PLS explanation population identity is inconsistent.")
        input_digests.append(dataset.scientific_digest)
        for start in range(0, len(ids), 64):
            delta = np.asarray(dataset.X[start : start + 64], dtype=float) - offset
            for index, identity in enumerate(ids[start : start + 64]):
                # Allocate only p × targets for one observation, not n × p × targets.
                contributions = delta[index, :, None] * coefficients
                total = baseline + contributions.sum(axis=0)
                saved = np.asarray(expected[identity]["predicted"], dtype=float)
                scale = np.abs(baseline) + np.abs(contributions).sum(axis=0)
                if (
                    saved.shape != (targets,)
                    or not np.isfinite(contributions).all()
                    or not np.isfinite(saved).all()
                    or not np.isfinite(total).all()
                    or not np.isfinite(scale).all()
                    or not np.all(np.abs(total - saved) <= 1e-9 * np.maximum(scale, 1e-12))
                ):
                    raise ValueError("PLS contributions do not reproduce the exact retained predictions.")
                responses = []
                for target in range(targets):
                    values = contributions[:, target]
                    leading = np.sort(np.argsort(-np.abs(values), kind="stable")[:count])
                    omitted = np.ones(p, dtype=bool)
                    omitted[leading] = False
                    responses.append(
                        {
                            "variables": [[int(j), float(values[j])] for j in leading],
                            "prediction": float(saved[target]),
                            "contribution_total": float(values.sum()),
                            "omitted_signed": float(values[omitted].sum()),
                            "omitted_absolute": float(np.abs(values[omitted]).sum()),
                        }
                    )
                evidence[identity] = responses
    if set(evidence) != {r["id"] for r in rows if r["predicted"] is not None}:
        raise ValueError("PLS explanation population is incomplete.")
    profiles_available = p * (targets + components + 1) <= MAX_PROFILE_CELLS
    result = {
        "schema_version": "spectrasherpa-pls-explanations/1",
        "model_digest": model_digest,
        "source_contract_digest": source_contract_digest,
        "feature_identity": _digest(state["input_identity"]),
        "input_identity": state["input_identity"],
        "input_digests": input_digests,
        "reference_digest": _digest(reference_ids),
        "reference_count": len(reference_ids),
        "response_identity": state["response_identity"],
        "baseline": baseline.tolist(),
        "formula": "c_jr = (X_j - fitted X mean_j) B_jr; prediction_r = fitted Y mean_r + sum_j c_jr",
        "preprocessing": preprocessing,
        "internal_scale": state["scale"],
        "feature_count": p,
        "feature_labels": labels,
        "feature_values": np.asarray(axis.values).tolist() if axis is not None and axis.values is not None else None,
        "feature_units": state["feature_axis_units"] or "",
        "signal_units": state["input_identity"]["signal_units"],
        "top_per_response": count,
        "coefficients": coefficients.T.tolist() if profiles_available else None,
        "loadings": loadings.tolist() if profiles_available else None,
        "vip": state["vip_scores"] if profiles_available else None,
        "profiles_unavailable_reason": (
            None if profiles_available else "Full fitted profiles exceed the 100,000 coefficient display budget."
        ),
        "rows": evidence,
    }
    if len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError("PLS explanations exceed the 6 MiB evidence budget; sample review remains available.")
    return result
