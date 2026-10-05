from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.collection_assembly import CollectionMember, assemble_collection, collection_manifest
from spectra_sherpa.app.lib.collection_definition import (
    COLLECTION_DEFINITION_SCHEMA,
    apply_collection_definition,
    project_collection_definition,
    scientific_collection_identity,
    validate_collection_definition,
)
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
from spectra_sherpa.app.models.project_data_source import ProjectDataSource
from spectra_sherpa.app.services.collection_definitions import (
    collection_definition_path,
    read_collection_definition,
    write_collection_definition,
)
from spectra_sherpa.app.services.dag.nodes.data import loaders as data_loaders
from spectra_sherpa.app.services.project_data_sources import describe_node_data_source
from spectra_sherpa.core.execution_runtime import ExecutionRuntime, ResolvedExperimentCollection, ResolvedExperimentFile
from spectra_sherpa.io import ingest, select_asset
from spectra_sherpa.io.types import SourceMember


def _dataset(label: str, values: list[float]) -> SherpaDataset:
    return SherpaDataset(
        X=np.asarray([values], dtype=np.float64),
        feature_axis=SpectralAxis(
            values=np.asarray([4000.0, 3000.0], dtype=np.float64),
            units="cm-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(
            values=np.asarray([1_700_000_000.0]),
            labels=[label],
            title="Acquisition timestamp (UTC)",
            units="s",
            sample_table={"acquired_at": ["2026-08-23T13:00:00-07:00"]},
        ),
        domain=DomainContext(
            technique="IR",
            expected_units="cm-1",
            data_quantity="Absorbance",
            instrument="Thermo Nicolet OMNIC",
        ),
        title=label,
        units="absorbance",
        data_role="X_spectra",
    )


def _members() -> list[CollectionMember]:
    return [
        CollectionMember(_dataset("parser-b", [3.0, 4.0]), "raw/b.spa", 20, "b" * 64, asset_id="spectrum"),
        CollectionMember(_dataset("parser-a", [1.0, 2.0]), "raw/a.spa", 10, "a" * 64, asset_id="spectrum"),
    ]


def test_collection_accepts_cosmetic_axis_unit_and_title_variants() -> None:
    members = _members()
    members[1].dataset.feature_axis = SpectralAxis(
        values=np.asarray([4000.0, 3000.0]),
        units="cm⁻¹",
        title="Wavenumber (cm-1)",
    )

    result = assemble_collection(members, title="Alias-compatible collection")

    assert result.shape == (2, 2)


def test_collection_refuses_raman_shift_as_absolute_wavenumber() -> None:
    members = _members()
    members[1].dataset.feature_axis = SpectralAxis(
        values=np.asarray([4000.0, 3000.0]),
        units="cm-1",
        title="Raman shift",
    )

    with pytest.raises(ValueError, match="cannot combine 'wavenumber' and 'raman_shift'"):
        assemble_collection(members, title="Invalid collection")


def test_collection_grid_error_names_recorded_harmonization_node() -> None:
    members = _members()
    members[1].dataset.feature_axis = SpectralAxis(
        values=np.asarray([3999.0, 2999.0]),
        units="cm-1",
        title="Wavenumber",
    )

    with pytest.raises(ValueError, match="preprocess.wavenumber_align"):
        assemble_collection(members, title="Grid-mismatched collection")


def test_collection_accepts_feature_table_axes_identified_by_column_labels() -> None:
    dataset = SherpaDataset(
        X=np.asarray([[5.1, 3.5, 1.4, 0.2], [6.3, 3.3, 6.0, 2.5]], dtype=np.float64),
        feature_axis=FeatureAxis(
            labels=["sepal length (cm)", "sepal width (cm)", "petal length (cm)", "petal width (cm)"],
            title="Property",
        ),
        sample_axis=SampleAxis(labels=["setosa-001", "virginica-001"], title="Sample"),
        data_role="X_features",
    )
    member = CollectionMember(dataset, "raw/sklearn_iris.csv", 100, "a" * 64)

    result = assemble_collection([member], title="Iris")

    assert result.shape == (2, 4)
    assert result.feature_axis.values is None
    assert result.feature_axis.labels == dataset.feature_axis.labels


