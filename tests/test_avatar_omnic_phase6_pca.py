from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).parents[3]
TOOL_PATH = REPO_ROOT / "packages" / "spectra-sherpa" / "tools" / "avatar_omnic_phase6_pca.py"
CHECKED_REPORT_PATH = REPO_ROOT / "docs" / "evidence" / "avatar-essential-oils-v1-phase6-pca.json"
SPEC = importlib.util.spec_from_file_location("avatar_omnic_phase6_pca", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def test_checked_phase6_report_is_exact_and_closed() -> None:
    assert TOOL.validate_checked_report(CHECKED_REPORT_PATH) == []


def _workflow(experiment_id: int = 7) -> dict:
    payload = TOOL._workflow_payload(project_id=9, experiment_id=experiment_id)
    return {"nodes": payload["nodes"], "edges": payload["edges"]}


def test_portable_workflow_projection_is_exact_and_remap_stable() -> None:
    first = TOOL._portable_workflow_projection(_workflow(7))
    second = TOOL._portable_workflow_projection(_workflow(99))
    assert first == second
    assert json.dumps(first).count("<portable-experiment-id>") == 1

    mutated = _workflow(7)
    mutated["nodes"][1]["parameters"]["region_start"] = 3000.0
    with pytest.raises(ValueError, match="frozen portable graph"):
        TOOL._portable_workflow_projection(mutated)


def test_public_descriptive_projection_removes_sample_and_specimen_labels() -> None:
    report = {
        "schema_version": "spectrasherpa.pca-block-report/1",
        "score_shape": [33, 3],
        "sample_identity_sha256": "a" * 64,
        "specimen_ids": [f"S{index}" for index in range(11)],
        "block_ids": [1, 2, 3],
        "within_specimen_pairwise_distance": {"count": 33},
        "between_specimen_centroid_distance": {"count": 55},
        "between_to_within_mean_ratio": 2.0,
        "specimen_centroids_sha256": "b" * 64,
        "block_centroids": [[0.0, 0.0, 0.0]] * 3,
        "block_centroids_sha256": "c" * 64,
        "block_r_squared": 0.01,
        "block_effect_interpretation": "descriptive",
        "order_specimen_fully_aliased": True,
        "order_identifiability": "aliased",
        "ordered_paths": [
            {
                "block": block,
                "ordered_sample_ids_sha256": str(block) * 64,
                "ordered_scores_sha256": "d" * 64,
                "spearman_by_component": [],
                "successive_path_length": 1.0,
            }
            for block in (1, 2, 3)
        ],
    }
    result = TOOL._path_free_descriptive_summary(report)
    encoded = json.dumps(result)
    assert result["specimen_count"] == 11
    assert result["block_count"] == 3
    assert [item["block_ordinal"] for item in result["ordered_paths"]] == [1, 2, 3]
    assert "specimen_ids" not in encoded
    assert '"block":' not in encoded
    assert "S0" not in encoded


def test_public_descriptive_projection_refuses_wrong_exact_cardinality() -> None:
    report = {"specimen_ids": ["A"], "block_ids": [1, 2, 3], "ordered_paths": [{}, {}, {}]}
    with pytest.raises(ValueError, match="11-by-3"):
        TOOL._path_free_descriptive_summary(report)


def test_private_io_is_atomic_mode_0600_and_rejects_linked_leaf(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    destination = private / "result.json"
    record = TOOL._write_private_json(destination, {"ok": True})
    if os.name != "nt":  # Windows uses the containing profile ACL.
        assert destination.stat().st_mode & 0o777 == 0o600
    assert record["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert json.loads(TOOL._read_private_bytes(destination, limit=1000)) == {"ok": True}

    destination.unlink()
    victim = private / "victim.json"
    victim.write_text("unchanged")
    os.symlink(victim, destination)
    with pytest.raises(ValueError, match="must not be linked"):
        TOOL._write_private_json(destination, {"changed": True})
    assert victim.read_text() == "unchanged"


def test_private_reader_rejects_public_mode_and_oversize(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "value.json"
    path.write_bytes(b"12345")
    os.chmod(path, 0o644)
    if os.name != "nt":
        with pytest.raises(ValueError, match="mode-0600"):
            TOOL._read_private_bytes(path, limit=10)
    os.chmod(path, 0o600)
    with pytest.raises(ValueError, match="mode-0600"):
        TOOL._read_private_bytes(path, limit=4)


def test_private_output_rejects_linked_parent(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    os.symlink(private, linked)
    with pytest.raises(ValueError, match="private non-linked directory"):
        TOOL._write_private_json(linked / "result.json", {"ok": True})


def test_public_writer_rejects_linked_leaf_without_touching_target(tmp_path: Path) -> None:
    victim = tmp_path / "victim.json"
    victim.write_text("unchanged")
    output = tmp_path / "report.json"
    os.symlink(victim, output)
    with pytest.raises(ValueError, match="must not be linked"):
        TOOL._write_public_json(output, {"changed": True})
    assert victim.read_text() == "unchanged"


def test_public_report_admission_is_bounded_and_rejects_links(tmp_path: Path, monkeypatch) -> None:
    report = tmp_path / "report.json"
    report.write_text("{}")
    linked = tmp_path / "linked.json"
    os.symlink(report, linked)
    assert TOOL.validate_checked_report(linked) == ["public report must be regular and non-linked"]

    monkeypatch.setattr(TOOL, "MAX_PUBLIC_REPORT_BYTES", 1)
    assert TOOL.validate_checked_report(report) == ["public report exceeds its byte ceiling"]
    with pytest.raises(ValueError, match="byte ceiling"):
        TOOL._write_public_json(tmp_path / "large.json", {"value": "too large"})


def test_run_refuses_existing_workspace_b_before_spawning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace_a = tmp_path / "a"
    workspace_a.mkdir()
    (workspace_a / "spectra_platform.db").write_bytes(b"db")
    workspace_b = tmp_path / "b"
    workspace_b.mkdir()
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(TOOL, "_run_stage", forbidden)
    args = type(
        "Args",
        (),
        {
            "workspace_a": workspace_a,
            "workspace_b": workspace_b,
            "archive": tmp_path / "archive.sherpa",
            "private_report": tmp_path / "private.json",
            "public_report": tmp_path / "public.json",
            "project_id": 1,
            "experiment_id": 2,
        },
    )()
    with pytest.raises(ValueError, match="must be absent"):
        TOOL._run(args)
    assert called is False


@pytest.mark.parametrize(
    ("archive_name", "private_name", "public_name", "message"),
    [
        ("same", "private.json", "same", "paths collide"),
        ("archive.sherpa", "same", "same", "paths collide"),
    ],
)
def test_run_refuses_output_collisions_before_spawning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    archive_name: str,
    private_name: str,
    public_name: str,
    message: str,
) -> None:
    workspace_a = tmp_path / "a"
    workspace_a.mkdir()
    (workspace_a / "spectra_platform.db").write_bytes(b"db")
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(TOOL, "_run_stage", forbidden)
    args = type(
        "Args",
        (),
        {
            "workspace_a": workspace_a,
            "workspace_b": tmp_path / "b",
            "archive": tmp_path / archive_name,
            "private_report": tmp_path / private_name,
            "public_report": tmp_path / public_name,
            "project_id": 1,
            "experiment_id": 2,
        },
    )()
    with pytest.raises(ValueError, match=message):
        TOOL._run(args)
    assert called is False


def test_run_refuses_output_inside_source_workspace_before_spawning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace_a = tmp_path / "a"
    workspace_a.mkdir()
    (workspace_a / "spectra_platform.db").write_bytes(b"db")
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(TOOL, "_run_stage", forbidden)
    args = type(
        "Args",
        (),
        {
            "workspace_a": workspace_a,
            "workspace_b": tmp_path / "b",
            "archive": workspace_a / "models" / "archive.sherpa",
            "private_report": tmp_path / "private.json",
            "public_report": tmp_path / "public.json",
            "project_id": 1,
            "experiment_id": 2,
        },
    )()
    with pytest.raises(ValueError, match="outside workspace A"):
        TOOL._run(args)
    assert called is False


def test_checked_report_digest_fails_closed_on_any_scientific_mutation(tmp_path: Path, monkeypatch) -> None:
    report = json.loads(CHECKED_REPORT_PATH.read_bytes())
    path = tmp_path / "report.json"
    path.write_bytes(TOOL._json_bytes(report))
    monkeypatch.setattr(TOOL, "CHECKED_REPORT_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    assert TOOL.validate_checked_report(path) == []

    mutations = [
        ("claim", lambda value: value.update({"claim_boundary": "botanical authenticity validated"})),
        ("nonclaims", lambda value: value.update({"nonclaims": []})),
        ("private", lambda value: value.update({"private_evidence_authority": {}})),
        ("portability", lambda value: value.update({"workflow_and_artifact_portability": {}})),
        ("workflow", lambda value: value["scientific_result"].update({"workflow_authority": {}})),
        (
            "selection",
            lambda value: value["scientific_result"]["selection"].update({"selected_values_sha256": "b" * 64}),
        ),
        (
            "pca",
            lambda value: value["scientific_result"]["pca"].update({"explained_variance_ratio": [1.0, 0.0, 0.0]}),
        ),
        (
            "descriptive",
            lambda value: value["scientific_result"]["descriptive_report"].update({"block_r_squared": 0.5}),
        ),
    ]
    for _, mutate in mutations:
        changed = copy.deepcopy(report)
        mutate(changed)
        path.write_bytes(TOOL._json_bytes(changed))
        monkeypatch.setattr(TOOL, "CHECKED_REPORT_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
        assert TOOL.validate_checked_report(path), "semantic mutation passed after its file digest was refreshed"


def test_model_detail_accepts_exact_pca_axis_value_projection() -> None:
    from spectra_sherpa.app.api.v1.routes.models import _model_to_detail
    from spectra_sherpa.app.models.model_artifact import ModelArtifact

    now = datetime.utcnow()
    model = ModelArtifact(
        artifact_uid="00000000-0000-4000-8000-000000000001",
        user_id=1,
        model_type="pca",
        name="PCA",
        artifact_dir="private",
        n_features=3,
        n_components=2,
        feature_axis_json=json.dumps([1000.0, 900.0, 800.0]),
        is_active=True,
        is_deploy_ready=False,
        created_at=now,
        updated_at=now,
    )
    detail = _model_to_detail(model)
    assert detail.feature_axis == [1000.0, 900.0, 800.0]


def test_phase6_tool_cannot_fit_or_recompute_pca() -> None:
    source = TOOL_PATH.read_text()
    forbidden = (
        "from sklearn",
        "import sklearn",
        "fit_pca(",
        "np.linalg.svd",
        "SklearnPCA",
    )
    assert all(marker not in source for marker in forbidden)


def test_base_profile_import_guard_denies_only_spectrochempy() -> None:
    guard = TOOL._DenySpectroChemPy()
    with pytest.raises(ModuleNotFoundError, match="base-profile proof"):
        guard.find_spec("spectrochempy")
    with pytest.raises(ModuleNotFoundError, match="base-profile proof"):
        guard.find_spec("spectrochempy.core.dataset")
    assert guard.find_spec("numpy") is None


def test_optional_profile_requires_exact_qualified_distribution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TOOL.importlib.metadata, "version", lambda name: TOOL.EXPECTED_SCP_VERSION)
    assert TOOL._require_installed_scp_distribution() == TOOL.EXPECTED_SCP_VERSION

    monkeypatch.setattr(TOOL.importlib.metadata, "version", lambda name: "0.8.2")
    with pytest.raises(RuntimeError, match="requires SpectroChemPy 0.8.1"):
        TOOL._require_installed_scp_distribution()

    def absent(name: str) -> str:
        raise TOOL.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(TOOL.importlib.metadata, "version", absent)
    with pytest.raises(RuntimeError, match="requires the qualified"):
        TOOL._require_installed_scp_distribution()


def _selection_wires() -> tuple[dict, dict, np.ndarray]:
    source = np.arange(np.prod(TOOL.EXPECTED_SOURCE_SHAPE), dtype=np.float64).reshape(TOOL.EXPECTED_SOURCE_SHAPE)
    axis = np.arange(TOOL.EXPECTED_SOURCE_SHAPE[1], dtype=np.float64)
    mask = np.zeros(TOOL.EXPECTED_SOURCE_SHAPE[1], dtype=np.bool_)
    mask[: TOOL.EXPECTED_SELECTED_SHAPE[1]] = True
    y_axis = {"labels": [f"S{i}" for i in range(33)], "sample_table": {"sample_id": [f"S{i}" for i in range(33)]}}
    common = {
        "dataset_id": TOOL.EXPECTED_DATASET_ID,
        "title": "Avatar essential-oil three-block corpus",
        "units": "absorbance",
        "data_role": "X_spectra",
        "data_modality": "spectral",
        "domain": {"technique": "IR"},
        "target_context": None,
        "is_time_series": False,
    }
    source_wire = {
        **common,
        "shape": TOOL.EXPECTED_SOURCE_SHAPE,
        "data": source.tolist(),
        "x_axis": {
            "data": axis.tolist(),
            "axis_class": "SpectralAxis",
            "title": "Wavenumber",
            "units": "cm-1",
        },
        "y_axis": y_axis,
    }
    selected_wire = {
        **common,
        "shape": TOOL.EXPECTED_SELECTED_SHAPE,
        "data": source[:, mask].tolist(),
        "x_axis": {
            "data": axis[mask].tolist(),
            "axis_class": "SpectralAxis",
            "title": "Wavenumber",
            "units": "cm-1",
        },
        "y_axis": copy.deepcopy(y_axis),
    }
    return source_wire, selected_wire, mask


def test_selection_output_is_exact_source_projection() -> None:
    source, selected, mask = _selection_wires()
    TOOL._require_exact_selection_projection(source, selected, mask)

    wrong_values = copy.deepcopy(selected)
    wrong_values["data"][0][1] += 1.0
    with pytest.raises(ValueError, match="exact masked source"):
        TOOL._require_exact_selection_projection(source, wrong_values, mask)

    wrong_axis = copy.deepcopy(selected)
    wrong_axis["x_axis"]["data"][1] += 1.0
    with pytest.raises(ValueError, match="source-axis projection"):
        TOOL._require_exact_selection_projection(source, wrong_axis, mask)

    wrong_labels = copy.deepcopy(selected)
    wrong_labels["y_axis"]["labels"][0:2] = reversed(wrong_labels["y_axis"]["labels"][0:2])
    with pytest.raises(ValueError, match="sample labels"):
        TOOL._require_exact_selection_projection(source, wrong_labels, mask)

    wrong_semantics = copy.deepcopy(selected)
    wrong_semantics["x_axis"]["axis_class"] = "FeatureAxis"
    with pytest.raises(ValueError, match="spectral semantics"):
        TOOL._require_exact_selection_projection(source, wrong_semantics, mask)

    stale_shape = copy.deepcopy(source)
    stale_shape["data"] = np.asarray(stale_shape["data"]).reshape(1868, 33).tolist()
    with pytest.raises(ValueError, match="shape"):
        TOOL._require_exact_selection_projection(stale_shape, selected, mask)


def test_pca_outputs_preserve_sample_and_feature_axis_semantics() -> None:
    _, selected, _ = _selection_wires()
    scores = {"y_axis": copy.deepcopy(selected["y_axis"])}
    loadings = {"x_axis": copy.deepcopy(selected["x_axis"])}
    TOOL._require_pca_output_semantics(scores, loadings, selected)

    wrong_scores = copy.deepcopy(scores)
    wrong_scores["y_axis"]["labels"][0:2] = reversed(wrong_scores["y_axis"]["labels"][0:2])
    with pytest.raises(ValueError, match="scores changed sample"):
        TOOL._require_pca_output_semantics(wrong_scores, loadings, selected)

    wrong_loadings = copy.deepcopy(loadings)
    wrong_loadings["x_axis"]["units"] = "nm"
    with pytest.raises(ValueError, match="feature-axis semantics"):
        TOOL._require_pca_output_semantics(scores, wrong_loadings, selected)


def _pca_state_and_outputs() -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict]:
    loadings = np.zeros(TOOL.EXPECTED_LOADING_SHAPE, dtype=np.float64)
    loadings[0, 0] = loadings[1, 1] = loadings[2, 2] = 1.0
    explained = np.asarray([0.9, 0.06, 0.02], dtype=np.float64)
    eigenvalues = np.asarray([9.0, 0.6, 0.2], dtype=np.float64)
    axis = np.arange(TOOL.EXPECTED_SELECTED_SHAPE[1], dtype=np.float64)
    axis_wire = {"units": "cm-1", "title": "Wavenumber", "quantity": "wavenumber"}
    state = {
        "schema_version": "spectrasherpa.model.pca-state/4",
        "serializer": "spectrasherpa.model-artifact.pca/3",
        "source_contract_digest": "c" * 64,
        "state_content_digest": "d" * 64,
        "arrays": {
            "center": None,
            "explained_variance": eigenvalues.tolist(),
            "explained_variance_ratio": explained.tolist(),
            "loadings": loadings.tolist(),
            "mean": np.zeros(TOOL.EXPECTED_SELECTED_SHAPE[1]).tolist(),
            "offset": None,
            "scale": None,
        },
        "metadata": {
            "feature_axis_labels_sha256": None,
            "feature_axis_units": "cm-1",
            "feature_axis_quantity": "wavenumber",
            "feature_axis_values_sha256": TOOL._array_digest(axis),
            "input_axis_identity_sha256": "a" * 64,
            "input_shape": list(TOOL.EXPECTED_SELECTED_SHAPE),
            "n_components": 3,
            "n_features": TOOL.EXPECTED_SELECTED_SHAPE[1],
            "reference_samples": TOOL.EXPECTED_SELECTED_SHAPE[0],
            "rank_projection_strategy": "none",
            "scale_mode": None,
            "scaled": False,
            "sign_rule": "largest_absolute_loading_positive",
            "standardized": False,
        },
    }
    return state, loadings, explained, eigenvalues, axis, axis_wire


def test_pca_state_refuses_divergent_node_outputs() -> None:
    state, loadings, explained, eigenvalues, axis, axis_wire = _pca_state_and_outputs()
    kwargs = {
        "loadings": loadings,
        "explained": explained,
        "eigenvalues": eigenvalues,
        "selected_axis": axis,
        "selected_axis_wire": axis_wire,
        "expected_contract_digest": "c" * 64,
        "expected_input_axis_identity_sha256": "a" * 64,
    }
    TOOL._require_pca_state_output_binding(state, **kwargs)
    changed = loadings.copy()
    changed[0, 2] = 1.0
    with pytest.raises(ValueError, match="arrays differ"):
        TOOL._require_pca_state_output_binding(state, **{**kwargs, "loadings": changed})
    with pytest.raises(ValueError, match="arrays differ"):
        TOOL._require_pca_state_output_binding(state, **{**kwargs, "explained": explained + 0.01})


def test_persisted_artifact_refuses_wrong_feature_axis() -> None:
    state, loadings, explained, eigenvalues, axis, axis_wire = _pca_state_and_outputs()
    scores = np.zeros(TOOL.EXPECTED_SCORE_SHAPE, dtype=np.float64)
    selected = np.zeros(TOOL.EXPECTED_SELECTED_SHAPE, dtype=np.float64)
    mask = np.zeros(TOOL.EXPECTED_SOURCE_SHAPE[1], dtype=np.bool_)
    mask[: TOOL.EXPECTED_SELECTED_SHAPE[1]] = True
    inventory = {
        "loadings": {"shape": TOOL.EXPECTED_LOADING_SHAPE, "dtype": "float64"},
        "explained_variance_ratio": {"shape": [3], "dtype": "float64"},
        "explained_variance": {"shape": [3], "dtype": "float64"},
        "mean": {"shape": [TOOL.EXPECTED_SELECTED_SHAPE[1]], "dtype": "float64"},
        "scores": {"shape": TOOL.EXPECTED_SCORE_SHAPE, "dtype": "float64"},
    }
    manifest = {
        "model_type": "pca",
        "serializer": "spectrasherpa.model-artifact.pca/3",
        "n_components": 3,
        "n_features": TOOL.EXPECTED_SELECTED_SHAPE[1],
        "standardized": False,
        "scaled": False,
        "scale_mode": None,
        "feature_axis_class": "SpectralAxis",
        "feature_axis_units": "cm-1",
        "feature_axis_title": "Wavenumber",
        "feature_axis": axis.tolist(),
        "selected_features": axis.tolist(),
        "feature_mask": mask.tolist(),
        "arrays": inventory,
        "metrics": {"explained_variance_ratio": explained.tolist()},
        "training_data_hash": TOOL._training_data_hash(selected),
        "integrity_hash": "i" * 64,
        "artifact_uid": "u",
    }
    inspection = {
        "artifact_uid": "u",
        "arrays": {name: {**value, "mean": 0.0} for name, value in inventory.items()},
        "manifest": manifest,
    }
    detail = {
        "artifact_uid": "u",
        "integrity_hash": "i" * 64,
        "feature_axis": axis.tolist(),
        "training_data_hash": TOOL._training_data_hash(selected),
    }
    persisted_arrays = {
        "loadings": loadings,
        "explained_variance_ratio": explained,
        "explained_variance": eigenvalues,
        "mean": np.asarray(state["arrays"]["mean"], dtype=np.float64),
        "scores": scores,
    }
    kwargs = {
        "persisted_manifest": manifest,
        "persisted_arrays": persisted_arrays,
        "selected_axis": axis,
        "selected_axis_wire": axis_wire,
        "loadings": loadings,
        "explained": explained,
        "eigenvalues": eigenvalues,
        "scores": scores,
        "state_arrays": state["arrays"],
        "mask": mask,
        "selected": selected,
    }
    TOOL._require_artifact_binding(inspection, detail, **kwargs)
    wrong = copy.deepcopy(inspection)
    wrong["manifest"]["feature_axis"][1] += 1.0
    with pytest.raises(ValueError, match="differs"):
        TOOL._require_artifact_binding(wrong, detail, **kwargs)

    wrong_arrays = dict(persisted_arrays)
    wrong_arrays["loadings"] = loadings.copy()
    wrong_arrays["loadings"][0, 2] = 1.0
    with pytest.raises(ValueError, match="array loadings differs"):
        TOOL._require_artifact_binding(inspection, detail, **{**kwargs, "persisted_arrays": wrong_arrays})

    wrong_mask = mask.copy()
    wrong_mask[[0, -1]] = ~wrong_mask[[0, -1]]
    with pytest.raises(ValueError, match="not cross-bound"):
        TOOL._require_artifact_binding(inspection, detail, **{**kwargs, "mask": wrong_mask})
