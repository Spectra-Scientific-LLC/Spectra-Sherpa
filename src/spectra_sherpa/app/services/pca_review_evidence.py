"""Exact, bounded PCA review receipts. This is presentation, never a second fit."""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib import pca_numerics
from spectra_sherpa.app.lib.sample_identity import sample_ids as declared_sample_ids
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.dag.nodes._chemometric_diagnostics import hotelling_t2_per_sample
from spectra_sherpa.app.services.dag.nodes.data.sample_preparation import _slice_dataset_rows
from spectra_sherpa.app.services.dag.nodes.diagnostics import _outlier_dispatch
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import (
    apply_pca_fitted_state,
    pca_q_residuals_in_fitted_space,
)
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode
from spectra_sherpa.app.services.dag.retained_holdout import source_replay_digest
from spectra_sherpa.sdk.runtime import execute_workflow_async, operation_workflow

SCHEMA = "spectrasherpa-pca-review/1"
SAMPLEWISE = {"preprocess.normalize", "preprocess.smooth", "preprocess.derivative"}
PREPROCESSORS = SAMPLEWISE | {"preprocess.scale"}
TERMINALS = {"diagnostics.outliers", "output.plot", "output.data_table", "stats.summary"}
MAX_SAMPLES = 5000


def filter_id(pca_id: str) -> str:
    import hashlib

    return "review_filter_" + hashlib.sha256(pca_id.encode()).hexdigest()[:20]


def review_path(definition: dict, pca_id: str) -> tuple[list[dict], dict]:
    """Admit a single-source linear calibration path; branches are presentation only."""
    if definition.get("fold_validation_plan"):
        raise ValueError("Campaign folds cannot be changed by PCA review. Create a separate analysis.")
    nodes = {n["node_id"]: n for n in definition["nodes"]}
    edges = definition["edges"]
    if pca_id in nodes and nodes[pca_id]["node_type"] == "model.fitted_pls":
        from .pls_review_evidence import review_path as pls_path

        return pls_path(definition, pca_id)
    if pca_id not in nodes or nodes[pca_id]["node_type"] != "model.pca":
        raise ValueError("Choose a fitted PCA node.")
    if sum(n["node_type"] == "model.pca" for n in nodes.values()) != 1:
        raise ValueError("Slice A requires one PCA model per workflow.")
    path, current, seen = [], pca_id, set()
    while True:
        if current in seen:
            raise ValueError("Cyclic workflow cannot be reviewed.")
        seen.add(current)
        path.insert(0, nodes[current])
        incoming = [e for e in edges if e["to_node_id"] == current]
        if not incoming:
            break
        if len(incoming) != 1 or incoming[0]["from_node_id"] not in nodes:
            raise ValueError("Slice A requires a single input chain without reference side inputs.")
        current = incoming[0]["from_node_id"]
    if path[0]["node_type"] != "data.collection_load":
        raise ValueError("Slice A requires a single-file My Dataset collection source.")
    insertion = 0
    if len(path) > 2 and path[1]["node_type"] == "data.filter_samples":
        p = path[1].get("parameters") or {}
        if p.get("field") == "source_inclusion" and not p.get("invert"):
            insertion = 1
    middle = path[insertion + 1 : -1]
    if middle and middle[0]["node_id"] == filter_id(pca_id):
        if middle[0]["node_type"] != "data.filter_samples":
            raise ValueError("Review filter identity was replaced.")
        middle = middle[1:]
    if any(n["node_type"] not in PREPROCESSORS for n in middle):
        raise ValueError("Slice A supports PCA with scale/center, normalization, smoothing and derivatives only.")
    if any(n["node_type"] not in TERMINALS for key, n in nodes.items() if key not in seen):
        raise ValueError("Split, prediction, campaign and multiple-source workflows are not eligible for Slice A.")
    # An upstream branch could refit another model or expose inconsistent cohorts.
    for n in path[:-1]:
        outgoing = [e for e in edges if e["from_node_id"] == n["node_id"]]
        if len(outgoing) != 1:
            raise ValueError("Slice A requires an unbranched source-to-PCA chain.")
    a, b = path[insertion : insertion + 2]
    edge = next(e for e in edges if e["from_node_id"] == a["node_id"] and e["to_node_id"] == b["node_id"])
    if edge.get("from_output", "default") != "default":
        raise ValueError("Review requires the canonical source dataset output.")
    return path, dict(edge)