def test_collection_rejects_coordinate_free_unlabeled_feature_axes() -> None:
    dataset = SherpaDataset(
        X=np.asarray([[1.0, 2.0]], dtype=np.float64),
        feature_axis=FeatureAxis(title="Property"),
        sample_axis=SampleAxis(labels=["sample-001"], title="Sample"),
        data_role="X_features",
    )
    member = CollectionMember(dataset, "raw/unlabeled.csv", 10, "a" * 64)

    with pytest.raises(ValueError, match="lacks typed axes"):
        assemble_collection([member], title="Unlabeled")


def test_collection_rejects_spectral_axes_without_numeric_coordinates() -> None:
    dataset = SherpaDataset(
        X=np.asarray([[1.0, 2.0]], dtype=np.float64),
        feature_axis=SpectralAxis(labels=["band-a", "band-b"], title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["sample-001"], title="Sample"),
        data_role="X_spectra",
    )
    member = CollectionMember(dataset, "raw/spectrum.csv", 10, "a" * 64)

    with pytest.raises(ValueError, match="lacks typed axes"):
        assemble_collection([member], title="Invalid spectrum")


def _definition() -> dict[str, object]:
    domain = DomainContext(
        technique="IR",
        sample_type="essential oil",
        measurement_mode="ATR absorbance",
        expected_units="cm-1",
        data_quantity="absorbance",
        instrument="Avatar 370",
    ).model_dump(mode="json", exclude_none=False)
    columns = ["sample_id", "specimen_id", "block", "acquisition_order"]
    return {
        "schema_version": COLLECTION_DEFINITION_SCHEMA,
        "columns": columns,
        "collection": {
            "dataset_id": "avatar-essential-oils/1:canonical-phase4",
            "title": "Avatar essential-oil three-block corpus",
            "units": "absorbance",
            "data_role": "X_spectra",
            "domain": domain,
            "sample_axis": {"title": "Avatar collection", "units": None, "values_policy": "omit"},
        },
        "rows": [
            {
                "file_name": "raw/a.spa",
                "sha256": "a" * 64,
                "asset_id": "spectrum",
                "source_row_index": 0,
                "sample_id": "A__B1",
                "annotations": {
                    "sample_id": "A__B1",
                    "specimen_id": "A",
                    "block": 1,
                    "acquisition_order": 1,
                },
            },
            {
                "file_name": "raw/b.spa",
                "sha256": "b" * 64,
                "asset_id": "spectrum",
                "source_row_index": 0,
                "sample_id": "B__B1",
                "annotations": {
                    "sample_id": "B__B1",
                    "specimen_id": "B",
                    "block": 1,
                    "acquisition_order": 2,
                },
            },
        ],
    }


def test_definition_drives_order_and_complete_target_free_collection_semantics() -> None:
    definition = validate_collection_definition(_definition())
    result = apply_collection_definition(_members(), definition)

    np.testing.assert_array_equal(result.X, [[1.0, 2.0], [3.0, 4.0]])
    assert result.title == "Avatar essential-oil three-block corpus"
    assert result.dataset_id == "avatar-essential-oils/1:canonical-phase4"
    assert result.sample_axis is not None
    assert result.sample_axis.labels == ["A__B1", "B__B1"]
    assert result.sample_axis.values is None
    assert list(result.sample_axis.sample_table or {}) == _definition()["columns"]
    assert result.sample_axis.sample_table["specimen_id"] == ["A", "B"]
    assert result.domain.sample_type == "essential oil"
    assert result.domain.measurement_mode == "ATR absorbance"
    assert result.domain.instrument == "Avatar 370"
    assert result.target is None
    assert result.sample_axis.classes is None
    source = result.meta["source_collection"]
    assert source["collection_definition_sha256"] == definition.sha256
    assert len(source["scientific_collection_sha256"]) == 64


