"""Systemic gates for the Phase 8 saved-model application qualification."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest


def _load_tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "avatar_omnic_phase8_application.py"
    spec = importlib.util.spec_from_file_location("avatar_omnic_phase8_application", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stage(tool):
    return {
        "runtime_attestation": {
            "schema_version": "spectrasherpa-avatar-phase8-runtime/1",
            "source_commit": tool.RUNTIME_IMPLEMENTATION_COMMIT,
            "operator_code": tool.OPERATOR_CODE,
            "python": {"implementation": "CPython", "version": "3.11.13"},
            "platform": {"system": "Darwin", "machine": "arm64"},
            "distributions": dict(tool.EXPECTED_RUNTIME_DISTRIBUTIONS),
        },
        "saved_version_number": 1,
        "archive": {"size_bytes": 101, "sha256": "a" * 64},
        "input_archive": {"size_bytes": 101, "sha256": "a" * 64},
        "restored_version_count": 1,
        "storage_uid_remapped": True,
        "reexport": {"size_bytes": 102, "sha256": "b" * 64},
        "reexport_semantics": {"semantic_projection_sha256": "9" * 64},
        "scientific": {
            "source_collection": {"shape": tool.EXPECTED_SOURCE_SHAPE},
            "selection": {"shape": tool.EXPECTED_SELECTED_SHAPE},
            "workflow": {"portable_projection_sha256": "c" * 64},
            "models": {"pca": {"model_type": "pca"}, "plsda": {"model_type": "plsda"}},
            "outputs": {
                "pca_scores_shape": tool.EXPECTED_PCA_SCORE_SHAPE,
                "pca_scores_sha256": "d" * 64,
                "plsda_response_shape": tool.EXPECTED_PLSDA_RESPONSE_SHAPE,
                "plsda_responses_sha256": "e" * 64,
            },
        },
        "private": {
            "pca_scores": [[1.0]],
            "plsda_responses": [[2.0]],
            "plsda_ordered_classes": ["A"],
            "plsda_decisions": ["A"],
            "plsda_decision_margins": [0.5],
        },
    }


def _nominal_report(tool):
    stage = _stage(tool)
    report = tool._public_projection(stage, stage, stage)
    report["private_evidence_authority"] = {
        "private_report_size_bytes": 1000,
        "private_report_sha256": "f" * 64,
        "private_report_published": False,
    }
    sections = {name: tool._json_digest(value) for name, value in tool._section_projections(report).items()}
    return report, sections


def test_phase8_workflow_is_application_only_and_exactly_bound() -> None:
    tool = _load_tool()
    payload = tool._application_workflow_payload(
        project_id=7,
        experiment_id=11,
        pca_model_id="pca-id",
        plsda_model_id="plsda-id",
    )
    nodes = {item["node_id"]: item for item in payload["nodes"]}

    assert [item["node_type"] for item in payload["nodes"]] == [
        "data.load_group",
        "selection.variable_select",
        "model.load_apply",
        "model.load_apply",
    ]
    assert nodes["window"]["parameters"] == {
        "method": "interval",
        "region_start": 3100.0,
        "region_end": 650.0,
    }
    assert nodes["pca_apply"]["parameters"] == {"model_id": "pca-id"}
    assert nodes["plsda_apply"]["parameters"] == {"model_id": "plsda-id"}
    assert len(payload["edges"]) == 3
    assert all("fit" not in item["node_type"] for item in payload["nodes"])


def test_phase8_tool_contains_no_direct_fitted_lifecycle_call() -> None:
    path = Path(__file__).resolve().parents[1] / "tools" / "avatar_omnic_phase8_application.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {
        "execute_candidate_validation",
        "execute_candidate_validation_with_private_classification_trace",
        "execute_selected_candidate_full_refit",
    }
    calls = [item for item in ast.walk(tree) if isinstance(item, ast.Call)]
    assert not any(isinstance(item.func, ast.Attribute) and item.func.attr == "fit_fitted_state" for item in calls)
    assert not any(isinstance(item.func, ast.Name) and item.func.id in forbidden for item in calls)


def test_phase8_exact_stage_comparison_includes_every_scientific_output() -> None:
    tool = _load_tool()
    first = _stage(tool)
    second = deepcopy(first)
    assert tool._same_application_outputs(first, second)

    for key in (
        "pca_scores",
        "plsda_responses",
        "plsda_ordered_classes",
        "plsda_decisions",
        "plsda_decision_margins",
    ):
        changed = deepcopy(second)
        changed["private"][key] = ["changed"]
        assert not tool._same_application_outputs(first, changed)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report["process_boundary"].__setitem__("plsda_fit_or_refit_count", 1),
        lambda report: report["scientific_result"]["outputs"].__setitem__("plsda_responses_sha256", "0" * 64),
        lambda report: report.__setitem__("claim_boundary", "botanical authenticity validated"),
        lambda report: report.__setitem__("nonclaims", []),
        lambda report: report.__setitem__("private_evidence_authority", {}),
    ],
)
def test_phase8_checked_report_rejects_semantic_mutation_after_rehash(mutation) -> None:
    tool = _load_tool()
    report, reviewed_sections = _nominal_report(tool)
    assert tool._semantic_failures(report, reviewed_sections) == []

    mutation(report)
    assert tool._semantic_failures(report, reviewed_sections)


def test_phase8_public_reader_refuses_symlink_and_oversize_before_read_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _load_tool()
    target = tmp_path / "target.json"
    target.write_bytes(b"{}")
    linked = tmp_path / "linked.json"
    linked.symlink_to(target)
    with pytest.raises(ValueError, match="non-linked"):
        tool._read_public(linked, limit=100)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * 101)
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(AssertionError("unbounded read")))
    with pytest.raises(ValueError, match="byte contract"):
        tool._read_public(oversized, limit=100)


def test_phase8_output_paths_refuse_collision_before_any_stage(tmp_path: Path) -> None:
    tool = _load_tool()
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    shared = evidence / "shared.json"
    args = argparse.Namespace(
        archive=shared,
        private_report=shared,
        public_report=evidence / "public.json",
        phase6_archive=tmp_path / "phase6.sherpa",
        phase6_private_report=tmp_path / "phase6.json",
        phase7_private_report=tmp_path / "phase7.json",
    )
    with pytest.raises(ValueError, match="collides"):
        tool._closed_output_paths(args, tmp_path / "workspace-a", tmp_path / "workspace-b")
    assert list(evidence.iterdir()) == []


def test_phase8_workspaces_refuse_same_or_nested_identity_before_execution(tmp_path: Path) -> None:
    tool = _load_tool()
    for workspace_a, workspace_b in (
        (tmp_path / "same", tmp_path / "same"),
        (tmp_path / "parent", tmp_path / "parent/child"),
    ):
        with pytest.raises(ValueError, match="distinct and non-nested"):
            tool._run(argparse.Namespace(workspace_a=workspace_a, workspace_b=workspace_b))


def test_phase8_stage_b_archive_is_exactly_bound_before_import() -> None:
    tool = _load_tool()
    payload = b"PK\x03\x04exact-archive"
    stage_a = {"archive": {"size_bytes": len(payload), "sha256": tool._sha256(payload)}}
    assert tool._require_stage_archive(payload, stage_a) == stage_a["archive"]

    with pytest.raises(ValueError, match="differs from the exact Stage A export"):
        tool._require_stage_archive(payload + b"unbound-trailer", stage_a)


def test_phase8_runtime_and_operator_authority_must_match_every_stage() -> None:
    tool = _load_tool()
    stages = [_stage(tool), _stage(tool), _stage(tool)]
    assert tool._require_common_runtime(*stages) == stages[0]["runtime_attestation"]

    changed = deepcopy(stages)
    changed[2]["runtime_attestation"]["distributions"]["numpy"] = "0.0.0"
    with pytest.raises(ValueError, match="runtime/operator authority"):
        tool._require_common_runtime(*changed)


def test_phase8_reexport_refuses_corrupt_and_semantically_empty_archives() -> None:
    tool = _load_tool()
    with pytest.raises(ValueError, match="valid closed project archive"):
        tool._require_reexport_semantics(b"not-a-zip", expected_science={}, expected_workflow={})

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("project.json", json.dumps({"archive_format": "0.4"}))
    with pytest.raises(ValueError, match="canonical archive admission"):
        tool._require_reexport_semantics(payload.getvalue(), expected_science={}, expected_workflow={})


@pytest.mark.parametrize("label", ["source", "model arrays"])
def test_phase8_reexport_member_content_is_stream_hashed(label: str) -> None:
    tool = _load_tool()
    expected = b"exact-member-bytes"
    changed = b"X" + expected[1:]
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("member.bin", changed)
    with zipfile.ZipFile(io.BytesIO(payload.getvalue()), "r") as archive:
        with pytest.raises(ValueError, match=f"{label} member content differs"):
            tool._read_reexport_member(
                archive,
                "member.bin",
                label=label,
                max_bytes=len(expected),
                expected_size=len(expected),
                expected_sha256=tool._sha256(expected),
            )


def test_phase8_reexport_source_manifest_is_recomputed_from_actual_members() -> None:
    tool = _load_tool()
    entries = [
        {
            "file_name": "raw/a.spa",
            "size_bytes": 4,
            "sha256": "a" * 64,
            "prepared_data_sha256": "b" * 64,
        }
    ]
    from spectra_sherpa.app.lib.collection_assembly import source_collection_manifest

    expected = source_collection_manifest(entries)["manifest_digest"]
    assert tool._require_reexport_source_manifest(entries, expected)["manifest_digest"] == expected

    coherently_changed = deepcopy(entries)
    coherently_changed[0]["sha256"] = "c" * 64
    with pytest.raises(ValueError, match="actual source bytes do not reproduce"):
        tool._require_reexport_source_manifest(coherently_changed, expected)


def test_phase8_reexport_model_training_source_is_inside_exact_project_custody() -> None:
    tool = _load_tool()
    manifest = {
        "preprocessing_chain": [
            {
                "op_id": "spectrasherpa.experiment_dataset_read/2",
                "parameters": {"dataset_id": 1},
            }
        ]
    }
    model_record = {"training_dataset_id": 1}
    experiment_index = {1: (7, {"id": 1})}
    assert (
        tool._require_reexport_model_training_source(
            manifest,
            model_record,
            owner_project_id=7,
            experiment_index=experiment_index,
        )
        == 1
    )

    coherently_unbound_manifest = deepcopy(manifest)
    coherently_unbound_manifest["preprocessing_chain"][0]["parameters"]["dataset_id"] = 999
    coherently_unbound_record = {"training_dataset_id": 999}
    with pytest.raises(ValueError, match="outside archive custody"):
        tool._require_reexport_model_training_source(
            coherently_unbound_manifest,
            coherently_unbound_record,
            owner_project_id=7,
            experiment_index=experiment_index,
        )

    with pytest.raises(ValueError, match="outside archive custody"):
        tool._require_reexport_model_training_source(
            manifest,
            model_record,
            owner_project_id=7,
            experiment_index={1: (8, {"id": 1})},
        )


def _workflow_science_fixture(tool, monkeypatch: pytest.MonkeyPatch):
    source_X = np.asarray([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]])
    source_axis = np.asarray([4.0, 3.0, 2.0, 1.0])
    mask = np.asarray([False, True, True, False])
    labels = ["s1", "s2"]
    table = {"sample_id": labels, "specimen_id": ["A", "B"], "block": [1, 1]}
    monkeypatch.setattr(tool, "EXPECTED_SOURCE_SHAPE", [2, 4])
    monkeypatch.setattr(tool, "EXPECTED_SELECTED_SHAPE", [2, 2])
    monkeypatch.setattr(tool, "EXPECTED_DATASET_ID", "exact-source")
    monkeypatch.setattr(tool, "EXPECTED_SOURCE_AXIS_SHA256", tool._array_digest(source_axis))
    monkeypatch.setattr(tool, "EXPECTED_SELECTION_MASK_SHA256", tool._bool_digest(mask))

    def wire(data, axis, *, dataset_id):
        return {
            "data": data.tolist(),
            "dataset_id": dataset_id,
            "units": "absorbance",
            "data_role": "X_spectra",
            "data_modality": "spectra",
            "target_context": {},
            "is_time_series": False,
            "x_axis": {
                "data": axis.tolist(),
                "axis_class": "SpectralAxis",
                "title": "Wavenumber",
                "units": "cm-1",
            },
            "y_axis": {
                "labels": list(labels),
                "sample_table": deepcopy(table),
                "include_mask": [True, True],
            },
            "metadata": {
                "source_collection": {
                    "collection_definition_sha256": "a" * 64,
                    "source_manifest_sha256": "b" * 64,
                    "scientific_collection_sha256": "c" * 64,
                }
            },
        }

    execution = {
        "results": {
            "source": {"default": wire(source_X, source_axis, dataset_id="exact-source")},
            "window": {
                "X_selected": wire(source_X[:, mask], source_axis[mask], dataset_id="derived"),
                "mask": mask.tolist(),
                "selection_report": {
                    "method": "interval",
                    "reference_samples": 2,
                    "reference_features": 4,
                    "selected_features": 2,
                    "feature_axis_values_sha256": tool._array_digest(source_axis),
                    "feature_mask_sha256": tool._bool_digest(mask),
                },
            },
        }
    }
    observed_source = {
        "shape": [2, 4],
        "values_sha256": tool._array_digest(source_X),
        "feature_axis_sha256": tool._array_digest(source_axis),
        "sample_labels_sha256": tool._json_digest(labels),
        "sample_table_sha256": tool._json_digest(table),
        "dataset_id": "exact-source",
        "target_state": "absent",
        "collection_definition_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "scientific_collection_sha256": "c" * 64,
    }
    observed_selection = {
        "method": "interval",
        "requested_bounds_cm-1": [3100.0, 650.0],
        "actual_endpoints_cm-1": [3.0, 2.0],
        "shape": [2, 2],
        "selected_values_sha256": tool._array_digest(source_X[:, mask]),
        "selected_axis_sha256": tool._array_digest(source_axis[mask]),
        "mask_sha256": tool._bool_digest(mask),
    }
    return execution, {"source_collection": observed_source, "selection": observed_selection}


def test_phase8_recomputes_exact_source_and_selection_from_workflow_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _load_tool()
    execution, reviewed = _workflow_science_fixture(tool, monkeypatch)
    assert tool._require_exact_workflow_science(execution, reviewed) == (
        reviewed["source_collection"],
        reviewed["selection"],
    )

    changed = deepcopy(execution)
    changed["results"]["window"]["X_selected"]["data"][0][0] += 1.0
    with pytest.raises(ValueError, match="exact source projection"):
        tool._require_exact_workflow_science(changed, reviewed)

    changed = deepcopy(execution)
    changed["results"]["window"]["X_selected"]["y_axis"]["labels"].reverse()
    with pytest.raises(ValueError, match="sample identity"):
        tool._require_exact_workflow_science(changed, reviewed)

    changed = deepcopy(execution)
    changed["results"]["window"]["mask"] = [0, 1, 1, 0]
    with pytest.raises(ValueError, match="exact boolean"):
        tool._require_exact_workflow_science(changed, reviewed)


def _pca_artifact_fixture(tool, monkeypatch: pytest.MonkeyPatch):
    selected = np.zeros((33, 1270), dtype=np.float64)
    selected_axis = np.linspace(3099.0, 652.0, 1270, dtype=np.float64)
    loadings = np.zeros((3, 1270), dtype=np.float64)
    loadings[0, 0] = loadings[1, 1] = loadings[2, 2] = 1.0
    explained = np.asarray([0.6, 0.3, 0.1], dtype=np.float64)
    eigenvalues = np.asarray([3.0, 2.0, 1.0], dtype=np.float64)
    mean = np.zeros(1270, dtype=np.float64)
    scores = np.zeros((33, 3), dtype=np.float64)
    mask = np.asarray([True] * 1270 + [False] * (1868 - 1270), dtype=np.bool_)
    monkeypatch.setattr(tool, "EXPECTED_SELECTED_VALUES_SHA256", tool._array_digest(selected))
    monkeypatch.setattr(tool, "EXPECTED_SELECTED_AXIS_SHA256", tool._array_digest(selected_axis))
    monkeypatch.setattr(tool, "EXPECTED_SELECTION_MASK_SHA256", tool._bool_digest(mask))
    monkeypatch.setattr(tool, "EXPECTED_SOURCE_AXIS_SHA256", "1" * 64)

    from spectra_sherpa.app.lib.axes import SpectralAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode
    from spectra_sherpa.app.services.dag.rank_projection import input_axis_identity
    from spectra_sherpa.app.services.dag.stable_execution_contract import execution_contract_digest

    replay_input = SherpaDataset(
        X=selected,
        feature_axis=SpectralAxis(
            values=selected_axis,
            units="cm-1",
            title="Wavenumber",
            quantity="wavenumber",
        ),
    )

    state_arrays = {
        "loadings": loadings.tolist(),
        "explained_variance_ratio": explained.tolist(),
        "explained_variance": eigenvalues.tolist(),
        "mean": mean.tolist(),
        "scale": None,
        "offset": None,
        "center": None,
    }
    state_metadata = {
        "n_components": 3,
        "n_features": 1270,
        "reference_samples": 33,
        "standardized": False,
        "scaled": False,
        "scale_mode": None,
        "sign_rule": "largest_absolute_loading_positive",
        "feature_axis_values_sha256": tool._array_digest(selected_axis),
        "feature_axis_labels_sha256": None,
        "feature_axis_units": "cm-1",
        "feature_axis_quantity": "wavenumber",
        "input_axis_identity_sha256": input_axis_identity(replay_input),
        "input_shape": [33, 1270],
        "rank_projection_strategy": "none",
    }
    state = {
        "schema_version": "spectrasherpa.model.pca-state/4",
        "serializer": "spectrasherpa.model-artifact.pca/3",
        "source_contract_digest": execution_contract_digest(PCANode.metadata),
        "state_content_digest": tool._json_digest({"metadata": state_metadata, "arrays": state_arrays}),
        "metadata": state_metadata,
        "arrays": state_arrays,
    }
    decoded = {
        "loadings": loadings,
        "explained_variance_ratio": explained,
        "explained_variance": eigenvalues,
        "mean": mean,
        "scores": scores,
    }
    inventory = {name: {"shape": list(value.shape), "dtype": "float64"} for name, value in decoded.items()}
    selection_report = {
        "schema": "spectrasherpa.selection.variable_select.report/1",
        "method": "interval",
        "parameters": {"invert": False, "method": "interval", "region_end": 650.0, "region_start": 3100.0},
        "reference_samples": 33,
        "reference_features": 1868,
        "selected_features": 1270,
        "feature_axis_values_sha256": tool.EXPECTED_SOURCE_AXIS_SHA256,
        "feature_mask_sha256": tool.EXPECTED_SELECTION_MASK_SHA256,
        "predictive_performance_claimed": False,
        "selection_scope": "target_free_feature_rule_not_predictive_validation",
        "detected_extrema_indices": [],
        "score_sha256": None,
    }
    integrity = "a" * 64
    manifest = {
        "arrays": inventory,
        "artifact_authority": "workbench_native_or_imported_model",
        "artifact_uid": "pca-id",
        "feature_axis": selected_axis.tolist(),
        "feature_axis_class": "SpectralAxis",
        "feature_axis_title": "Wavenumber",
        "feature_axis_units": "cm-1",
        "feature_mask": mask.tolist(),
        "integrity_hash": integrity,
        "metrics": {
            "cumulative_variance": np.cumsum(explained).tolist(),
            "explained_variance_ratio": explained.tolist(),
        },
        "model_type": "pca",
        "n_components": 3,
        "n_features": 1270,
        "node_id": "pca",
        "preprocessing_chain": [
            {
                "op_id": "spectrasherpa.experiment_dataset_read/2",
                "parameters": {
                    "asset_id": "spectrum",
                    "collection_definition_sha256": tool.EXPECTED_DEFINITION_SHA256,
                    "dataset_id": 1,
                    "file_count": 33,
                    "scientific_collection_sha256": tool.EXPECTED_SCIENTIFIC_COLLECTION_SHA256,
                    "source_manifest_sha256": tool.EXPECTED_SOURCE_MANIFEST_SHA256,
                    "stage": "raw",
                },
            },
            {
                "op_id": "selection.variable_select",
                "parameters": {"feature_mask": mask.tolist(), "selection_report": selection_report},
            },
        ],
        "scale_mode": None,
        "scaled": False,
        "selected_features": selected_axis.tolist(),
        "serializer": "spectrasherpa.model-artifact.pca/3",
        "standardized": False,
        "training_data_hash": tool._training_data_hash(selected),
    }
    detail = {
        "artifact_uid": "pca-id",
        "feature_axis": selected_axis.tolist(),
        "integrity_hash": integrity,
        "model_type": "pca",
        "n_components": 3,
        "n_features": 1270,
        "training_data_hash": tool._training_data_hash(selected),
    }
    inspection = {
        "artifact_uid": "pca-id",
        "manifest": deepcopy(manifest),
        "arrays": deepcopy(inventory),
    }
    private = {
        "workspace_a_initial": {
            "private": {
                "fitted_state": state,
                "loadings": loadings.tolist(),
                "scores": scores.tolist(),
                "selected_axis": selected_axis.tolist(),
                "selected_matrix": selected.tolist(),
            }
        }
    }
    science = {
        "pca": {
            "artifact_integrity_hash": integrity,
            "artifact_serializer": "spectrasherpa.model-artifact.pca/3",
            "explained_variance_ratio": explained.tolist(),
            "explained_variance_ratio_sha256": tool._array_digest(explained),
            "eigenvalues": eigenvalues.tolist(),
            "eigenvalues_sha256": tool._array_digest(eigenvalues),
            "loadings_sha256": tool._array_digest(loadings),
            "source_contract_digest": state["source_contract_digest"],
            "state_content_digest": state["state_content_digest"],
        }
    }
    return manifest, decoded, detail, inspection, private, science


def test_phase8_pca_artifact_is_exactly_bound_to_phase6_arrays_and_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _load_tool()
    manifest, arrays, detail, inspection, private, science = _pca_artifact_fixture(tool, monkeypatch)
    observed = tool._require_pca_artifact_binding(
        manifest=manifest,
        arrays=arrays,
        detail=detail,
        inspection=inspection,
        phase6_private=private,
        phase6_science=science,
        expected_training_dataset_id=1,
    )
    assert observed["artifact_integrity_sha256"] == "a" * 64
    assert observed["state_content_digest"] == science["pca"]["state_content_digest"]
    assert len(observed["manifest_science_sha256"]) == 64

    semantic_mutations = []
    for field, value in (("feature_axis_units", "nm"), ("feature_axis_title", "Frequency")):
        changed = deepcopy(manifest)
        changed[field] = value
        semantic_mutations.append(changed)
    changed = deepcopy(manifest)
    changed["preprocessing_chain"][1]["parameters"]["selection_report"]["reference_samples"] = 999
    semantic_mutations.append(changed)
    changed = deepcopy(manifest)
    changed["preprocessing_chain"][0]["parameters"]["dataset_id"] = 999
    semantic_mutations.append(changed)
    for changed_manifest in semantic_mutations:
        changed_inspection = deepcopy(inspection)
        changed_inspection["manifest"] = deepcopy(changed_manifest)
        with pytest.raises(ValueError, match="persisted PCA"):
            tool._require_pca_artifact_binding(
                manifest=changed_manifest,
                arrays=arrays,
                detail=detail,
                inspection=changed_inspection,
                phase6_private=private,
                phase6_science=science,
                expected_training_dataset_id=1,
            )

    for field in ("loadings", "explained_variance_ratio", "explained_variance"):
        changed_arrays = deepcopy(arrays)
        changed_arrays[field] = np.array(changed_arrays[field], copy=True)
        changed_arrays[field].flat[0] += 0.01
        with pytest.raises(ValueError, match="differs from reviewed Phase 6"):
            tool._require_pca_artifact_binding(
                manifest=manifest,
                arrays=changed_arrays,
                detail=detail,
                inspection=inspection,
                phase6_private=private,
                phase6_science=science,
                expected_training_dataset_id=1,
            )

    changed_manifest = deepcopy(manifest)
    changed_manifest["feature_axis"][0] += 1.0
    changed_inspection = deepcopy(inspection)
    changed_inspection["manifest"] = deepcopy(changed_manifest)
    with pytest.raises(ValueError, match="persisted PCA"):
        tool._require_pca_artifact_binding(
            manifest=changed_manifest,
            arrays=arrays,
            detail=detail,
            inspection=changed_inspection,
            phase6_private=private,
            phase6_science=science,
            expected_training_dataset_id=1,
        )

    changed_manifest = deepcopy(manifest)
    changed_manifest["feature_mask"] = [int(value) for value in changed_manifest["feature_mask"]]
    changed_inspection = deepcopy(inspection)
    changed_inspection["manifest"] = deepcopy(changed_manifest)
    with pytest.raises(ValueError, match="persisted PCA"):
        tool._require_pca_artifact_binding(
            manifest=changed_manifest,
            arrays=arrays,
            detail=detail,
            inspection=changed_inspection,
            phase6_private=private,
            phase6_science=science,
            expected_training_dataset_id=1,
        )


def test_phase8_public_projection_is_row_and_storage_identity_free() -> None:
    tool = _load_tool()
    report, _ = _nominal_report(tool)
    encoded = tool._pretty_json(report).decode("utf-8")
    for forbidden in (
        '"sample_id"',
        '"specimen_id"',
        '"artifact_uid"',
        '"project_id"',
        '"experiment_id"',
        '"workflow_id"',
        "/private/",
    ):
        assert forbidden not in encoded


def test_checked_phase8_report_is_closed_and_exact() -> None:
    tool = _load_tool()
    report = Path(__file__).resolve().parents[3] / "docs/evidence/avatar-essential-oils-v1-phase8-application.json"

    assert tool.validate_checked_report(report) == []