def sample_ids(dataset: SherpaDataset) -> list[str]:
    if not isinstance(dataset, SherpaDataset) or dataset.X.ndim != 2:
        raise ValueError("Selection requires an exact two-dimensional dataset.")
    axis = dataset.get_observation_axis()
    if not isinstance(axis, SampleAxis):
        raise ValueError("Selection requires an explicit sample observation axis.")
    ids = declared_sample_ids(dataset)
    if not ids or len(ids) > MAX_SAMPLES:
        raise ValueError(
            "New reviews require unique exact typed sample_id values (at most 5,000). "
            "Attach a sample table with sample_id, or re-import with typed IDs, then rerun. "
            "Display labels are not sample IDs."
        )
    if axis.include_mask is not None and not np.asarray(axis.include_mask, dtype=bool).all():
        raise ValueError("Materialize Source Inclusion before reviewing this PCA.")
    return ids


def review_filter_parameters(excluded: list[str], *, identity_field: str = "sample_id") -> dict:
    """New reviews use typed IDs; historical custody retains its recorded field."""
    if identity_field not in {"sample_id", "sample_label"}:
        raise ValueError("Unknown review observation identity field.")
    return {
        "field": "sample_table" if identity_field == "sample_id" else "sample_label",
        **({"sample_table_column": "sample_id"} if identity_field == "sample_id" else {}),
        "filter_values": excluded,
        "invert": True,
        "match_mode": "in_list",
        "case_sensitive": True,
    }


def _dataset(results: dict, node_id: str, port: str = "default") -> SherpaDataset:
    result = results.get(node_id)
    value = result.get(port) if isinstance(result, dict) else result
    if not isinstance(value, SherpaDataset):
        raise ValueError(f"Exact dataset output is unavailable for {node_id}.")
    return value