def test_definition_projects_exact_member_without_losing_curated_row_semantics() -> None:
    definition = validate_collection_definition(_definition())
    selected = [_members()[1]]

    projected = project_collection_definition(definition, selected)
    result = apply_collection_definition(selected, projected)

    assert projected.sha256 != definition.sha256
    assert [row["file_name"] for row in projected.payload["rows"]] == ["raw/a.spa"]
    assert result.sample_axis is not None
    assert result.sample_axis.labels == ["A__B1"]
    assert result.sample_axis.sample_table == {
        "sample_id": ["A__B1"],
        "specimen_id": ["A"],
        "block": [1],
        "acquisition_order": [1],
    }
    np.testing.assert_array_equal(result.X, [[1.0, 2.0]])
    source = result.meta["source_collection"]
    assert source["collection_definition_sha256"] == projected.sha256
    assert len(source["scientific_collection_sha256"]) == 64


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda d: d["rows"].pop(), "cover every"),
        (lambda d: d["rows"].append(copy.deepcopy(d["rows"][0])), "duplicate"),
        (lambda d: d["rows"][0].__setitem__("sha256", "c" * 64), "source/asset"),
        (lambda d: d["rows"][0].__setitem__("asset_id", "wrong"), "source/asset"),
        (lambda d: d["rows"][0].__setitem__("source_row_index", 1), "native order"),
        (lambda d: d["rows"][0]["annotations"].__setitem__("sample_id", "wrong"), "not aligned"),
        (lambda d: d["rows"][0]["annotations"].__setitem__("block", float("nan")), "non-finite"),
        (lambda d: d["rows"][0]["annotations"].__setitem__("block", 2**53), "lossless JSON"),
        (lambda d: d.__setitem__("unexpected", True), "invalid schema"),
    ],
)
def test_definition_mutations_fail_closed(mutation, message: str) -> None:
    payload = copy.deepcopy(_definition())
    mutation(payload)
    if message in {"cover every", "source/asset", "native order"}:
        definition = validate_collection_definition(payload)
        with pytest.raises(ValueError, match=message):
            apply_collection_definition(_members(), definition)
    else:
        with pytest.raises(ValueError, match=message):
            validate_collection_definition(payload)


def test_definition_refuses_target_and_classes() -> None:
    members = _members()
    members[1].dataset.target = np.asarray([1.0])
    with pytest.raises(ValueError, match="target-free"):
        apply_collection_definition(members, validate_collection_definition(_definition()))

    members = _members()
    members[1].dataset.sample_axis = SampleAxis(labels=["parser-a"], classes=np.asarray([1]))
    with pytest.raises(ValueError, match="sample classes"):
        apply_collection_definition(members, validate_collection_definition(_definition()))


def test_definition_budget_refuses_before_canonical_json_materialization(monkeypatch) -> None:
    from spectra_sherpa.app.lib import collection_definition

    payload = _definition()
    columns = ["sample_id", "specimen_id", "block", *[f"note_{index}" for index in range(61)]]
    payload["columns"] = columns
    payload["rows"] = []
    for index in range(17):
        annotations = {column: "x" * 4096 for column in columns}
        annotations.update({"sample_id": f"sample-{index}", "specimen_id": f"specimen-{index}", "block": 1})
        payload["rows"].append(
            {
                "file_name": f"raw/{index}.spa",
                "sha256": f"{index:064x}",
                "asset_id": "spectrum",
                "source_row_index": 0,
                "sample_id": f"sample-{index}",
                "annotations": annotations,
            }
        )
    monkeypatch.setattr(
        collection_definition.json,
        "dumps",
        lambda *_args, **_kwargs: pytest.fail("oversized definition reached aggregate JSON materialization"),
    )
    with pytest.raises(ValueError, match="4 MiB"):
        validate_collection_definition(payload)


