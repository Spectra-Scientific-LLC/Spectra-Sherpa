"""Render a saved Workbench DAG as one canonical executable Python program.

The exporter is deliberately not a scientific code generator. It projects
application-owned ``data.file_load`` sources to explicit ``deploy.input``
bindings, embeds the resulting current workflow manifest, and invokes the
public SDK's canonical executor. Node formulas, estimators, preprocessing,
metrics, and artifact lifecycle behavior therefore remain owned by the live
registry operation that the Workbench itself executes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pprint import pformat
from typing import TYPE_CHECKING, Any, Mapping

from spectra_sherpa.core.target_authority import admit_target_authority
from spectra_sherpa.io.authority import (
    admit_portable_ingestion_authority,
    project_portable_ingestion_authority,
)
from spectra_sherpa.sdk.deployment import DEPLOYMENT_INPUT_SCHEMA
from spectra_sherpa.sdk.workflow import WorkflowSpec, workflow_spec

if TYPE_CHECKING:
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.workflow_export_context import BundledSourceFile, WorkflowExportContext


@dataclass(frozen=True)
class ExportValidationError:
    """Describe why a workflow cannot become a self-contained executable."""

    node_id: str
    node_type: str
    reason: str


@dataclass(frozen=True)
class BundledSourceBinding:
    """One actor-authorized file projected to a canonical deployment input."""

    node_id: str
    stream_name: str
    bundle_relative_path: str
    byte_length: int
    sha256: str
    target_authority: Mapping[str, object] | None
    prepared_overrides: Mapping[str, object]
    ingestion_authority: Mapping[str, object]
    external_reference: Mapping[str, object] | None = None
    source_kind: str = "file"
    asset_id: str | None = None
    member_file_name: str | None = None
    collection_title: str | None = None
    collection_definition: Mapping[str, object] | None = None
    group_column: str | None = None
    source_manifest_sha256: str | None = None
    collection_definition_sha256: str | None = None
    scientific_collection_sha256: str | None = None

    @property
    def selected_target(self) -> str | None:
        value = self.target_authority.get("column") if self.target_authority is not None else None
        return str(value) if value else None

    @property
    def target_type(self) -> str | None:
        value = self.target_authority.get("target_type") if self.target_authority is not None else None
        return str(value) if value else None

    def as_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "stream_name": self.stream_name,
            "bundle_relative_path": self.bundle_relative_path,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "target_authority": dict(self.target_authority) if self.target_authority is not None else None,
            "prepared_overrides": dict(self.prepared_overrides),
            "ingestion_authority": dict(self.ingestion_authority),
            "external_reference": dict(self.external_reference) if self.external_reference is not None else None,
            "source_kind": self.source_kind,
            "asset_id": self.asset_id,
            "member_file_name": self.member_file_name,
            "collection_title": self.collection_title,
            "collection_definition": (
                dict(self.collection_definition) if self.collection_definition is not None else None
            ),
            "group_column": self.group_column,
            "source_manifest_sha256": self.source_manifest_sha256,
            "collection_definition_sha256": self.collection_definition_sha256,
            "scientific_collection_sha256": self.scientific_collection_sha256,
        }


@dataclass(frozen=True)
class CanonicalExecutableExport:
    """Closed projection shared by Python and notebook renderers."""

    workflow: WorkflowSpec
    bundled_sources: tuple[BundledSourceBinding, ...]
    external_streams: tuple[str, ...]
    execution_order: tuple[str, ...]
    node_types: Mapping[str, str]
    node_labels: Mapping[str, str]


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", value) or "source"


def _portable_ingestion_authority(
    bundle: BundledSourceFile,
    *,
    asset_id: str | None,
    prepared_overrides: Mapping[str, object],
) -> Mapping[str, object]:
    """Resolve one export source through its actual native scientific path."""

    if bundle.ingestion_authority is not None:
        return admit_portable_ingestion_authority(bundle.ingestion_authority).canonical_dict()
    if bundle.external_reference is not None:
        from spectra_sherpa.app.lib.reference_materialization import materialize_reference_member

        projection_id = str(bundle.external_reference.get("projection_id") or "")
        if not projection_id:
            raise ValueError("registered export source is missing its projection identity")
        dataset = materialize_reference_member(bundle.absolute_path, projection_id).dataset
    else:
        from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

        dataset = load_canonical_file_as_sherpa(
            bundle.absolute_path,
            asset_id=asset_id,
            prepared_overrides=prepared_overrides,
        )
    return project_portable_ingestion_authority(dataset).canonical_dict()


def _topological_order(nodes: list[dict[str, Any]], edges: list[dict[str, str]]) -> tuple[str, ...]:
    indegree = {str(node["node_id"]): 0 for node in nodes}
    successors: dict[str, list[str]] = {node_id: [] for node_id in indegree}
    for edge in edges:
        source = edge["from_node_id"]
        target = edge["to_node_id"]
        indegree[target] += 1
        successors[source].append(target)
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while ready:
        node_id = ready.pop(0)
        ordered.append(node_id)
        for target in sorted(successors[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if len(ordered) != len(nodes):
        raise ValueError("Workflow graph must be acyclic")
    return tuple(ordered)


def build_canonical_executable_export(
    workflow: Workflow,
    *,
    export_context: WorkflowExportContext | None,
) -> CanonicalExecutableExport:
    """Build the only executable export projection for a saved workflow.

    A Workbench file source carries database identities that are meaningful
    only inside the originating application. Export replaces that source
    node—not any scientific child—with ``deploy.input`` and binds its exact
    actor-authorized bytes separately. All remaining node identities,
    parameters, typed ports, and edges are preserved and re-admitted by the
    current registry through :func:`workflow_spec`.
    """

    if getattr(workflow, "fold_validation_plan", None) is not None:
        raise ValueError(
            "Executable code export cannot preserve the sheet validation plan; export its .sherpa project instead."
        )

    nodes: list[dict[str, Any]] = []
    bundled_sources: list[BundledSourceBinding] = []
    external_streams: list[str] = []
    seen_streams: set[str] = set()

    from spectra_sherpa.app.services.dag.node_base import node_registry

    for wf_node in workflow.nodes:
        node_id = str(wf_node.node_id)
        node_type = str(wf_node.node_type)
        parameters = dict(wf_node.parameters or {})
        if node_type == "data.load_group" and parameters.get("source_mode") == "experiment_collection":
            raise ValueError(
                "Legacy project collection sources must be reopened and saved through "
                "data.collection_load before export"
            )
        if node_type in {"data.file_load", "data.collection_load"}:
            spec = export_context.source_spec_for(node_id) if export_context is not None else None
            expected_mode = "single_file" if node_type == "data.file_load" else "collection"
            if spec is None or spec.loader_mode != expected_mode or not spec.bundle_files:
                raise ValueError(f"Node {node_id} ({node_type}) has no complete actor-authorized source set")
            if node_type == "data.file_load" and len(spec.bundle_files) != 1:
                raise ValueError(f"Node {node_id} ({node_type}) requires exactly one actor-authorized file")
            stream_name = f"export.source.{_safe_identifier(node_id)}"
            if stream_name in seen_streams:
                raise ValueError(f"Export repeats deployment stream {stream_name!r}")
            seen_streams.add(stream_name)
            admitted_target_authority = admit_target_authority(parameters.get("target_authority"))
            target_authority = (
                admitted_target_authority.canonical_dict() if admitted_target_authority is not None else None
            )
            if admitted_target_authority is not None and node_type == "data.collection_load":
                collection_digest = parameters.get("scientific_collection_sha256")
                if collection_digest and admitted_target_authority.source_digest != collection_digest:
                    raise ValueError(f"Node {node_id} ({node_type}) target authority differs from its collection")
            asset_id = str(parameters.get("asset_id") or "") or None
            for bundle in spec.bundle_files:
                try:
                    source_bytes = bundle.absolute_path.read_bytes()
                except OSError as exc:
                    raise ValueError(f"Node {node_id} ({node_type}) bundled file is unavailable") from exc
                source_sha256 = hashlib.sha256(source_bytes).hexdigest()
                if bundle.external_reference is not None:
                    expected_size = bundle.external_reference.get("member_size_bytes")
                    expected_sha256 = bundle.external_reference.get("member_sha256")
                    if len(source_bytes) != expected_size or source_sha256 != expected_sha256:
                        raise ValueError(f"Node {node_id} ({node_type}) registered reference member is not exact")
                if (
                    admitted_target_authority is not None
                    and node_type == "data.file_load"
                    and admitted_target_authority.source_digest != source_sha256
                ):
                    raise ValueError(f"Node {node_id} ({node_type}) target authority differs from its source")
                bundled_sources.append(
                    BundledSourceBinding(
                        node_id=node_id,
                        stream_name=stream_name,
                        bundle_relative_path=str(bundle.bundle_relative_path),
                        byte_length=len(source_bytes),
                        sha256=source_sha256,
                        target_authority=target_authority,
                        prepared_overrides=(
                            bundle.prepared_overrides.to_sidecar_dict()
                            if node_type == "data.collection_load"
                            else spec.overrides.to_sidecar_dict()
                        ),
                        ingestion_authority=_portable_ingestion_authority(
                            bundle,
                            asset_id=None if asset_id == "single-auto" else asset_id,
                            prepared_overrides=(
                                bundle.prepared_overrides.to_sidecar_dict()
                                if node_type == "data.collection_load"
                                else spec.overrides.to_sidecar_dict()
                            ),
                        ),
                        external_reference=bundle.external_reference,
                        source_kind="collection" if node_type == "data.collection_load" else "file",
                        asset_id=(
                            str(bundle.external_reference["projection_id"])
                            if bundle.external_reference is not None
                            else asset_id
                        ),
                        member_file_name=bundle.member_file_name or bundle.absolute_path.name,
                        collection_title=spec.collection_title,
                        collection_definition=spec.collection_definition,
                        group_column=str(parameters.get("group_column") or "") or None,
                        source_manifest_sha256=str(parameters.get("source_manifest_sha256") or "") or None,
                        collection_definition_sha256=(
                            str(parameters.get("collection_definition_sha256") or "") or None
                        ),
                        scientific_collection_sha256=(
                            str(parameters.get("scientific_collection_sha256") or "") or None
                        ),
                    )
                )
            nodes.append(
                {
                    "node_id": node_id,
                    "node_type": "deploy.input",
                    "parameters": {
                        "stream_name": stream_name,
                        "schema_version": DEPLOYMENT_INPUT_SCHEMA,
                    },
                }
            )
            continue

        if node_type == "deploy.input":
            stream_name = str(parameters.get("stream_name", ""))
            if not stream_name or stream_name in seen_streams:
                raise ValueError(f"Node {node_id} ({node_type}) has an invalid or repeated stream name")
            seen_streams.add(stream_name)
            external_streams.append(stream_name)

        nodes.append({"node_id": node_id, "node_type": node_type, "parameters": parameters})

    edges = [
        {
            "from_node_id": str(edge.from_node_id),
            "to_node_id": str(edge.to_node_id),
            "from_output": str(edge.from_output or "default"),
            "to_input": str(edge.to_input or "default"),
        }
        for edge in workflow.edges
    ]
    admitted = workflow_spec(nodes=nodes, edges=edges)
    node_types = {str(node["node_id"]): str(node["node_type"]) for node in admitted.payload["nodes"]}
    node_labels: dict[str, str] = {}
    for node_id, node_type in node_types.items():
        try:
            node_labels[node_id] = node_registry.get_metadata(node_type).label
        except (AttributeError, KeyError):
            node_labels[node_id] = node_type
    order = _topological_order(admitted.payload["nodes"], admitted.payload["edges"])
    return CanonicalExecutableExport(
        workflow=admitted,
        bundled_sources=tuple(sorted(bundled_sources, key=lambda item: item.node_id)),
        external_streams=tuple(sorted(external_streams)),
        execution_order=order,
        node_types=node_types,
        node_labels=node_labels,
    )


def validate_export(
    workflow: Workflow, export_context: WorkflowExportContext | None = None
) -> list[ExportValidationError]:
    """Return an empty list only when the canonical export projection admits."""

    try:
        build_canonical_executable_export(workflow, export_context=export_context)
    except (KeyError, TypeError, ValueError) as exc:
        return [ExportValidationError(node_id="__workflow__", node_type="canonical_dag", reason=str(exc))]
    return []


def _render_module(export: CanonicalExecutableExport, workflow: Workflow, *, include_main: bool) -> str:
    workflow_manifest = pformat(export.workflow.as_dict(), width=100, sort_dicts=True)
    source_bindings = pformat([binding.as_dict() for binding in export.bundled_sources], width=100, sort_dicts=True)
    external_streams = repr(export.external_streams)

    documentation = [
        f"Generated canonical workflow: {workflow.name}",
        "",
        "This file contains declarative DAG and source-binding records only.",
        "Every scientific operation executes through spectra_sherpa.sdk.runtime.",
        f"Workflow digest: {export.workflow.workflow_digest}",
    ]
    description = str(getattr(workflow, "description", "") or "").strip()
    if description:
        documentation.extend(["", description])
    integrity_hash = getattr(workflow, "integrity_hash", None)
    if integrity_hash:
        documentation.extend(["", f"Saved Workbench integrity hash: {integrity_hash}"])
    if any(binding.external_reference is not None for binding in export.bundled_sources):
        documentation.extend(
            [
                "",
                "Registered reference bytes are not included. Set SPECTRA_REFERENCE_DIR to the exact",
                "required extracted member or to a bounded directory containing exactly one matching file.",
            ]
        )
    lines = [repr("\n".join(documentation)), ""]
    lines.extend(
        [
            "import hashlib",
            "import os",
            "",
            "import spectra_sherpa.sdk as ss",
            "from spectra_sherpa.app.services.export_utils import export_artifacts",
            "",
            f"WORKFLOW_MANIFEST = {workflow_manifest}",
            f"BUNDLED_SOURCE_BINDINGS = {source_bindings}",
            f"EXTERNAL_STREAMS = {external_streams}",
            "",
            "DATA_DIR = os.environ.get(",
            "    'SHERPA_DATA_DIR',",
            '    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")',
            '    if "__file__" in dir() else os.path.join(os.getcwd(), "data"),',
            ")",
            "REFERENCE_PATH = os.environ.get('SPECTRA_REFERENCE_DIR')",
            "REFERENCE_SEARCH_LIMIT = 1000",
            "",
            "",
            "def _file_sha256(path):",
            "    digest = hashlib.sha256()",
            "    with open(path, 'rb') as source_file:",
            "        for chunk in iter(lambda: source_file.read(1024 * 1024), b''):",
            "            digest.update(chunk)",
            "    return digest.hexdigest()",
            "",
            "",
            "def _registered_reference_path(binding):",
            "    if not REFERENCE_PATH:",
            "        raise FileNotFoundError(",
            "            'This workflow uses a registered reference file. Set SPECTRA_REFERENCE_DIR '",
            "            'to the exact extracted member or a directory containing it.'",
            "        )",
            "    root = os.path.abspath(os.path.expanduser(REFERENCE_PATH))",
            "    candidates = []",
            "    if os.path.isfile(root) and not os.path.islink(root):",
            "        candidates = [root]",
            "    elif os.path.isdir(root) and not os.path.islink(root):",
            "        visited = 0",
            "        pending = [root]",
            "        while pending:",
            "            current = pending.pop()",
            "            with os.scandir(current) as entries:",
            "                for entry in entries:",
            "                    visited += 1",
            "                    if visited > REFERENCE_SEARCH_LIMIT:",
            "                        raise ValueError('SPECTRA_REFERENCE_DIR exceeds the 1000-entry search limit')",
            "                    if entry.is_symlink():",
            "                        continue",
            "                    if entry.is_dir(follow_symlinks=False):",
            "                        pending.append(entry.path)",
            "                        continue",
            "                    if not entry.is_file(follow_symlinks=False):",
            "                        continue",
            "                    path = entry.path",
            "                    if os.path.getsize(path) != binding['byte_length']:",
            "                        continue",
            "                    if _file_sha256(path) == binding['sha256']:",
            "                        candidates.append(path)",
            "    else:",
            "        raise FileNotFoundError(f'SPECTRA_REFERENCE_DIR is unavailable: {root}')",
            "    if not candidates:",
            "        raise FileNotFoundError(",
            "            'No file under SPECTRA_REFERENCE_DIR matches the required registered '",
            "            'reference size and SHA-256'",
            "        )",
            "    if len(candidates) != 1:",
            "        raise ValueError('SPECTRA_REFERENCE_DIR contains more than one exact registered-reference match')",
            "    return candidates[0]",
            "",
            "",
            "def _binding_path(binding):",
            "    if binding.get('external_reference') is not None:",
            "        return _registered_reference_path(binding)",
            "    return os.path.join(DATA_DIR, binding['bundle_relative_path'])",
            "",
            "",
            "def _load_bundled_inputs():",
            '    """Load exact embedded files or explicitly rebound registered references."""',
            "    inputs = {}",
            "    streams = {}",
            "    for binding in BUNDLED_SOURCE_BINDINGS:",
            "        streams.setdefault(binding['stream_name'], []).append(binding)",
            "    for stream_name, bindings in streams.items():",
            "        resolved = []",
            "        for binding in bindings:",
            "            path = _binding_path(binding)",
            "            if not os.path.isfile(path):",
            '                raise FileNotFoundError(f"Workflow source is unavailable: {path}")',
            "            with open(path, 'rb') as source_file:",
            "                source_bytes = source_file.read()",
            "            if len(source_bytes) != binding['byte_length']:",
            '                raise ValueError(f"Workflow source size mismatch: {path}")',
            "            if hashlib.sha256(source_bytes).hexdigest() != binding['sha256']:",
            '                raise ValueError(f"Workflow source digest mismatch: {path}")',
            "            resolved.append((binding, path))",
            "        first = bindings[0]",
            "        if first['source_kind'] == 'collection':",
            "            inputs[stream_name] = ss.data.read_collection(",
            "                [",
            "                    {",
            "                        'path': path,",
            "                        'file_name': binding['member_file_name'],",
            "                        'byte_length': binding['byte_length'],",
            "                        'sha256': binding['sha256'],",
            "                        'asset_id': binding['asset_id'],",
            "                        'prepared_overrides': binding['prepared_overrides'],",
            "                        'expected_ingestion_authority': binding['ingestion_authority'],",
            "                        'external_reference': binding['external_reference'],",
            "                    }",
            "                    for binding, path in resolved",
            "                ],",
            "                title=first['collection_title'],",
            "                collection_definition=first['collection_definition'],",
            "                selected_target=(first['target_authority'] or {}).get('column'),",
            "                target_type=(first['target_authority'] or {}).get('target_type'),",
            "                group_column=first['group_column'],",
            "                expected_source_manifest_sha256=first['source_manifest_sha256'],",
            "                expected_collection_definition_sha256=first['collection_definition_sha256'],",
            "                expected_scientific_collection_sha256=first['scientific_collection_sha256'],",
            "            )",
            "        else:",
            "            if len(resolved) != 1:",
            "                raise ValueError('Single-file source resolved to multiple bindings')",
            "            binding, path = resolved[0]",
            "            if binding.get('external_reference') is not None:",
            "                inputs[stream_name] = ss.data.read_registered_reference(",
            "                    path,",
            "                    projection_id=binding['external_reference']['projection_id'],",
            "                    prepared_overrides=binding['prepared_overrides'],",
            "                    expected_ingestion_authority=binding['ingestion_authority'],",
            "                )",
            "            else:",
            "                inputs[stream_name] = ss.data.read(",
            "                    path,",
            "                    asset_id=binding['asset_id'],",
            "                    y=(binding['target_authority'] or {}).get('column'),",
            "                    target_type=(binding['target_authority'] or {}).get('target_type'),",
            "                    prepared_overrides=binding['prepared_overrides'],",
            "                    expected_ingestion_authority=binding['ingestion_authority'],",
            "                )",
            "    return inputs",
            "",
            "",
            "def execute_workflow(deployment_inputs=None):",
            '    """Execute the digest-bound DAG through the canonical SDK runtime."""',
            "    inputs = _load_bundled_inputs()",
            "    supplied = dict(deployment_inputs or {})",
            "    overlap = sorted(set(inputs) & set(supplied))",
            "    if overlap:",
            '        raise ValueError(f"Caller cannot replace bundled source streams: {overlap}")',
            "    inputs.update(supplied)",
            "    workflow = ss.workflow.WorkflowSpec.from_dict(WORKFLOW_MANIFEST)",
            "    return ss.runtime.execute_workflow(workflow, deployment_inputs=inputs)",
            "",
            "",
            "def run_workflow(deployment_inputs=None):",
            '    """Execute the workflow and return every canonical node result."""',
            "    return dict(execute_workflow(deployment_inputs).results)",
            "",
        ]
    )

    if include_main:
        safe_name = _safe_identifier(str(workflow.name).replace(" ", "_"))
        lines.extend(
            [
                "",
                'if __name__ == "__main__":',
                "    if EXTERNAL_STREAMS:",
                "        raise SystemExit(",
                '            "This workflow requires run_workflow(deployment_inputs={...}) for streams "',
                "            + repr(EXTERNAL_STREAMS)",
                "        )",
                "    results = run_workflow()",
                f"    print({('Workflow: ' + str(workflow.name))!r})",
                '    print("=" * 60)',
                "    for key, value in results.items():",
                "        if isinstance(value, dict):",
                '            print(f"  {key}: {list(value.keys())}")',
                "        elif hasattr(value, 'shape'):",
                '            print(f"  {key}: {value.shape}")',
                "        else:",
                '            print(f"  {key}: {type(value).__name__}")',
                f"    export_artifacts(results, {safe_name!r})",
                "",
            ]
        )
    return "\n".join(lines)


def generate_python_code(
    workflow: Workflow,
    export_context: WorkflowExportContext | None = None,
) -> str:
    """Generate the one current executable Python representation."""

    export = build_canonical_executable_export(workflow, export_context=export_context)
    return _render_module(export, workflow, include_main=True)


def generate_notebook_module_code(
    workflow: Workflow,
    export_context: WorkflowExportContext | None = None,
) -> tuple[CanonicalExecutableExport, str]:
    """Return the shared projection and definition-only code for notebooks."""

    export = build_canonical_executable_export(workflow, export_context=export_context)
    return export, _render_module(export, workflow, include_main=False)


__all__ = [
    "BundledSourceBinding",
    "CanonicalExecutableExport",
    "ExportValidationError",
    "build_canonical_executable_export",
    "generate_notebook_module_code",
    "generate_python_code",
    "validate_export",
]
