"""One-path workflow export and numerical round-trip qualification."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.notebook_export import generate_notebook
from spectra_sherpa.app.services.prepared_data import PreparedDataOverrides
from spectra_sherpa.app.services.python_export import (
    build_canonical_executable_export,
    generate_python_code,
    validate_export,
)
from spectra_sherpa.app.services.workflow_export_context import (
    BundledSourceFile,
    SourceExportSpec,
    WorkflowExportContext,
)
from spectra_sherpa.core.execution_runtime import ExecutionRuntime, ResolvedExperimentFile

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "data" / "templates"


def _load_template(name: str) -> dict:
    return yaml.safe_load((TEMPLATE_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def _template_to_workflow(template: dict) -> SimpleNamespace:
    body = template["template_data"]
    return SimpleNamespace(
        name=template["name"],
        description=template.get("description", ""),
        integrity_hash="template-roundtrip",
        nodes=[
            SimpleNamespace(
                node_id=node["node_id"],
                node_type=node["node_type"],
                parameters=dict(node.get("parameters") or {}),
            )
            for node in body["nodes"]
        ],
        edges=[
            SimpleNamespace(
                from_node_id=edge["from_node_id"],
                to_node_id=edge["to_node_id"],
                from_output=edge.get("from_output") or "default",
                to_input=edge.get("to_input") or "default",
            )
            for edge in body["edges"]
        ],
    )


ALL_TEMPLATES = sorted(path.stem for path in TEMPLATE_DIR.glob("*.yaml") if not path.stem.startswith("_"))


def _context_for_sources(workflow: SimpleNamespace, tmp_path: Path) -> WorkflowExportContext:
    specs: dict[str, SourceExportSpec] = {}
    for node in workflow.nodes:
        if node.node_type != "data.file_load":
            continue
        source = tmp_path / f"{node.node_id}.csv"
        source.write_text("target,1000,1001\n1,1,2\n2,2,4\n", encoding="utf-8")
        specs[node.node_id] = SourceExportSpec(
            node_id=node.node_id,
            source="experiment",
            loader_mode="single_file",
            overrides=PreparedDataOverrides(),
            bundle_files=(
                BundledSourceFile(
                    absolute_path=source,
                    source_relative_path=source.name,
                    bundle_relative_path=f"{node.node_id}/{source.name}",
                ),
            ),
        )
    return WorkflowExportContext(source_specs=specs)


@pytest.mark.parametrize("template_name", ALL_TEMPLATES)
def test_template_projects_to_one_admitted_canonical_workflow(template_name: str, tmp_path: Path) -> None:
    workflow = _template_to_workflow(_load_template(template_name))
    context = _context_for_sources(workflow, tmp_path)

    assert validate_export(workflow, context) == []
    projected = build_canonical_executable_export(workflow, export_context=context)
    original_types = {node.node_id: node.node_type for node in workflow.nodes}
    projected_types = {node["node_id"]: node["node_type"] for node in projected.workflow.payload["nodes"]}
    assert projected_types == {
        node_id: "deploy.input" if node_type == "data.file_load" else node_type
        for node_id, node_type in original_types.items()
    }
    assert len(projected.workflow.payload["edges"]) == len(workflow.edges)


@pytest.mark.parametrize("template_name", ALL_TEMPLATES)
def test_template_python_export_is_declarative_and_syntax_valid(template_name: str, tmp_path: Path) -> None:
    workflow = _template_to_workflow(_load_template(template_name))
    code = generate_python_code(workflow, export_context=_context_for_sources(workflow, tmp_path))

    ast.parse(code)
    assert "WorkflowSpec.from_dict" in code
    assert code.count("ss.runtime.execute_workflow(") == 1
    assert "using standalone export" not in code
    assert "generate_python" not in code
    assert "sklearn." not in code


@pytest.mark.parametrize("template_name", ALL_TEMPLATES)
def test_template_notebook_wraps_the_same_canonical_runtime(template_name: str, tmp_path: Path) -> None:
    workflow = _template_to_workflow(_load_template(template_name))
    notebook = generate_notebook(workflow, export_context=_context_for_sources(workflow, tmp_path))

    assert set(notebook) == {"nbformat", "nbformat_minor", "metadata", "cells"}
    assert notebook["nbformat"] == 4
    assert notebook["nbformat_minor"] == 5
    assert isinstance(notebook["metadata"], dict)
    assert isinstance(notebook["cells"], list)
    for cell in notebook["cells"]:
        assert cell["cell_type"] in {"code", "markdown"}
        assert isinstance(cell["source"], list)
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]))
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
    assert source.count("ss.runtime.execute_workflow(") == 1
    assert "generate_python" not in source


class _Resolver:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def resolve_experiment_file(self, **_identity: object) -> ResolvedExperimentFile:
        return ResolvedExperimentFile(
            path=str(self.path),
            original_file_path=self.path.name,
            created_datetime="2026-08-17T00:00:00Z",
        )


class _ArtifactWriter:
    def save(self, artifact_uid: str, manifest: dict, arrays: dict) -> str:
        del artifact_uid, manifest
        payload = io.BytesIO()
        np.savez_compressed(payload, **arrays)
        return hashlib.sha256(payload.getvalue()).hexdigest()

    def artifact_directory(self, artifact_uid: str) -> str:
        return f"memory://export-roundtrip/{artifact_uid}"


def _pls_workflow() -> SimpleNamespace:
    return SimpleNamespace(
        name="PLS export parity",
        description="",
        integrity_hash="pls-export-parity",
        nodes=[
            SimpleNamespace(
                node_id="source",
                node_type="data.file_load",
                parameters={
                    "experiment_id": 1,
                    "file_id": 2,
                    "stage": "raw",
                    "target_authority": {
                        "schema_version": "spectrasherpa-target-authority/1",
                        "column": "target",
                        "target_type": "continuous",
                        "units": None,
                        "source_digest": hashlib.sha256(_pls_source_bytes()).hexdigest(),
                    },
                },
            ),
            SimpleNamespace(
                node_id="pls",
                node_type="model.fitted_pls",
                parameters={"n_components": 2, "scale": True},
            ),
        ],
        edges=[
            SimpleNamespace(from_node_id="source", to_node_id="pls", from_output="default", to_input="default"),
            SimpleNamespace(from_node_id="source", to_node_id="pls", from_output="target", to_input="y"),
        ],
    )


def _pls_source_bytes() -> bytes:
    rows = ["target,1000,1001,1002,1003"]
    for index in range(1, 13):
        rows.append(f"{2.5 * index},{index},{index**2},{index + 3},{0.5 * index}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _write_pls_csv(path: Path) -> None:
    path.write_bytes(_pls_source_bytes())


def _pls_context(path: Path) -> WorkflowExportContext:
    return WorkflowExportContext(
        source_specs={
            "source": SourceExportSpec(
                node_id="source",
                source="experiment",
                loader_mode="single_file",
                overrides=PreparedDataOverrides(
                    target_column="target",
                    selected_target="target",
                    target_type="continuous",
                    target_mode="single",
                ),
                bundle_files=(
                    BundledSourceFile(
                        absolute_path=path,
                        source_relative_path=path.name,
                        bundle_relative_path="source/pls.csv",
                    ),
                ),
            )
        }
    )


def _execute_workbench(workflow: SimpleNamespace, source: Path) -> dict:
    executor = DAGExecutor(
        runtime=ExecutionRuntime(
            dataset_source_resolver=_Resolver(source),
            model_artifact_writer=_ArtifactWriter(),
        )
    )
    for node in workflow.nodes:
        executor.add_node(WorkflowNode(node.node_id, node.node_type, dict(node.parameters)))
    for edge in workflow.edges:
        executor.add_edge(WorkflowEdge(edge.from_node_id, edge.to_node_id, edge.from_output, edge.to_input))
    return asyncio.run(executor.execute())


def test_exported_pls_matches_the_original_workbench_dag(tmp_path: Path, monkeypatch) -> None:
    workflow = _pls_workflow()
    source = tmp_path / "pls.csv"
    _write_pls_csv(source)
    context = _pls_context(source)
    expected = _execute_workbench(workflow, source)

    bundle = tmp_path / "source" / "pls.csv"
    bundle.parent.mkdir()
    bundle.write_bytes(source.read_bytes())
    monkeypatch.setenv("SHERPA_DATA_DIR", str(tmp_path))
    code = generate_python_code(workflow, export_context=context)
    namespace = {"__file__": str(tmp_path / "workflow.py"), "__name__": "export_test"}
    exec(compile(code, "<canonical-export>", "exec"), namespace)
    actual = namespace["run_workflow"]()

    np.testing.assert_allclose(actual["pls"]["default"], expected["pls"]["default"], rtol=0, atol=1e-12)
    assert actual["pls"]["fitted_state"] == expected["pls"]["fitted_state"]


def test_export_rejects_modified_bundled_source_before_parsing(tmp_path: Path, monkeypatch) -> None:
    workflow = _pls_workflow()
    source = tmp_path / "pls.csv"
    _write_pls_csv(source)
    code = generate_python_code(workflow, export_context=_pls_context(source))
    bundle = tmp_path / "source" / "pls.csv"
    bundle.parent.mkdir()
    bundle.write_text("target,1000\n1,999\n", encoding="utf-8")
    monkeypatch.setenv("SHERPA_DATA_DIR", str(tmp_path))
    namespace = {"__file__": str(tmp_path / "workflow.py"), "__name__": "export_test"}
    exec(compile(code, "<canonical-export>", "exec"), namespace)

    with pytest.raises(ValueError, match="source (size|digest) mismatch"):
        namespace["run_workflow"]()


def test_exported_workflow_requires_exact_external_stream_set() -> None:
    workflow = SimpleNamespace(
        name="Deployment",
        description="",
        nodes=[
            SimpleNamespace(
                node_id="input",
                node_type="deploy.input",
                parameters={"stream_name": "sample", "schema_version": "spectrasherpa.deploy-input/1"},
            )
        ],
        edges=[],
        integrity_hash="deployment",
    )
    code = generate_python_code(workflow)
    namespace = {"__name__": "export_test"}
    exec(compile(code, "<deployment-export>", "exec"), namespace)

    with pytest.raises(ValueError, match="does not match workflow"):
        namespace["run_workflow"]()