def test_combined_identity_changes_with_source_or_definition() -> None:
    members = _members()
    source = collection_manifest(members)
    definition = validate_collection_definition(_definition())
    baseline_dataset = apply_collection_definition(members, definition)
    baseline = scientific_collection_identity(source, definition, baseline_dataset)

    changed = _definition()
    changed["collection"]["title"] = "Changed title"
    changed_definition = validate_collection_definition(changed)
    changed_dataset = apply_collection_definition(members, changed_definition)
    assert (
        scientific_collection_identity(source, changed_definition, changed_dataset)["scientific_collection_sha256"]
        != baseline["scientific_collection_sha256"]
    )
    changed_source = dict(source)
    changed_source["manifest_digest"] = "f" * 64
    assert (
        scientific_collection_identity(changed_source, definition, baseline_dataset)["scientific_collection_sha256"]
        != baseline["scientific_collection_sha256"]
    )


def test_definition_storage_is_canonical_private_and_symlink_safe(tmp_path: Path, monkeypatch) -> None:
    from spectra_sherpa.app.services import collection_definitions

    monkeypatch.setattr(
        collection_definitions,
        "experiment_dir",
        lambda experiment_id: tmp_path / f"exp_{experiment_id}",
    )
    definition = write_collection_definition(7, _definition())
    path = collection_definition_path(7)
    assert path.read_bytes() == definition.canonical_bytes
    if os.name != "nt":  # Windows uses the containing profile ACL.
        assert path.stat().st_mode & 0o777 == 0o600
    assert read_collection_definition(7) == definition
    path.chmod(0o644)
    if os.name != "nt":
        with pytest.raises(ValueError, match="private mode 0600"):
            read_collection_definition(7)
    path.chmod(0o600)

    path.unlink()
    victim = tmp_path / "victim.json"
    victim.write_text("unchanged")
    path.symlink_to(victim)
    with pytest.raises(ValueError, match="not a regular file"):
        write_collection_definition(7, _definition())
    assert victim.read_text(encoding="utf-8") == "unchanged"


def test_definition_storage_refuses_noncanonical_or_tampered_bytes(tmp_path: Path, monkeypatch) -> None:
    from spectra_sherpa.app.services import collection_definitions

    monkeypatch.setattr(
        collection_definitions,
        "experiment_dir",
        lambda experiment_id: tmp_path / f"exp_{experiment_id}",
    )
    path = collection_definition_path(8)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_definition(), indent=2))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="not canonical"):
        read_collection_definition(8)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        read_collection_definition(8)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.asyncio
