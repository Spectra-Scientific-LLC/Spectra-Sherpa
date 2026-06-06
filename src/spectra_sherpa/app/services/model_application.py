"""Apply persisted model artifacts to durable project datasets."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset
from spectra_sherpa.app.lib.adapters.scp_extractors import EXTRACT_REGISTRY
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.services.dag.nodes.data.loaders import MyDatasetNode
from spectra_sherpa.app.services.experiments import experiment_dir
from spectra_sherpa.app.services.model_store import ModelArtifactIntegrityError, get_model_store

logger = logging.getLogger(__name__)


@dataclass
class LoadedProjectDataset:
    dataset: SherpaDataset
    experiment_id: int
    experiment_name: str
    project_id: int | None
    file_ids: list[int]
    stage: str


async def load_project_dataset(
    session: AsyncSession,
    *,
    user_id: int,
    experiment_id: int,
    stage: str = "raw",
    file_id: int | None = None,
) -> LoadedProjectDataset:
    """Load a user-owned My Dataset experiment as a SherpaDataset."""
    exp_result = await session.execute(
        select(Experiment).where(Experiment.id == experiment_id, Experiment.user_id == user_id)
    )
    experiment = exp_result.scalar_one_or_none()
    if experiment is None:
        raise ValueError("Dataset not found")

    files_query = select(ExperimentFile).where(ExperimentFile.experiment_id == experiment_id)
    if file_id is not None:
        files_query = files_query.where(ExperimentFile.id == file_id)
    else:
        files_query = files_query.where(ExperimentFile.stage == stage)
    files_query = files_query.order_by(ExperimentFile.id)

    files = list((await session.execute(files_query)).scalars().all())
    if not files and file_id is None and stage == "raw":
        synthetic_query = (
            select(ExperimentFile)
            .where(ExperimentFile.experiment_id == experiment_id, ExperimentFile.stage == "synthetic")
            .order_by(ExperimentFile.id)
        )
        files = list((await session.execute(synthetic_query)).scalars().all())
        if files:
            stage = "synthetic"

    if not files:
        raise ValueError("Dataset has no files for the requested scope")

    base_dir = experiment_dir(experiment_id)
    helper = MyDatasetNode("model_apply_dataset_loader", {"dataset_id": experiment_id})
    loaded = []
    for file in files:
        path = base_dir / file.file_path
        if not path.exists():
            raise ValueError(f"Dataset file is missing from storage: {file.file_path}")
        loaded.append(helper._load_file(str(path), file_name=file.file_path))

    dataset = _loaded_files_to_sherpa(helper, loaded, experiment.name)
    return LoadedProjectDataset(
        dataset=dataset,
        experiment_id=experiment_id,
        experiment_name=experiment.name,
        project_id=experiment.project_id,
        file_ids=[int(file.id) for file in files],
        stage=stage,
    )


def _loaded_files_to_sherpa(helper: MyDatasetNode, loaded: list[Any], experiment_name: str) -> SherpaDataset:
    groups = helper._group_by_x_axis(loaded)
    groups.sort(key=lambda group: helper._x_length(group[0].dataset), reverse=True)
    spectra_group = groups[0]
    prop_groups = groups[1:]
    embedded_target = helper._combine_embedded_targets(spectra_group)

    spectra_datasets = [item.dataset for item in spectra_group]
    spectra_names = [item.file_name for item in spectra_group]
    spectra = helper._concatenate(spectra_datasets, spectra_names) if len(spectra_datasets) > 1 else spectra_datasets[0]
    spectra.title = f"{experiment_name} ({len(spectra_datasets)} file{'s' if len(spectra_datasets) != 1 else ''})"

    target = None
    if embedded_target is not None:
        target_data, target_names, target_units = embedded_target
        target = (target_data, target_names, target_units)
    elif prop_groups:
        all_props: list[Any] = []
        all_names: list[str] = []
        for group in prop_groups:
            for item in group:
                all_props.append(item.dataset)
                all_names.append(item.file_name)
        target_ds = helper._concatenate(all_props, all_names) if len(all_props) > 1 else all_props[0]
        target_data = np.asarray(target_ds.data, dtype=np.float64)
        target_names = None
        if hasattr(target_ds, "x") and getattr(target_ds.x, "labels", None) is not None:
            target_names = list(target_ds.x.labels)
        target = (target_data, target_names or [], None)

    spectra_out = spectra if isinstance(spectra, SherpaDataset) else from_nddataset(spectra)
    if not isinstance(spectra_out, SherpaDataset):
        raise ValueError("Dataset loader did not return a SherpaDataset")

    if target is not None:
        target_data, target_names, target_units = target
        spectra_out.target = target_data
        is_cat = np.asarray(target_data).dtype.kind in ("U", "S", "O")
        spectra_out.target_context = TargetContext(
            target_type="categorical" if is_cat else "continuous",
            target_names=list(target_names) if target_names else None,
            target_units=target_units,
        )
    return spectra_out


def apply_model_to_dataset(
    artifact_uid: str,
    dataset: SherpaDataset,
    *,
    scope: str = "all",
) -> dict[str, Any]:
    """Apply one model artifact to a SherpaDataset and return comparable output."""
    store = get_model_store()
    try:
        manifest, arrays = store.load(artifact_uid)
    except FileNotFoundError as exc:
        raise ValueError(f"Model artifact not found: {artifact_uid}") from exc
    except ModelArtifactIntegrityError as exc:
        raise ValueError(f"Model artifact is corrupt: {exc}") from exc

    model_type = str(manifest.get("model_type", ""))
    extract_cls = EXTRACT_REGISTRY.get(model_type)
    if extract_cls is None:
        raise ValueError(f"Unsupported model type: {model_type!r}")

    X = np.asarray(dataset.X, dtype=np.float64)
    if X.ndim == 1:
        X = X.reshape(1, -1)
    y = np.asarray(dataset.target) if dataset.target is not None else None

    validate_feature_contract(X, dataset, manifest)
    X_scoped, y_scoped, sample_indices, warnings = _prepare_X_for_artifact(X, y, manifest, scope=scope)
    X_ready, feature_warning = _apply_feature_mask(X_scoped, dataset, manifest)
    warnings.extend(feature_warning)
    validate_prepared_feature_contract(X_ready, manifest)

    extract = extract_cls.from_artifact(manifest, arrays)  # type: ignore[attr-defined]
    response: dict[str, Any] = {
        "artifact_uid": artifact_uid,
        "model_type": model_type,
        "scope": scope,
        "sample_indices": sample_indices.tolist(),
        "n_samples": int(X_ready.shape[0]),
        "warnings": warnings,
        "metadata": {
            "classes": list(getattr(extract, "classes", manifest.get("classes", [])) or []),
            "preprocessing_chain": manifest.get("preprocessing_chain", []),
            "training_data_hash": manifest.get("training_data_hash"),
        },
    }

    if hasattr(extract, "predict") and model_type in {"plsda", "knn", "simca"}:
        labels, probabilities = extract.predict(X_ready)
        labels_list = [str(label) for label in list(labels)]
        response["predictions"] = labels_list
        response["probabilities"] = np.asarray(probabilities, dtype=np.float64).tolist()
        if y_scoped is not None:
            y_true = [str(label) for label in y_scoped.tolist()]
            response["true_labels"] = y_true
            response["metrics"] = _classification_metrics(y_true, labels_list, response["metadata"]["classes"])
        else:
            response["metrics"] = None
        return response

    if hasattr(extract, "predict"):
        predicted = extract.predict(X_ready)
        predicted_arr = np.asarray(predicted, dtype=np.float64)
        response["predictions"] = predicted_arr.tolist()
        response["metrics"] = _regression_metrics(y_scoped, predicted_arr) if y_scoped is not None else None
        applicability = _applicability_diagnostics(extract, X_ready)
        if applicability is not None:
            response["applicability"] = applicability
            n_out = int(applicability.get("n_out_of_domain", 0) or 0)
            if n_out:
                response["warnings"].append(
                    f"{n_out} sample{'s' if n_out != 1 else ''} outside saved model applicability domain"
                )
        return response

    if hasattr(extract, "transform"):
        transformed = extract.transform(X_ready)
        response["transformed"] = np.asarray(transformed).tolist()
        response["metrics"] = None
        return response

    raise ValueError(f"Model type {model_type!r} cannot be applied")


def _applicability_diagnostics(extract: Any, X_ready: np.ndarray) -> dict[str, Any] | None:
    diagnostics_fn = getattr(extract, "applicability_diagnostics", None)
    if not callable(diagnostics_fn):
        return None
    diagnostics = diagnostics_fn(X_ready)
    if not isinstance(diagnostics, dict):
        return None
    return diagnostics


def compare_models_on_dataset(
    artifact_uids: list[str],
    dataset: SherpaDataset,
    *,
    scope: str = "all",
) -> dict[str, Any]:
    results = [apply_model_to_dataset(uid, dataset, scope=scope) for uid in artifact_uids]
    comparison: dict[str, Any] = {
        "scope": scope,
        "models": results,
        "pairwise": [],
    }
    if len(results) >= 2 and all("predictions" in result for result in results):
        base = results[0]
        base_pred = list(base["predictions"])
        for other in results[1:]:
            other_pred = list(other["predictions"])
            n = min(len(base_pred), len(other_pred))
            disagreements = [i for i in range(n) if base_pred[i] != other_pred[i]]
            comparison["pairwise"].append(
                {
                    "left_artifact_uid": base["artifact_uid"],
                    "right_artifact_uid": other["artifact_uid"],
                    "n_compared": n,
                    "n_disagreements": len(disagreements),
                    "disagreement_fraction": len(disagreements) / n if n else 0.0,
                    "disagreement_indices": disagreements[:1000],
                    "truncated": len(disagreements) > 1000,
                }
            )
    return comparison


def _prepare_X_for_artifact(
    X: np.ndarray,
    y: np.ndarray | None,
    manifest: dict[str, Any],
    *,
    scope: str,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray, list[str]]:
    warnings: list[str] = []
    chain = manifest.get("preprocessing_chain") or []
    partition = _find_partition_step(chain)
    indices = np.arange(X.shape[0])
    if scope in {"train", "test"}:
        if partition is None:
            raise ValueError(f"Model artifact does not contain train/test partition provenance for scope={scope!r}")
        key = "train_indices" if scope == "train" else "test_indices"
        indices = np.asarray(partition.get(key) or [], dtype=np.int64)
        if indices.size == 0:
            raise ValueError(f"Model artifact does not contain {key}")
        if int(indices.max()) >= X.shape[0] or int(indices.min()) < 0:
            raise ValueError("Stored partition indices do not match this dataset")

    X_work = X[indices]
    y_work = y[indices] if y is not None else None

    for step in chain:
        op_id = step.get("op_id")
        params = step.get("parameters", {})
        if op_id in {"selection.sample_partition"} or str(op_id).startswith("data."):
            continue
        if str(op_id).startswith("model."):
            continue
        if op_id == "preprocess.scale":
            state = params.get("transform_state")
            if isinstance(state, dict):
                X_work = _apply_scale_state(X_work, state)
            else:
                raise ValueError(
                    "preprocess.scale has no replayable transform_state; re-train the model with a current "
                    "SpectraSherpa version or apply the same preprocessing upstream before Load & Apply"
                )
            continue
        if op_id == "preprocess.normalize":
            X_work = _apply_normalize_step(X_work, params)
            continue
        if op_id == "preprocess.emsc":
            X_work = _apply_emsc_step(X_work, params)
            continue
        if op_id == "preprocess.smooth":
            X_work = _apply_smooth_step(X_work, params)
            continue
        if op_id == "preprocess.derivative":
            X_work = _apply_derivative_step(X_work, params)
            continue
        if op_id == "baseline.penalized_ls":
            X_work = _apply_penalized_baseline_step(X_work, params)
            continue
        if op_id == "baseline.rubberband":
            raise ValueError(
                "baseline.rubberband is recorded in the model preprocessing chain but is not replayable "
                "in artifact application. Apply the same rubberband correction upstream before Load & Apply, "
                "or re-train with a replayable baseline method."
            )
        if op_id == "preprocess.osc":
            raise ValueError(
                "preprocess.osc is recorded in the model preprocessing chain but its fitted OSC projection "
                "state was not persisted. Re-train without OSC in the deploy path or apply a validated OSC "
                "transform before Load & Apply."
            )
        if str(op_id).startswith(("preprocess.", "baseline.")):
            raise ValueError(f"Preprocessing step {op_id!r} is recorded but not replayed by model apply")
        warnings.append(f"Processing step {op_id!r} is recorded but not replayed by model apply")

    return X_work, y_work, indices, warnings


def _regression_metrics(y_true: np.ndarray | None, y_pred: np.ndarray) -> dict[str, Any] | None:
    if y_true is None:
        return None
    true = np.asarray(y_true, dtype=np.float64)
    pred = np.asarray(y_pred, dtype=np.float64)
    if true.ndim == 1:
        true = true.reshape(-1, 1)
    if pred.ndim == 1:
        pred = pred.reshape(-1, 1)
    if true.shape != pred.shape or true.size == 0:
        return None

    finite = np.isfinite(true) & np.isfinite(pred)
    per_target: list[dict[str, float | None]] = []
    residuals_all: list[np.ndarray] = []
    for target_idx in range(true.shape[1]):
        mask = finite[:, target_idx]
        if not np.any(mask):
            per_target.append({"rmsep": None, "r2": None, "bias": None, "sep": None})
            continue
        t = true[mask, target_idx]
        p = pred[mask, target_idx]
        residual = t - p
        residuals_all.append(residual)
        rmsep = float(np.sqrt(np.mean(residual**2)))
        bias = float(np.mean(residual))
        sep = float(np.std(residual, ddof=1)) if residual.size > 1 else 0.0
        ss_tot = float(np.sum((t - np.mean(t)) ** 2))
        r2 = float(1.0 - np.sum(residual**2) / ss_tot) if ss_tot > 0 else None
        per_target.append({"rmsep": rmsep, "r2": r2, "bias": bias, "sep": sep})

    if not residuals_all:
        return None

    all_residual = np.concatenate(residuals_all)
    metrics: dict[str, Any] = {
        "rmsep": float(np.sqrt(np.mean(all_residual**2))),
        "bias": float(np.mean(all_residual)),
        "sep": float(np.std(all_residual, ddof=1)) if all_residual.size > 1 else 0.0,
        "n_evaluated": int(all_residual.size),
    }
    if len(per_target) == 1:
        metrics["r2"] = per_target[0]["r2"]
    else:
        r2_values = [item["r2"] for item in per_target if item["r2"] is not None]
        metrics["r2"] = float(np.mean(r2_values)) if r2_values else None
        metrics["per_target"] = per_target
    return metrics


def _find_partition_step(chain: list[dict[str, Any]]) -> dict[str, Any] | None:
    for step in chain:
        if step.get("op_id") == "selection.sample_partition":
            params = step.get("parameters")
            return params if isinstance(params, dict) else None
    return None


def _apply_scale_state(X: np.ndarray, state: dict[str, Any]) -> np.ndarray:
    method = state.get("method")
    if method == "mean_center":
        return X - np.asarray(state["mean"], dtype=np.float64)
    if method in {"autoscale", "pareto"}:
        out = X
        mean = state.get("mean")
        if mean is not None:
            out = out - np.asarray(mean, dtype=np.float64)
        return out / np.asarray(state["scale"], dtype=np.float64)
    if method == "scale_max":
        target_max = float(state.get("target_max", 1.0))
        denom = np.max(np.abs(X), axis=1, keepdims=True)
        denom[(denom == 0) | ~np.isfinite(denom)] = 1.0
        return X / denom * target_max
    raise ValueError(f"Unsupported scale transform_state method: {method!r}")


def _apply_normalize_step(X: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_scale_nodes import _normalize_dispatch

    method = params.get("method", "snv")
    state = params.get("transform_state")
    if isinstance(state, dict):
        state_method = state.get("method", method)
        if state_method == "msc":
            reference = np.asarray(state.get("reference_spectrum"), dtype=np.float64)
            if reference.ndim != 1 or reference.shape[0] != X.shape[1]:
                raise ValueError(
                    "preprocess.normalize(method='msc') transform_state does not match supplied feature count"
                )
            return _apply_msc_reference(X, reference)
        if state_method in {"snv", "scale"}:
            method = state_method
            if method == "scale":
                return _normalize_dispatch(
                    X,
                    method="scale",
                    scale_method=state.get("scale_method", params.get("scale_method", "max")),
                )
    if method == "msc":
        raise ValueError(
            "preprocess.normalize(method='msc') is recorded but not replayed by model apply "
            "because the fitted MSC reference spectrum was not persisted"
        )
    return _normalize_dispatch(
        X,
        method=method,
        reference=params.get("reference", "mean"),
        scale_method=params.get("scale_method", "max"),
    )


def _apply_msc_reference(X: np.ndarray, reference: np.ndarray) -> np.ndarray:
    A = np.vstack([reference, np.ones(reference.shape[0], dtype=np.float64)]).T
    corrected = np.zeros_like(X, dtype=np.float64)
    for i in range(X.shape[0]):
        m, c = np.linalg.lstsq(A, X[i], rcond=None)[0]
        corrected[i] = (X[i] - c) / m if abs(m) > 1e-10 else X[i]
    return corrected


def _apply_emsc_step(X: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    state = params.get("transform_state")
    if not isinstance(state, dict):
        raise ValueError(
            "preprocess.emsc has no replayable transform_state; re-train the model with a current "
            "SpectraSherpa version or apply EMSC upstream before Load & Apply"
        )
    reference = np.asarray(state.get("reference_spectrum"), dtype=np.float64)
    if reference.ndim != 1 or reference.shape[0] != X.shape[1]:
        raise ValueError("preprocess.emsc transform_state does not match supplied feature count")
    poly_order = int(state.get("poly_order", params.get("poly_order", 2)))
    constituents_raw = state.get("constituents")
    constituents = None
    if constituents_raw is not None:
        constituents = np.asarray(constituents_raw, dtype=np.float64)
        if constituents.ndim == 1:
            constituents = constituents.reshape(1, -1)
        if constituents.ndim != 2 or constituents.shape[1] != X.shape[1]:
            raise ValueError("preprocess.emsc constituent transform_state does not match supplied feature count")

    n_features = X.shape[1]
    x_axis = np.arange(n_features, dtype=np.float64)
    x_norm = (x_axis - x_axis.mean()) / x_axis.std() if n_features > 1 else x_axis
    design_cols: list[np.ndarray] = [x_norm**deg for deg in range(poly_order + 1)]
    ref_col_idx = len(design_cols)
    design_cols.append(reference)
    if constituents is not None:
        design_cols.extend(constituents[k] for k in range(constituents.shape[0]))
    design = np.column_stack(design_cols)
    baseline_cols = [j for j in range(design.shape[1]) if j != ref_col_idx]
    corrected = np.zeros_like(X, dtype=np.float64)
    for i, spectrum in enumerate(X):
        coef, _, _, _ = np.linalg.lstsq(design, spectrum, rcond=None)
        if baseline_cols:
            baseline = design[:, baseline_cols] @ coef[baseline_cols]
            corrected[i] = (spectrum - baseline) / coef[ref_col_idx] if abs(coef[ref_col_idx]) > 1e-8 else spectrum
        else:
            corrected[i] = spectrum / coef[ref_col_idx] if abs(coef[ref_col_idx]) > 1e-8 else spectrum
    return corrected


def _apply_penalized_baseline_step(X: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    from spectra_sherpa.app.lib.preprocessing import baseline_penalized_ls

    return baseline_penalized_ls(
        X,
        method=params.get("method", "als"),
        lam=float(params.get("lam", 1e5)),
        p=float(params.get("p", 0.001)),
        max_iter=int(params.get("max_iter", 50)),
        tol=float(params.get("tol", 1e-6)),
    )


def _apply_smooth_step(X: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_deriv_nodes import _smooth_dispatch

    return _smooth_dispatch(
        X,
        method=params.get("method", "savitzky_golay"),
        size=int(params.get("size", 11)),
        order=int(params.get("order", 2)),
        lam=float(params.get("lam", 1e2)),
        d=str(params.get("d", "2")),
        sigma=float(params.get("sigma", 2.0)),
    )


def _apply_derivative_step(X: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_deriv_nodes import _derivative_dispatch

    return _derivative_dispatch(
        X,
        method=params.get("method", "savitzky_golay"),
        deriv=str(params.get("deriv", "1")),
        size=int(params.get("size", 11)),
        order=int(params.get("order", 2)),
        gap=int(params.get("gap", 5)),
        segment=int(params.get("segment", 5)),
    )


def _apply_feature_mask(
    X: np.ndarray,
    dataset: SherpaDataset,
    manifest: dict[str, Any],
) -> tuple[np.ndarray, list[str]]:
    feature_mask = manifest.get("feature_mask")
    if feature_mask is None:
        return X, []
    mask = np.asarray(feature_mask, dtype=bool)
    selected_count = int(mask.sum())
    if mask.size == X.shape[1]:
        return X[:, mask], [f"Applied saved feature mask ({mask.size} -> {selected_count} features)"]
    if selected_count == X.shape[1]:
        return X, []
    raise ValueError(
        "Feature mask mismatch: model artifact mask does not match supplied dataset feature count "
        f"(mask={mask.size}, selected={selected_count}, supplied={X.shape[1]})"
    )


def validate_prepared_feature_contract(X: np.ndarray, manifest: dict[str, Any]) -> None:
    """Validate the final matrix shape after preprocessing and feature replay."""
    expected_features = manifest.get("n_features")
    if expected_features is None:
        return
    expected = int(expected_features)
    supplied = int(X.shape[1])
    if supplied != expected:
        raise ValueError(f"Feature count mismatch after preprocessing replay: model expects {expected}, got {supplied}")


def validate_feature_contract(
    X: np.ndarray,
    dataset: SherpaDataset | Any,
    manifest: dict[str, Any],
) -> None:
    """Hard-fail if an artifact is applied to incompatible feature space.

    Artifact application is operationally dangerous when the feature axis drifts:
    the model can still produce numbers, but they are chemically meaningless.
    This guard validates feature count, stored selection masks, axis values, and
    units whenever those contracts are present in the manifest.
    """
    expected_raw = manifest.get("n_features")
    if expected_raw is None:
        return
    expected_features = int(expected_raw)
    supplied_features = int(X.shape[1])

    feature_mask = manifest.get("feature_mask")
    mask: np.ndarray | None = None
    axis_masked = False
    if feature_mask is not None:
        mask = np.asarray(feature_mask, dtype=bool)
        if supplied_features == expected_features:
            axis_masked = False
        elif mask.size == supplied_features and int(mask.sum()) == expected_features:
            axis_masked = True
        else:
            raise ValueError(
                "Feature-contract mismatch: artifact expects "
                f"{expected_features} selected features from a {mask.size}-feature source, "
                f"but dataset has {supplied_features} features"
            )
    elif supplied_features != expected_features:
        raise ValueError(
            f"Feature count mismatch: artifact expects {expected_features} features, "
            f"but dataset has {supplied_features}"
        )

    expected_axis = manifest.get("feature_axis")
    if expected_axis is None:
        return
    expected_values = np.asarray(expected_axis, dtype=np.float64)
    if expected_values.size != expected_features:
        raise ValueError(
            "Feature-contract mismatch: artifact manifest has "
            f"{expected_values.size} feature-axis points for {expected_features} features"
        )

    if not isinstance(dataset, SherpaDataset):
        raise ValueError("Feature-contract mismatch: dataset has no typed feature axis for artifact validation")

    axis = dataset.get_feature_axis()
    if axis is None or axis.values is None:
        raise ValueError("Feature-contract mismatch: dataset has no feature-axis values")

    actual_values = np.asarray(axis.values, dtype=np.float64)
    if mask is not None and mask.size == actual_values.size and int(mask.sum()) == expected_features:
        # For non-contiguous variable selections, compare selected coordinates
        # as actual_wn[mask], not actual_wn[:len(selected)].
        actual_values = actual_values[mask]
    elif axis_masked:
        raise ValueError(
            "Feature-contract mismatch: artifact feature mask cannot be applied to dataset feature-axis values"
        )

    if actual_values.size != expected_values.size:
        raise ValueError(
            "Feature-contract mismatch: dataset feature-axis length "
            f"{actual_values.size} does not match artifact length {expected_values.size}"
        )
    if not np.allclose(actual_values, expected_values, rtol=1e-6, atol=1e-6, equal_nan=False):
        raise ValueError("Feature-contract mismatch: dataset feature-axis values differ from the artifact")

    expected_units = manifest.get("feature_axis_units")
    if expected_units:
        actual_units = getattr(axis, "units", None)
        if not actual_units:
            raise ValueError("Feature-contract mismatch: dataset feature-axis units are missing")
        if _normalize_unit(str(actual_units)) != _normalize_unit(str(expected_units)):
            raise ValueError(
                "Feature-contract mismatch: dataset feature-axis units "
                f"{actual_units!r} differ from artifact units {expected_units!r}"
            )


def _normalize_unit(value: str) -> str:
    return value.strip().lower().replace(" ", "").replace("cm^-1", "cm-1").replace("cm⁻¹", "cm-1")


def _classification_metrics(y_true: list[str], y_pred: list[str], classes: list[str]) -> dict[str, Any]:
    from sklearn.metrics import (
        accuracy_score,
        balanced_accuracy_score,
        classification_report,
        confusion_matrix,
        f1_score,
    )

    labels = [str(cls) for cls in classes] if classes else sorted(set(y_true) | set(y_pred))
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro")),
        "classes": labels,
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "classification_report": classification_report(
            y_true,
            y_pred,
            labels=labels,
            output_dict=True,
            zero_division=0,
        ),
    }
