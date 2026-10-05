from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.lib.axes import AxisInfo
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetLayoutContext,
    DomainContext,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.execution_runtime import ApplicationModelArtifactReplay
from spectra_sherpa.app.services.model_store import ModelStore
from spectra_sherpa.core.dimension_roles import DimensionRole
from spectra_sherpa.core.execution_runtime import ExecutionRuntime

# These are the runtime-ready templates reachable from the established dataset
# catalog. Exact dataset-to-template admission is covered by
# test_dataset_template_compatibility.py; this matrix executes each distinct
# numerical DAG against a scientifically shaped representative input.
NATIVE_TEMPLATE_SLUGS = frozenset(
    {
        "classification_plsda",
        "clustering_comparison",
        "hierarchical_clustering",
        "ica_decomposition",
        "knn_classification",
        "nested_cv_validation",
        "nmf_mixture_decomposition",
        "osc_target_orthogonal_correction",
        "parafac_multiway",
        "pca",
        "peak_guided_pls",
        "peaks",
        "pls_calibration",
        "preprocessing",
        "raman_processing",
        "representative_calibration",
        "simca_classification",
        "variable_selection_comparison",
        "variable_selection_pls",
        "vip_assisted_pls",
    }
)


def _template_entries() -> list[dict[str, Any]]:
    entries = [entry for entry in TemplateLoader().load_all() if entry["slug"] in NATIVE_TEMPLATE_SLUGS]
    assert {entry["slug"] for entry in entries} == NATIVE_TEMPLATE_SLUGS
    return entries


def _nonempty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, np.ndarray):
        return value.size > 0
    if isinstance(value, (list, tuple, str, bytes, dict)):
        return len(value) > 0
    return True


def _visualization_plots(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    if isinstance(value.get("data"), list):
        return [value]
    return [
        candidate
        for candidate in value.values()
        if isinstance(candidate, dict) and isinstance(candidate.get("data"), list)
    ]


def _is_table_payload(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("metadata"), dict)
        and value["metadata"].get("type") in {"records", "dict", "array"}
    )


def _presentation_problems(
    executor: DAGExecutor,
    results: dict[str, object],
) -> list[str]:
    problems: list[str] = []
    for node_id, node in executor.nodes.items():
        result = results.get(node_id)
        if not isinstance(result, dict) or node.metadata is None:
            continue
        contract = node.metadata.resolved_presentation_contract()
        if contract is None:
            continue
        for presentation in contract.presentations:
            if "plot" not in presentation.modes:
                continue
            missing = [port for port in presentation.source_ports if port not in result]
            if missing:
                problems.append(f"{node_id}:{presentation.presentation_id}: missing {missing}")
                continue
            for port in presentation.source_ports:
                if not _nonempty(result[port]):
                    problems.append(f"{node_id}:{presentation.presentation_id}: empty {port}")

            if presentation.kind != "visualization":
                continue
            source_value = result[presentation.source_ports[0]]
            if _is_table_payload(source_value):
                continue
            plots = _visualization_plots(source_value)
            if not plots:
                problems.append(f"{node_id}:{presentation.presentation_id}: no Plotly payload")
                continue
            for plot in plots:
                traces = [trace for trace in plot["data"] if isinstance(trace, dict)]
                if not traces:
                    problems.append(f"{node_id}:{presentation.presentation_id}: no traces")
                    continue
                if all(
                    trace.get("type") in {"table", "pie"} or {"header", "cells"}.issubset(trace) for trace in traces
                ):
                    continue
                layout = plot.get("layout") or {}
                if not (layout.get("xaxis") or {}).get("title"):
                    problems.append(f"{node_id}:{presentation.presentation_id}: unlabeled x-axis")
                if not (layout.get("yaxis") or {}).get("title"):
                    problems.append(f"{node_id}:{presentation.presentation_id}: unlabeled y-axis")
    return problems


def _multiway_fixture() -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(20260909)
    factors = [rng.normal(size=(length, 3)) for length in (12, 7, 31)]
    values = np.einsum("ir,jr,kr->ijk", *factors)
    target = np.linspace(0.0, 1.0, values.shape[0])
    return (
        SherpaDataset(
            values,
            sample_axis=SampleAxis(labels=[f"sample_{index + 1:03d}" for index in range(values.shape[0])]),
            feature_axis=SpectralAxis(
                values=np.linspace(400.0, 750.0, values.shape[2]),
                title="Emission wavelength",
                units="nm",
            ),
            axes={
                1: AxisInfo(
                    values=np.arange(values.shape[1]),
                    title="Excitation index",
                )
            },
            target=target,
            layout=DatasetLayoutContext(
                kind="batch",
                source_type="synthetic-eem-template-qualification",
                source_dtype=values.dtype.str,
                source_shape=values.shape,
                mode_roles=(
                    DimensionRole.SAMPLE,
                    DimensionRole.EXCITATION,
                    DimensionRole.EMISSION,
                ),
            ),
            title="PARAFAC template qualification",
        ),
        target,
    )