async def test_registered_project_collection_reuses_exact_definition_and_combined_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = [tmp_path / "b.spa", tmp_path / "a.spa"]
    payloads = [b"b", b"a"]
    resolved = []
    for index, (path, payload) in enumerate(zip(paths, payloads, strict=True), 1):
        path.write_bytes(payload)
        resolved.append(
            ResolvedExperimentFile(
                path=str(path),
                original_file_path=f"raw/{path.name}",
                created_datetime=f"2026-08-24T00:00:0{index}+00:00",
                file_id=index,
                stage="raw",
                size_bytes=1,
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )

    definition_payload = _definition()
    definition_payload["rows"][0]["sha256"] = hashlib.sha256(b"a").hexdigest()
    definition_payload["rows"][1]["sha256"] = hashlib.sha256(b"b").hexdigest()
    definition = validate_collection_definition(definition_payload)

    class Resolver:
        async def resolve_experiment_collection(self, *, experiment_id: int, stage: str = "raw"):
            assert (experiment_id, stage) == (7, "raw")
            return ResolvedExperimentCollection(
                7,
                "Exact collection",
                tuple(resolved),
                collection_definition_bytes=definition.canonical_bytes,
            )

    def load_member(_self, file_path, **kwargs):
        path = Path(file_path)
        dataset = _dataset(f"parser-{path.stem}", [1.0, 2.0] if path.stem == "a" else [3.0, 4.0])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return data_loaders._LoadedDataset(
            dataset=dataset,
            file_name=kwargs["file_name"],
            prepared_overrides={},
            source_members=(SourceMember(path.name, digest, 1),),
            selected_asset_id="spectrum",
        )

    monkeypatch.setattr(data_loaders.ExperimentDatasetReader, "_load_file", load_member)
    members = [
        CollectionMember(
            _dataset("parser-b", [3.0, 4.0]),
            "raw/b.spa",
            1,
            hashlib.sha256(b"b").hexdigest(),
            asset_id="spectrum",
        ),
        CollectionMember(
            _dataset("parser-a", [1.0, 2.0]),
            "raw/a.spa",
            1,
            hashlib.sha256(b"a").hexdigest(),
            asset_id="spectrum",
        ),
    ]
    manifest = collection_manifest(list(reversed(members)))
    projected = apply_collection_definition(list(reversed(members)), definition)
    identity = scientific_collection_identity(manifest, definition, projected)
    node = data_loaders.LoadGroupNode(
        "group",
        {
            "source_mode": "experiment_collection",
            "experiment_id": 7,
            "stage": "raw",
            "asset_id": "spectrum",
            "source_manifest_sha256": manifest["manifest_digest"],
            "collection_definition_sha256": definition.sha256,
            "scientific_collection_sha256": identity["scientific_collection_sha256"],
        },
    )
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=Resolver()))

    result = await node.execute()

    np.testing.assert_array_equal(result.X, [[1.0, 2.0], [3.0, 4.0]])
    assert result.sample_axis.labels == ["A__B1", "B__B1"]
    assert result.meta["source_collection"]["scientific_collection_sha256"] == identity["scientific_collection_sha256"]

    stale = data_loaders.LoadGroupNode(
        "stale",
        {
            **node.parameters,
            "collection_definition_sha256": "0" * 64,
        },
    )
    stale.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=Resolver()))
    with pytest.raises(ValueError, match="saved collection definition;.*re-import.*rebind"):
        await stale.execute()


def test_checked_avatar_definition_binds_phase4_projection() -> None:
    root = Path(__file__).resolve().parents[3]
    path = root / "docs/evidence/avatar-essential-oils-v1-collection-definition.json"
    definition = validate_collection_definition(json.loads(path.read_text(encoding="utf-8")))
    assert definition.canonical_bytes == path.read_bytes()
    assert definition.sha256 == "524960aed6d2ef8294a7ffed0056f7287a38b611462c12599fc2bd7cf1222db2"
    assert len(definition.payload["rows"]) == 33
    assert len(definition.payload["columns"]) == 14
    assert len({row["annotations"]["specimen_id"] for row in definition.payload["rows"]}) == 11
    assert {row["annotations"]["block"] for row in definition.payload["rows"]} == {1, 2, 3}
    assert definition.payload["collection"] == {
        "dataset_id": "avatar-essential-oils/1:canonical-phase4",
        "title": "Avatar essential-oil three-block corpus",
        "units": "absorbance",
        "data_role": "X_spectra",
        "domain": DomainContext(
            technique="IR",
            sample_type="essential oil",
            measurement_mode="ATR absorbance",
            expected_units="absorbance",
            data_quantity="absorbance",
            instrument="Thermo Nicolet Avatar 370",
        ).model_dump(mode="json", exclude_none=False),
        "sample_axis": {"title": "Acquisition", "units": None, "values_policy": "omit"},
    }


def test_collection_definition_has_one_shared_production_application_authority() -> None:
    root = Path(__file__).resolve().parents[1] / "src/spectra_sherpa"
    importers = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if path.name != "collection_definition.py" and "apply_collection_definition" in path.read_text(encoding="utf-8")
    }
    assert importers == {
        "app/api/v1/routes/builder.py",
        "app/services/dag/nodes/data/loaders.py",
        "app/services/model_application.py",
        "sdk/data.py",
    }