async def build_review_receipt(definition: dict, results: dict, pca_id: str) -> dict[str, Any]:
    path, insertion_edge = review_path(definition, pca_id)
    baseline = _dataset(results, insertion_edge["from_node_id"])
    ids = sample_ids(baseline)
    collection = _dataset(results, path[0]["node_id"]).meta.get("source_collection", {})
    if len(collection.get("files", [])) != 1:
        from spectra_sherpa.app.lib.collection_assembly import verified_source_observations

        verified_source_observations(_dataset(results, path[0]["node_id"]))
    source_sha = collection.get("source_manifest_sha256") or collection.get("manifest_digest")
    if not isinstance(source_sha, str) or len(source_sha) != 64:
        raise ValueError("Source file identity is unavailable; rerun the workflow.")
    pca = results[pca_id]
    scores = _dataset(results, pca_id, "scores")
    retained_ids = sample_ids(scores)
    retained_set = set(retained_ids)
    excluded_ids = [x for x in ids if x not in retained_set]
    if retained_ids != [x for x in ids if x in retained_set]:
        raise ValueError("PCA observations do not preserve the exact source cohort order.")
    owned = next((n for n in path if n["node_id"] == filter_id(pca_id)), None)
    if excluded_ids:
        p = owned.get("parameters", {}) if owned else {}
        if (
            p.get("field") != "sample_table"
            or p.get("sample_table_column") != "sample_id"
            or p.get("invert") is not True
            or set(p.get("filter_values", [])) != set(excluded_ids)
        ):
            raise ValueError("Excluded cohort does not match the explicit review filter.")
    diagnostics, _ = _outlier_dispatch(pca["diagnostic_state"])
    model = pca["fitted_state"]
    eigenvalues = np.asarray(pca["eigenvalues"], dtype=float)
    components = scores.shape[1]
    populations = [(_dataset(results, path[-2]["node_id"]), scores.X)]
    applied: dict[str, dict] = {}
    if excluded_ids:
        projection = _slice_dataset_rows(
            baseline, baseline.X, np.asarray([i for i, identity in enumerate(ids) if identity not in retained_set])
        )
        try:
            start = next(i for i, n in enumerate(path) if n["node_id"] == filter_id(pca_id)) + 1
            for n in path[start:-1]:
                if n["node_type"] == "preprocess.scale":
                    history = _dataset(results, n["node_id"]).provenance.to_list()
                    states = [
                        s["parameters"]["transform_state"]
                        for s in history
                        if s.get("op_id") == "preprocess.scale" and s.get("node_id") == n["node_id"]
                    ]
                    if len(states) != 1:
                        raise ValueError("Exact fitted scaling state is unavailable.")
                    # Apply the exact executed state through the source ABI; never fit.
                    projection = ScaleNode(n["node_id"], n.get("parameters") or {}).apply_fitted_state(
                        projection, states[0]
                    )
                else:
                    if n["node_type"] not in SAMPLEWISE:
                        raise ValueError("Preprocessing is outside the sample-local review contract.")
                    spec, payloads, expected = operation_workflow(
                        n["node_type"], parameters=n.get("parameters") or {}, inputs={"default": projection}
                    )
                    execution = await execute_workflow_async(spec, deployment_inputs=payloads)
                    if dict(execution.dataset_content_digests) != dict(expected):
                        raise ValueError("Projection input identity changed across execution admission.")
                    projection = execution.output()
                if sample_ids(projection) != excluded_ids:
                    raise ValueError("Preprocessing changed excluded observation identity.")
            projected_scores = apply_pca_fitted_state(projection, model)
            t2 = hotelling_t2_per_sample(projected_scores, eigenvalues=eigenvalues)
            q = pca_q_residuals_in_fitted_space(projection, projected_scores, model)
            populations.append((projection, projected_scores))
            for i, identity in enumerate(excluded_ids):
                applied[identity] = {"scores": projected_scores[i].tolist(), "t2": float(t2[i]), "q": float(q[i])}
        except (ValueError, TypeError, KeyError) as exc:
            for identity in excluded_ids:
                applied[identity] = {"scores": None, "t2": None, "q": None, "projection_error": str(exc)}
    positions = {identity: i for i, identity in enumerate(retained_ids)}
    classes = baseline.sample_axis.classes
    rows = []
    for identity in ids:
        i = positions.get(identity)
        rows.append(
            {
                "id": identity,
                "role": "calibration" if i is not None else "excluded_projected",
                "group": str(classes[len(rows)]) if classes is not None else "Calibration",
                **(
                    {
                        "scores": scores.X[i].tolist(),
                        "t2": diagnostics["T2"][i],
                        "q": diagnostics["Q"][i],
                        "screened": bool(diagnostics["flags"][i]),
                    }
                    if i is not None
                    else applied[identity]
                ),
            }
        )
    from .dataset_views import review_curation_binding
    from .pls_review_evidence import spectral_display

    receipt = {
        "dataset_curation_source": review_curation_binding(
            _dataset(results, path[0]["node_id"]), path[0]["parameters"]
        ),
        "model_kind": "pca",
        "identity_field": "sample_id",
        "spectra": spectral_display(baseline),
        "schema_version": SCHEMA,
        "pca_node_id": pca_id,
        "graph_digest": compute_workflow_hash(definition["nodes"], definition["edges"]),
        "source_digest": source_replay_digest(baseline),
        "source_execution_digest": baseline.scientific_digest,
        "source_manifest_sha256": source_sha,
        "insertion_edge": insertion_edge,
        "filter_id": filter_id(pca_id),
        "rows": rows,
        "n_calibration": len(retained_ids),
        "n_components": components,
        "calibration_t2_limit": diagnostics["T2_limit"],
        "application_t2_limit": pca_numerics.hotelling_t2_limit(len(retained_ids), components, 0.95, prediction=True),
        "q_limit": diagnostics["Q_limit"],
        "q_limit_method": diagnostics["metadata"]["q_limit_method"],
        "confidence": 0.95,
        "interpretation": "Calibration screening; exclusion after inspection is adaptive model development.",
    }

    # Optional explanations must never disable the existing selection/restore loop.
    from asyncio import to_thread

    from .pca_review_explanations import build_explanations

    try:
        receipt["explanations"] = await to_thread(
            build_explanations,
            model,
            populations,
            rows,
            [n["node_type"] for n in path[1:-1] if n["node_type"] in PREPROCESSORS],
        )
        import json

        if len(json.dumps(receipt, allow_nan=False).encode()) > 15 * 1024 * 1024:
            raise ValueError("Combined explanation evidence exceeds the review display budget.")
    except (ValueError, TypeError, KeyError) as exc:
        receipt["explanations"] = {"unavailable_reason": str(exc)}
    return receipt


async def review_receipts(definition: dict, results: dict, *, unavailable_reason: str | None = None) -> dict[str, Any]:
    receipts = {}
    for n in definition.get("nodes", []):
        if n["node_type"] not in {"model.pca", "model.fitted_pls"} or n["node_id"] not in results:
            continue
        if unavailable_reason:
            receipts[n["node_id"]] = {"unavailable_reason": unavailable_reason}
            continue
        try:
            if n["node_type"] == "model.fitted_pls":
                from .pls_review_evidence import build_review_receipt as pls_receipt

                receipts[n["node_id"]] = await pls_receipt(definition, results, n["node_id"])
            else:
                receipts[n["node_id"]] = await build_review_receipt(definition, results, n["node_id"])
        except (ValueError, KeyError, TypeError) as exc:
            receipts[n["node_id"]] = {"unavailable_reason": str(exc)}
    return receipts