def _spectral_fixture(slug: str) -> tuple[SherpaDataset, np.ndarray]:
    rng = np.random.default_rng(20260909)
    n_samples, n_features = 72, 121
    axis = np.linspace(4000.0, 650.0, n_features)
    centers = (900.0, 1450.0, 1710.0, 2920.0, 3350.0)
    basis = np.vstack([np.exp(-0.5 * ((axis - center) / 45.0) ** 2) for center in centers])
    concentrations = rng.uniform(0.15, 1.2, size=(n_samples, len(centers)))
    values = concentrations @ basis + 0.03 + rng.normal(0.0, 0.002, size=(n_samples, n_features))
    continuous = 2.0 * concentrations[:, 0] - concentrations[:, 2] + 0.2 * concentrations[:, 4]
    categorical = np.asarray([f"class_{index % 3 + 1}" for index in range(n_samples)])
    target = (
        categorical if slug in {"classification_plsda", "knn_classification", "simca_classification"} else continuous
    )
    target_is_categorical = target.dtype.kind in {"U", "S", "O"}
    dataset = SherpaDataset(
        X=values,
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=[f"sample_{index + 1:03d}" for index in range(n_samples)]),
        target=target,
        target_context=TargetContext(
            target_type="categorical" if target_is_categorical else "continuous",
            target_name="class" if target_is_categorical else "response",
            target_names=["class" if target_is_categorical else "response"],
        ),
        title="Spectral template qualification",
    )
    dataset.domain = DomainContext(technique="Raman" if slug == "raman_processing" else "FTIR")
    return dataset, target


def _fixture(slug: str) -> tuple[SherpaDataset, np.ndarray]:
    return _multiway_fixture() if slug == "parafac_multiway" else _spectral_fixture(slug)


def _executor(entry: dict[str, Any], artifact_root: Path) -> DAGExecutor:
    slug = entry["slug"]
    template = entry["template_data"]
    store = ModelStore(artifact_root / slug)
    executor = DAGExecutor(
        process_pool=None,
        runtime=ExecutionRuntime(
            model_artifact_reader=store,
            model_artifact_writer=store,
            model_artifact_replay=ApplicationModelArtifactReplay(),
        ),
    )
    for raw in template["nodes"]:
        parameters = dict(raw.get("parameters") or {})
        if raw["node_type"] == "data.file_load":
            parameters = {"experiment_id": 1, "file_id": 1, "stage": "raw"}
        executor.add_node(
            WorkflowNode(
                node_id=raw["node_id"],
                node_type=raw["node_type"],
                parameters=parameters,
            )
        )
    for raw in template["edges"]:
        executor.add_edge(
            WorkflowEdge(
                from_node=raw["from_node_id"],
                to_node=raw["to_node_id"],
                from_output=raw.get("from_output", "default"),
                to_input=raw.get("to_input", "default"),
            )
        )
    return executor


@pytest.mark.parametrize("entry", _template_entries(), ids=lambda entry: entry["slug"])
@pytest.mark.asyncio
async def test_runtime_ready_template_executes_and_presents_every_node(
    entry: dict[str, Any],
    tmp_path: Path,
) -> None:
    executor = _executor(entry, tmp_path)
    dataset, target = _fixture(entry["slug"])
    executor.inject_result("data_1", {"default": dataset, "target": target})

    results = await executor.execute()

    assert set(results) == set(executor.nodes)
    assert _presentation_problems(executor, results) == []


@pytest.mark.parametrize("clip", [False, True], ids=["unmodified", "clip-before-split"])
@pytest.mark.parametrize("grouped", [False, True], ids=["ungrouped", "grouped"])
@pytest.mark.asyncio
async def test_plsda_template_preserves_sample_table_supervision_through_feature_clipping(
    tmp_path: Path,
    clip: bool,
    grouped: bool,
) -> None:
    from spectra_sherpa.app.services.dag.supervision_binding import attach_sample_table_supervision

    entry = deepcopy(next(entry for entry in _template_entries() if entry["slug"] == "classification_plsda"))
    dataset, target = _spectral_fixture(entry["slug"])
    labels = list(dataset.sample_axis.labels)
    dataset.sample_axis = SampleAxis(
        labels=labels,
        sample_table={
            "sample_id": labels,
            "class": target.tolist(),
            "batch": [index // 24 for index in range(dataset.shape[0])],
        },
    )
    dataset.meta["source_collection"] = {
        "manifest_digest": "a" * 64,
        "collection_definition_sha256": "b" * 64,
        "scientific_collection_sha256": "c" * 64,
    }
    dataset = attach_sample_table_supervision(
        dataset,
        target_column="class",
        target_type="categorical",
        group_column="batch" if grouped else None,
        node_id="data_1",
    )
    if clip:
        entry["template_data"]["nodes"].append(
            {
                "node_id": "clip_1",
                "node_type": "preprocess.clip_range",
                "parameters": {"minimum": 900.0, "maximum": 3350.0},
            }
        )
        for edge in entry["template_data"]["edges"]:
            if edge["from_node_id"] == "data_1" and edge.get("to_input") == "X":
                edge["from_node_id"] = "clip_1"
        entry["template_data"]["edges"].append(
            {
                "from_node_id": "data_1",
                "to_node_id": "clip_1",
            }
        )
    executor = _executor(entry, tmp_path)
    executor.inject_result("data_1", {"default": dataset, "target": dataset.target})

    results = await executor.execute()

    assert set(results) == set(executor.nodes)
    assert _presentation_problems(executor, results) == []
    if clip:
        clipped = results["clip_1"]["default"]
        assert clipped.shape[1] < dataset.shape[1]
        np.testing.assert_array_equal(clipped.target, dataset.target)
        assert clipped.sample_axis.sample_table == dataset.sample_axis.sample_table