def test_project_source_fingerprint_binds_definition_and_combined_identity() -> None:
    parameters = {
        "source_mode": "experiment_collection",
        "experiment_id": 7,
        "stage": "raw",
        "asset_id": "spectrum",
        "source_manifest_sha256": "a" * 64,
        "collection_definition_sha256": "b" * 64,
        "scientific_collection_sha256": "c" * 64,
    }
    baseline = describe_node_data_source({"id": "source", "type": "data.load_group", "parameters": parameters})
    assert baseline is not None
    assert "definition:" + "b" * 64 in baseline.source_ref
    assert "scientific:" + "c" * 64 in baseline.source_ref
    assert len(baseline.source_ref) > 255
    assert baseline.fingerprint.startswith("source-ref-sha256:")
    assert len(baseline.fingerprint) <= ProjectDataSource.__table__.c.fingerprint.type.length
    changed = describe_node_data_source(
        {
            "id": "source",
            "type": "data.load_group",
            "parameters": {**parameters, "scientific_collection_sha256": "d" * 64},
        }
    )
    assert changed is not None and changed.fingerprint != baseline.fingerprint
    assert (
        describe_node_data_source(
            {
                "id": "source",
                "type": "data.load_group",
                "parameters": {**parameters, "scientific_collection_sha256": ""},
            }
        )
        is None
    )


def test_private_avatar_sources_reconstruct_exact_phase4_science_when_available() -> None:
    root = Path(__file__).resolve().parents[3]
    source_root = root / "private-input/avatar-omnic-oils/curated-v2"
    if not source_root.is_dir():
        pytest.skip("private Avatar sources are not present in this checkout")
    definition = validate_collection_definition(
        json.loads(
            (root / "docs/evidence/avatar-essential-oils-v1-collection-definition.json").read_text(encoding="utf-8")
        )
    )
    members = []
    for row in definition.payload["rows"]:
        source_path = source_root / Path(row["file_name"]).name
        payload = source_path.read_bytes()
        selected = select_asset(ingest(source_path), asset_id=row["asset_id"])
        members.append(
            CollectionMember(
                selected.dataset,
                row["file_name"],
                len(payload),
                hashlib.sha256(payload).hexdigest(),
                asset_id=selected.asset_id,
            )
        )
    dataset = apply_collection_definition(members, definition)
    assert dataset.shape == (33, 1868)
    assert hashlib.sha256(np.ascontiguousarray(dataset.X).tobytes()).hexdigest() == (
        "66f6f64a08cb0a875ba654f7e9e66949a698c435292cf3fb8cd4c7ae784e2b76"
    )
    assert hashlib.sha256(np.ascontiguousarray(dataset.feature_axis.values).tobytes()).hexdigest() == (
        "f0fb31d4690ff770f518574e19353ee4b2bb6d46f43abdbd90a18aef6293ed6b"
    )
    assert dataset.sample_axis is not None and dataset.sample_axis.sample_table is not None
    assert _json_digest(dataset.sample_axis.sample_table) == (
        "1b13a7b34c0d9034bc06f397d9fb1bce1b3aa00491f7a50446a8769c483a5d38"
    )
    assert dataset.target is None and dataset.sample_axis.classes is None
    phase4_path = root / "docs/evidence/avatar-essential-oils-v1-canonical-dataset.json"
    phase4 = json.loads(phase4_path.read_text(encoding="utf-8"))
    tool_path = root / "packages/spectra-sherpa/tools/avatar_omnic_canonical_dataset.py"
    spec = importlib.util.spec_from_file_location("avatar_omnic_canonical_dataset_phase53", tool_path)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    current_projection = tool.dataset_projection(dataset)
    historical_projection = dict(phase4["dataset"])
    assert current_projection.pop("wire_version") == "3.0"
    assert historical_projection.pop("wire_version") == "1.0"
    assert current_projection == historical_projection


def _json_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
