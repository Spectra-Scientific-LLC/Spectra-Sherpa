"""Canonical source acquisition and executable-export tests."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.api.v1.routes.workflows.export import _workflow_data_readme
from spectra_sherpa.app.lib.collection_definition import COLLECTION_DEFINITION_SCHEMA
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset
from spectra_sherpa.app.services import workflow_export_context as export_context_service
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.supervision_binding import admit_attached_sample_table_supervision
from spectra_sherpa.app.services.prepared_data import PreparedDataOverrides
from spectra_sherpa.app.services.python_export import build_canonical_executable_export, generate_python_code
from spectra_sherpa.app.services.workflow_export_context import (
    BundledSourceFile,
    SourceExportSpec,
    WorkflowExportContext,
)
from spectra_sherpa.io.authority import project_portable_ingestion_authority

_SOURCE_BYTES = b"target,1000,1001\n1,2,3\n2,4,6\n"
_SOURCE_SHA256 = hashlib.sha256(_SOURCE_BYTES).hexdigest()


def _workflow(*, selected_target: str = "target") -> SimpleNamespace:
    return SimpleNamespace(
        name="Materialized reference",
        description="",
        integrity_hash="source-export",
        nodes=[
            SimpleNamespace(
                node_id="source",
                node_type="data.file_load",
                parameters={
                    "experiment_id": 1,
                    "file_id": 2,
                    "stage": "raw",
                    "target_authority": _target_authority(selected_target, "continuous", _SOURCE_SHA256),
                },
            )
        ],
        edges=[],
    )


def _target_authority(column: str, target_type: str, source_digest: str) -> dict[str, object]:
    return {
        "schema_version": "spectrasherpa-target-authority/1",
        "column": column,
        "target_type": target_type,
        "units": None,
        "source_digest": source_digest,
    }


def _write_source(path: Path) -> bytes:
    content = _SOURCE_BYTES
    path.write_bytes(content)
    return content


def _external_reference(content: bytes) -> dict[str, object]:
    digest = hashlib.sha256(content).hexdigest()
    return {
        "schema_version": "spectrasherpa-portable-reference/1",
        "projection_id": "eigenvector.corn_m5",
        "artifact_id": "eigenvector.corn",
        "artifact_size_bytes": 123456,
        "artifact_sha256": "a" * 64,
        "member_path": "corn.mat",
        "member_size_bytes": len(content),
        "member_sha256": digest,
        "native_reader_contract": "spectrasherpa.matlab/1",
        "scientific_sha256": "b" * 64,
        "provider": "Eigenvector Research",
        "provider_page": "https://eigenvector.com/data_sets",
        "download_url": "https://eigenvector.com/data/Corn.zip",
        "redistribution": "user_acquired_no_redistribution",
    }


def _write_spectrum(path: Path, values: tuple[float, float, float]) -> bytes:
    content = (f"4000.0,{values[0]}\n" f"3999.0,{values[1]}\n" f"3998.0,{values[2]}\n").encode("utf-8")
    path.write_bytes(content)
    return content


def _collection_definition(first: bytes, second: bytes) -> dict[str, object]:
    domain = DomainContext(
        technique="IR",
        measurement_mode="absorbance",
        expected_units="cm-1",
        data_quantity="absorbance",
    ).model_dump(mode="json", exclude_none=False)
    rows = []
    for index, (name, content, label) in enumerate(
        (("first.csv", first, "class-a"), ("second.csv", second, "class-b")),
        start=1,
    ):
        sample_id = f"sample-{index}"
        rows.append(
            {
                "file_name": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "asset_id": "single-auto",
                "source_row_index": 0,
                "sample_id": sample_id,
                "annotations": {
                    "sample_id": sample_id,
                    "specimen_id": label,
                    "class": label,
                    "block": index,
                },
            }
        )
    return {
        "schema_version": COLLECTION_DEFINITION_SCHEMA,
        "columns": ["sample_id", "specimen_id", "class", "block"],
        "collection": {
            "dataset_id": "portable-collection-test/1",
            "title": "Portable selected collection",
            "units": "absorbance",
            "data_role": "X_spectra",
            "domain": domain,
            "sample_axis": {"title": "Samples", "units": None, "values_policy": "omit"},
        },
        "rows": rows,
    }


def _context(
    path: Path,
    *,
    bundle_relative_path: str = "source/reference.csv",
    external_reference: dict[str, object] | None = None,
) -> WorkflowExportContext:
    from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa

    ingestion_authority = (
        project_portable_ingestion_authority(load_canonical_file_as_sherpa(path)).canonical_dict()
        if path.is_file()
        else None
    )
    return WorkflowExportContext(
        source_specs={
            "source": SourceExportSpec(
                node_id="source",
                source="experiment",
                loader_mode="single_file",
                overrides=PreparedDataOverrides(
                    x_title="Wavenumber",
                    x_units="cm-1",
                    y_title="Target",
                    target_column="target",
                    selected_target="target",
                    target_type="continuous",
                    target_mode="single",
                ),
                bundle_files=(
                    BundledSourceFile(
                        absolute_path=path,
                        source_relative_path=path.name,
                        bundle_relative_path=bundle_relative_path,
                        external_reference=external_reference,
                        ingestion_authority=ingestion_authority,
                    ),
                ),
            )
        }
    )


def test_file_load_is_the_canonical_materialized_reference_source() -> None:
    metadata = node_registry.get_metadata("data.file_load")
    assert {port.name for port in metadata.output_ports} >= {"default", "target"}
    assert metadata.policy is not None
    assert metadata.policy.data_egress_risk == "none"


def test_legacy_project_collection_requires_resave_through_canonical_source() -> None:
    workflow = SimpleNamespace(
        name="Project collection",
        description="",
        integrity_hash="project-collection",
        nodes=[
            SimpleNamespace(
                node_id="source",
                node_type="data.load_group",
                parameters={
                    "source_mode": "experiment_collection",
                    "experiment_id": 7,
                    "stage": "raw",
                    "asset_id": "spectrum",
                    "source_manifest_sha256": "a" * 64,
                },
            )
        ],
        edges=[],
    )

    with pytest.raises(ValueError, match="reopened and saved through data.collection_load"):
        build_canonical_executable_export(workflow, export_context=WorkflowExportContext())


def test_eigenvector_catalog_preserves_scientific_identity() -> None:
    from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG

    corn = DATASET_CATALOG["corn_m5"]
    diesel = DATASET_CATALOG["diesel_nir"]
    assert corn["prop_names"] == ["Moisture", "Oil", "Protein", "Starch"]
    assert corn["x_title"] == "Wavelength"
    assert corn["x_units"] == "nm"
    assert corn["artifact_projection_id"] == "public-corn-m5-moisture-v1"
    assert diesel["x_units"] == "nm"


def test_synthetic_reference_loader_returns_canonical_dataset() -> None:
    from spectra_sherpa.app.lib.synthetic_references import load_synthetic_reference_as_sherpa

    dataset = load_synthetic_reference_as_sherpa("Library_atmospheric-9")
    assert isinstance(dataset, SherpaDataset)
    assert dataset.shape[0] == 9
    assert "Component Library" in dataset.title


def test_export_binds_exact_file_digest_target_and_prepared_metadata(tmp_path: Path) -> None:
    source = tmp_path / "reference.csv"
    content = _write_source(source)
    projected = build_canonical_executable_export(_workflow(), export_context=_context(source))

    binding = projected.bundled_sources[0]
    assert binding.bundle_relative_path == "source/reference.csv"
    assert binding.byte_length == len(content)
    assert binding.sha256 == hashlib.sha256(content).hexdigest()
    assert binding.selected_target == "target"
    assert binding.target_type == "continuous"
    assert binding.prepared_overrides["x_title"] == "Wavenumber"
    assert binding.ingestion_authority["schema_version"] == "spectrasherpa.portable-ingestion-authority/1"
    assert binding.ingestion_authority["format_id"] == "csv"
    assert binding.ingestion_authority["source_members"] == [
        {"size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    ]
    assert "name" not in binding.ingestion_authority["source_members"][0]
    assert projected.workflow.payload["nodes"] == [
        {
            "node_id": "source",
            "node_type": "deploy.input",
            "parameters": {
                "stream_name": "export.source.source",
                "schema_version": "spectrasherpa.deploy-input/1",
            },
        }
    ]


def test_registered_reference_export_binds_portable_identity_without_reclassifying_ordinary_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "server-projection.csv"
    content = _write_source(source)
    reference = _external_reference(content)
    registered = _context(
        source,
        bundle_relative_path="source/corn.mat",
        external_reference=reference,
    )
    ordinary = _context(source)

    projected = build_canonical_executable_export(_workflow(), export_context=registered)
    assert projected.bundled_sources[0].external_reference == reference
    assert registered.iter_embedded_bundle_files() == []
    assert registered.iter_external_reference_files() == registered.iter_bundle_files()
    assert ordinary.iter_embedded_bundle_files() == ordinary.iter_bundle_files()
    assert ordinary.iter_external_reference_files() == []

    readme = _workflow_data_readme(
        registered,
        [
            {"name": "MATLAB", "extensions": [".mat"], "available": True},
            {"name": "Pending", "unsupportedReason": "not qualified", "available": False},
        ],
    )
    assert "not included in this export" in readme
    assert "SPECTRA_REFERENCE_DIR" in readme
    assert "eigenvector.corn_m5" in readme
    assert "https://eigenvector.com/data/Corn.zip" in readme
    assert reference["member_sha256"] in readme
    assert "does not retrieve, proxy, cache, mirror, or redistribute" in readme


def test_export_context_uses_sidecar_as_the_only_reference_classifier(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "customer-renamed.mat"
    content = _write_source(source)
    reference = _external_reference(content)

    monkeypatch.setattr(export_context_service, "read_registered_reference_sidecar", lambda _path: None)
    ordinary = export_context_service._bundle_specs_for_files("source", [str(source)])
    assert ordinary[0].external_reference is None
    assert ordinary[0].bundle_relative_path == "source/customer-renamed.mat"

    monkeypatch.setattr(
        export_context_service,
        "read_registered_reference_sidecar",
        lambda _path: reference,
    )
    registered = export_context_service._bundle_specs_for_files("source", [str(source)])
    assert registered[0].external_reference == reference
    assert registered[0].bundle_relative_path == "source/corn.mat"


def test_registered_reference_export_refuses_member_drift(tmp_path: Path) -> None:
    source = tmp_path / "server-projection.csv"
    content = _write_source(source)
    reference = _external_reference(content)
    source.write_bytes(content + b"drift")

    with pytest.raises(ValueError, match="registered reference member is not exact"):
        build_canonical_executable_export(
            _workflow(),
            export_context=_context(source, external_reference=reference),
        )


def test_generated_source_export_uses_only_sdk_reader_and_runtime(tmp_path: Path) -> None:
    source = tmp_path / "reference.csv"
    _write_source(source)
    code = generate_python_code(_workflow(), export_context=_context(source))

    ast.parse(code)
    assert "ss.data.read(" in code
    assert "prepared_overrides=binding['prepared_overrides']" in code
    assert "expected_ingestion_authority=binding['ingestion_authority']" in code
    assert "ss.runtime.execute_workflow(" in code
    assert "load_canonical_file_as_sherpa" not in code
    assert "ExperimentDatasetReader" not in code
    assert "spectrochempy" not in code


def test_generated_source_export_executes_and_preserves_target_axis_and_units(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "reference.csv"
    _write_source(source)
    code = generate_python_code(_workflow(), export_context=_context(source))
    bundle = tmp_path / "source" / "reference.csv"
    bundle.parent.mkdir()
    bundle.write_bytes(source.read_bytes())
    monkeypatch.setenv("SHERPA_DATA_DIR", str(tmp_path))
    namespace = {"__file__": str(tmp_path / "workflow.py"), "__name__": "source_test"}
    exec(compile(code, "<source-export>", "exec"), namespace)

    result = namespace["run_workflow"]()["source"]
    dataset = result["default"]
    np.testing.assert_array_equal(result["target"], np.array([1, 2]))
    assert dataset.feature_axis.title == "Wavenumber"
    assert dataset.feature_axis.units == "cm-1"
    assert dataset.target_context.selected_target == "target"


def test_registered_reference_export_rebinds_renamed_exact_member_from_bounded_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "server-projection.csv"
    content = _write_source(source)
    reference = _external_reference(content)
    code = generate_python_code(
        _workflow(),
        export_context=_context(
            source,
            bundle_relative_path="source/corn.mat",
            external_reference=reference,
        ),
    )
    reference_dir = tmp_path / "scientist-files"
    reference_dir.mkdir()
    (reference_dir / "renamed-by-scientist.csv").write_bytes(content)
    monkeypatch.setenv("SPECTRA_REFERENCE_DIR", str(reference_dir))
    from spectra_sherpa.sdk import data as sdk_data

    monkeypatch.setattr(
        sdk_data,
        "read_registered_reference",
        lambda path, **_kwargs: sdk_data.read(path, y="target"),
    )
    namespace = {"__file__": str(tmp_path / "workflow.py"), "__name__": "source_test"}
    exec(compile(code, "<reference-export>", "exec"), namespace)

    result = namespace["run_workflow"]()["source"]
    np.testing.assert_array_equal(result["target"], np.array([1, 2]))
    assert namespace["BUNDLED_SOURCE_BINDINGS"][0]["external_reference"]["projection_id"] == ("eigenvector.corn_m5")

    exact_file = reference_dir / "renamed-by-scientist.csv"
    monkeypatch.setenv("SPECTRA_REFERENCE_DIR", str(exact_file))
    exact_namespace = {"__file__": str(tmp_path / "workflow.py"), "__name__": "source_test"}
    exec(compile(code, "<reference-export>", "exec"), exact_namespace)
    np.testing.assert_array_equal(exact_namespace["run_workflow"]()["source"]["target"], np.array([1, 2]))


def test_collection_export_rebuilds_selected_members_target_and_groups_from_relocated_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first_bytes = _write_spectrum(first, (0.1, 0.2, 0.3))
    second_bytes = _write_spectrum(second, (0.4, 0.5, 0.6))
    definition = _collection_definition(first_bytes, second_bytes)
    overrides = PreparedDataOverrides(
        csv_layout="headerless_two_column_spectrum",
        x_title="Wavenumber",
        x_units="cm-1",
    )
    workflow = SimpleNamespace(
        name="Portable collection",
        description="",
        integrity_hash="portable-collection",
        nodes=[
            SimpleNamespace(
                node_id="source",
                node_type="data.collection_load",
                parameters={
                    "experiment_id": 7,
                    "stage": "raw",
                    "selected_file_ids": [10, 11],
                    "asset_id": "single-auto",
                    "target_authority": _target_authority("class", "categorical", "c" * 64),
                    "group_column": "block",
                    "source_manifest_sha256": "",
                    "collection_definition_sha256": "",
                    "scientific_collection_sha256": "",
                },
            )
        ],
        edges=[],
    )
    context = WorkflowExportContext(
        source_specs={
            "source": SourceExportSpec(
                node_id="source",
                source="experiment_collection",
                loader_mode="collection",
                bundle_files=(
                    BundledSourceFile(
                        absolute_path=first,
                        source_relative_path="first.csv",
                        bundle_relative_path="source/first.csv",
                        prepared_overrides=overrides,
                        member_file_name="first.csv",
                    ),
                    BundledSourceFile(
                        absolute_path=second,
                        source_relative_path="second.csv",
                        bundle_relative_path="source/second.csv",
                        prepared_overrides=overrides,
                        member_file_name="second.csv",
                    ),
                ),
                collection_title="Portable selected collection",
                collection_definition=definition,
            )
        }
    )

    code = generate_python_code(workflow, export_context=context)
    for path in (first, second):
        bundled = tmp_path / "relocated" / "source" / path.name
        bundled.parent.mkdir(parents=True, exist_ok=True)
        bundled.write_bytes(path.read_bytes())
    monkeypatch.setenv("SHERPA_DATA_DIR", str(tmp_path / "relocated"))
    namespace = {"__file__": str(tmp_path / "workflow.py"), "__name__": "source_test"}
    exec(compile(code, "<collection-export>", "exec"), namespace)

    result = namespace["run_workflow"]()["source"]
    dataset = result["default"]
    np.testing.assert_allclose(dataset.X, [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    np.testing.assert_array_equal(result["target"], np.asarray(["class-a", "class-b"]))
    supervision = admit_attached_sample_table_supervision(dataset)
    assert supervision is not None
    np.testing.assert_array_equal(supervision.groups, np.asarray([1, 2]))
    assert dataset.sample_axis.labels == ["sample-1", "sample-2"]
    assert dataset.target_context.selected_target == "class"


def test_registered_reference_export_refuses_missing_and_ambiguous_rebinding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "server-projection.csv"
    content = _write_source(source)
    code = generate_python_code(
        _workflow(),
        export_context=_context(source, external_reference=_external_reference(content)),
    )
    monkeypatch.delenv("SPECTRA_REFERENCE_DIR", raising=False)
    missing_namespace = {"__file__": str(tmp_path / "workflow.py"), "__name__": "source_test"}
    exec(compile(code, "<reference-export>", "exec"), missing_namespace)
    with pytest.raises(FileNotFoundError, match="Set SPECTRA_REFERENCE_DIR"):
        missing_namespace["run_workflow"]()

    reference_dir = tmp_path / "duplicates"
    reference_dir.mkdir()
    (reference_dir / "one.csv").write_bytes(content)
    (reference_dir / "two.csv").write_bytes(content)
    monkeypatch.setenv("SPECTRA_REFERENCE_DIR", str(reference_dir))
    duplicate_namespace = {"__file__": str(tmp_path / "workflow.py"), "__name__": "source_test"}
    exec(compile(code, "<reference-export>", "exec"), duplicate_namespace)
    with pytest.raises(ValueError, match="more than one exact registered-reference match"):
        duplicate_namespace["run_workflow"]()

    bounded_dir = tmp_path / "too-many-entries"
    bounded_dir.mkdir()
    for index in range(1001):
        (bounded_dir / f"unrelated-{index:04d}.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("SPECTRA_REFERENCE_DIR", str(bounded_dir))
    bounded_namespace = {"__file__": str(tmp_path / "workflow.py"), "__name__": "source_test"}
    exec(compile(code, "<reference-export>", "exec"), bounded_namespace)
    with pytest.raises(ValueError, match="1000-entry search limit"):
        bounded_namespace["run_workflow"]()


def test_export_rejects_missing_unowned_or_multi_file_source(tmp_path: Path) -> None:
    workflow = _workflow()
    with pytest.raises(ValueError, match="complete actor-authorized source set"):
        generate_python_code(workflow)

    source = tmp_path / "missing.csv"
    with pytest.raises(ValueError, match="bundled file is unavailable"):
        generate_python_code(workflow, export_context=_context(source))

    source.write_text("x\n1\n", encoding="utf-8")
    spec = _context(source).source_specs["source"]
    multi = WorkflowExportContext(
        source_specs={
            "source": SourceExportSpec(
                node_id="source",
                source="experiment",
                loader_mode="multi_file",
                overrides=spec.overrides,
                bundle_files=spec.bundle_files,
            )
        }
    )
    with pytest.raises(ValueError, match="complete actor-authorized source set"):
        generate_python_code(workflow, export_context=multi)


def test_sdk_reader_applies_the_shared_prepared_data_authority(tmp_path: Path) -> None:
    import spectra_sherpa.sdk as ss

    source = tmp_path / "reference.csv"
    _write_source(source)
    dataset = ss.data.read(
        source,
        y="target",
        target_type="continuous",
        prepared_overrides={
            "x_title": "Raman shift",
            "x_units": "cm-1",
            "selected_target": "target",
            "target_type": "continuous",
            "target_mode": "single",
        },
    )

    assert dataset.feature_axis.title == "Raman shift"
    assert dataset.feature_axis.units == "cm-1"
    np.testing.assert_array_equal(dataset.target, np.array([1, 2]))


def test_sdk_reader_refuses_native_parser_authority_drift(tmp_path: Path) -> None:
    import spectra_sherpa.sdk as ss

    source = tmp_path / "reference.csv"
    _write_source(source)
    observed = ss.data.read(source)
    expected = project_portable_ingestion_authority(observed).canonical_dict()
    renamed = tmp_path / "scientist-renamed.csv"
    renamed.write_bytes(source.read_bytes())
    rebound = ss.data.read(renamed, expected_ingestion_authority=expected)
    np.testing.assert_array_equal(rebound.X, observed.X)

    expected["parser_version"] = "future-parser"

    with pytest.raises(ValueError, match="native ingestion authority changed"):
        ss.data.read(source, expected_ingestion_authority=expected)


def test_portable_ingestion_authority_refuses_malformed_source_members(tmp_path: Path) -> None:
    import spectra_sherpa.sdk as ss

    source = tmp_path / "reference.csv"
    _write_source(source)
    observed = ss.data.read(source)
    full_authority = observed.get_extra("ingestion.authority")
    assert isinstance(full_authority, dict)
    full_authority["source_members"] = [None]
    observed.set_extra("ingestion.authority", full_authority)

    with pytest.raises(ValueError, match="has no source members"):
        project_portable_ingestion_authority(observed)


def test_exported_sdk_reader_replays_the_exact_csv_profile(tmp_path: Path) -> None:
    import spectra_sherpa.sdk as ss

    source = tmp_path / "supplier-export.csv"
    source.write_text("4000.0,0.10\n3999.0,0.20\n3998.0,0.30\n", encoding="utf-8")
    dataset = ss.data.read(
        source,
        prepared_overrides={
            "csv_layout": "headerless_two_column_spectrum",
            "x_title": "Wavenumber",
            "x_units": "cm-1",
        },
    )

    np.testing.assert_allclose(dataset.X, [[0.10, 0.20, 0.30]])
    np.testing.assert_allclose(dataset.feature_axis.values, [4000.0, 3999.0, 3998.0])
    assert dataset.feature_axis.title == "Wavenumber"
    assert dataset.feature_axis.units == "cm-1"
    assert dataset.meta["csv.profile"] == "headerless_two_column_spectrum"
