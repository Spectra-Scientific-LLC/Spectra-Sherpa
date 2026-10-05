"""Release contract for canonical dataset export and host materialization."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pytest
import yaml

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - register built-ins
from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.export_artifact import (
    EXPORT_ARTIFACT_SCHEMA,
    build_export_artifact,
    materialize_export_artifact,
    verify_export_artifact,
)
from spectra_sherpa.app.lib.io import inspect_csv_import_plan, load_csv_as_sherpa
from spectra_sherpa.app.lib.reference_materialization import _metal_etch_oes_feature_labels
from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
    TargetContext,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.output.export_node import ExportNode
from spectra_sherpa.app.services.export_utils import export_artifacts
from spectra_sherpa.execution_contract_vocabulary import (
    DatasetRankPolicy,
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
)
from tests.performance_contract import PerformanceCeiling


def _spectra(*, rows: int = 2, columns: int = 3) -> SherpaDataset:
    matrix = np.arange(rows * columns, dtype=np.float64).reshape(rows, columns) / 10.0
    return SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(
            values=np.linspace(4000.0, 1000.0, columns),
            units="cm^-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(labels=[f"sample-{index + 1}" for index in range(rows)]),
        units="absorbance",
        title="Reference spectra",
        data_role="X_spectra",
    )


def _generated_result(node: ExportNode, dataset: SherpaDataset) -> dict[str, object]:
    namespace: dict[str, object] = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)
    return namespace["results"][node.node_id]  # type: ignore[index,return-value]


def test_export_node_publishes_one_closed_local_contract() -> None:
    metadata = node_registry.get_metadata("output.export")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "output.export"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["implementation_id"] == "spectrasherpa.output.export"
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["sample_effect"] == "preserves_samples"
    assert contract.payload["feature_effect"] == "preserves_features"
    assert contract.payload["axis_effect"] == "preserves_axis"
    assert contract.payload["unit_effect"] == "preserves_units"
    assert contract.payload["input_rank_policy"] == DatasetRankPolicy.PRESERVES_ND.value
    assert metadata.policy is not None
    assert metadata.policy.data_egress_risk == "full_data"
    assert metadata.policy.requires_human_review is True
    # Export remains compatible with canonical score/result matrices while the
    # serializer enforces format-specific dataset rank internally.
    assert metadata.input_ports[0].type_ref == "spectrasherpa://types/Any/1.0"
    assert metadata.output_ports[0].type_ref == "spectrasherpa://types/ExportArtifact/1.0"


@pytest.mark.parametrize(
    ("fmt", "filename"),
    [("csv", "spectra.csv"), ("json", "spectra.json"), ("jdx", "spectrum.jdx")],
)
def test_live_and_generated_paths_prepare_identical_verified_bytes(fmt: str, filename: str) -> None:
    dataset = _spectra(rows=1 if fmt == "jdx" else 2)
    node = ExportNode("export", {"filename": filename, "format": fmt})

    live = asyncio.run(node.execute(dataset))
    generated = _generated_result(node, dataset)

    assert live == generated
    artifact = verify_export_artifact(live["artifact"])
    assert artifact["schema_version"] == EXPORT_ARTIFACT_SCHEMA
    assert artifact["filename"] == filename
    assert artifact["format"] == fmt
    assert artifact["byte_length"] == len(str(artifact["content"]).encode("utf-8"))
    assert artifact["content_sha256"] == hashlib.sha256(str(artifact["content"]).encode("utf-8")).hexdigest()
    assert artifact["shape"] == list(dataset.shape)


def test_csv_and_json_preserve_scientific_values_axes_and_units() -> None:
    dataset = _spectra()
    csv_artifact = build_export_artifact(dataset, filename="spectra.csv", format="csv")
    json_artifact = build_export_artifact(dataset, filename="spectra.json", format="json")

    csv_lines = str(csv_artifact["content"]).splitlines()
    assert csv_lines[0].startswith("#spectrasherpa-portable-csv/2,")
    assert csv_lines[1:] == [
        "sample,4000,2500,1000",
        "sample-1,0,0.10000000000000001,0.20000000000000001",
        "sample-2,0.29999999999999999,0.40000000000000002,0.5",
    ]
    envelope = json.loads(str(json_artifact["content"]))
    payload = envelope["dataset"]
    assert envelope["schema_version"] == "spectrasherpa-portable-json/1"
    assert envelope["shape"] == [2, 3]
    np.testing.assert_array_equal(payload["data"], dataset.X)
    assert payload["version"] == "3.0"
    assert payload["feature_axis"]["axis_class"] == "SpectralAxis"
    assert payload["feature_axis"]["title"] == "Wavenumber"
    assert payload["feature_axis"]["units"] == "cm^-1"
    assert payload["feature_axis"]["data"] == [4000.0, 2500.0, 1000.0]
    assert payload["sample_axis"]["labels"] == ["sample-1", "sample-2"]
    assert payload["units"] == "absorbance"
    assert payload["data_role"] == "X_spectra"
    assert csv_artifact["source_digest"] == dataset.scientific_digest
    assert json_artifact["source_digest"] == dataset.scientific_digest


def test_res15_repeated_oes_wavelength_blocks_export_with_unique_feature_identity() -> None:
    wavelengths = np.tile(np.array([250.0, 500.0, 791.5]), 3)
    labels = _metal_etch_oes_feature_labels(wavelengths)
    dataset = SherpaDataset(
        X=np.arange(18, dtype=np.float64).reshape(2, 9),
        feature_axis=SpectralAxis(
            values=wavelengths,
            labels=labels,
            title="Wavelength",
            units="nm",
        ),
        sample_axis=SampleAxis(labels=["wafer-1", "wafer-2"]),
        data_role="X_spectra",
    )

    artifact = build_export_artifact(dataset, filename="metal-etch-oes.csv", format="csv")
    rows = list(csv.reader(io.StringIO(str(artifact["content"]))))
    headers = rows[1]
    data_rows = rows[2:]

    assert headers[1:] == labels
    assert len(headers) == len(set(headers))
    assert headers[1] == "block_1:wavelength_250_nm"
    assert headers[4] == "block_2:wavelength_250_nm"
    assert headers[7] == "block_3:wavelength_250_nm"
    assert [row[0] for row in data_rows] == ["wafer-1", "wafer-2"]
    np.testing.assert_array_equal(np.asarray([row[1:] for row in data_rows], dtype=float), dataset.X)


def test_csv_preserves_each_named_multi_target_response_column() -> None:
    dataset = _spectra()
    dataset.target = np.array([[0.1, 2.0], [0.3, 4.0]])
    dataset.target_context = TargetContext(
        target_type="continuous",
        target_names=["Carbon dioxide", "Water"],
    )

    artifact = build_export_artifact(dataset, filename="mixture.csv", format="csv")

    assert str(artifact["content"]).splitlines()[1:] == [
        "sample,4000,2500,1000,Carbon dioxide,Water",
        "sample-1,0,0.10000000000000001,0.20000000000000001,0.10000000000000001,2",
        "sample-2,0.29999999999999999,0.40000000000000002,0.5,0.29999999999999999,4",
    ]


def test_portable_csv_round_trip_preserves_five_dissimilar_identity_cases(tmp_path: Path) -> None:
    cases = [
        _spectra(),
        SherpaDataset(
            X=np.array([[1.25, 2.5], [3.75, 5.0]]),
            feature_axis=FeatureAxis(
                values=[10.5, 20.25],
                labels=["density", "viscosity"],
                units="scaled",
                title="Engineered variables",
            ),
            sample_axis=SampleAxis(values=[101.5, 205.25], title="Batch number"),
            domain=DomainContext(technique="generic", sample_type="fuel"),
            title="Non-spectral feature table",
            data_role="X_features",
        ),
        SherpaDataset(
            X=np.arange(12, dtype=np.float64).reshape(2, 6),
            feature_axis=SpectralAxis(
                values=[250.0, 500.0, 250.0, 500.0, 250.0, 500.0],
                units="nm",
                title="Wavelength",
            ),
            sample_axis=SampleAxis(labels=["wafer-1", "wafer-2"]),
            data_role="X_spectra",
        ),
        SherpaDataset(
            X=np.array([[0.125, 0.25], [0.5, 1.0]]),
            feature_axis=FeatureAxis(labels=["f1", "f2"], title="Assay"),
            sample_axis=SampleAxis(
                labels=["001", "002"],
                sample_table={"batch": ["A", "B"], "comment": [None, "qualified"]},
            ),
            target=np.array(["control", "treated"]),
            target_context=TargetContext(
                target_type="categorical",
                target_name="class",
                target_names=["class"],
                class_names=["control", "treated"],
            ),
            data_role="X_features",
        ),
        SherpaDataset(
            X=np.array([[np.nextafter(0.1, 1.0), 1.0 / 3.0], [np.pi, np.e]]),
            feature_axis=FeatureAxis(labels=["ratio", "response"]),
            sample_axis=SampleAxis(labels=["cal-1", "cal-2"]),
            target=np.array([[0.1, 2.0], [0.3, 4.0]]),
            target_context=TargetContext(
                target_type="continuous",
                target_names=["bp50", "viscosity"],
                target_units="mixed",
            ),
            data_role="X_features",
        ),
    ]

    for index, source in enumerate(cases, start=1):
        artifact = build_export_artifact(source, filename=f"case-{index}.csv", format="csv")
        path = tmp_path / str(artifact["filename"])
        path.write_bytes(str(artifact["content"]).encode("utf-8"))

        plan = inspect_csv_import_plan(path)
        restored = load_csv_as_sherpa(path)

        assert plan["layout"] == "spectrasherpa_portable_v2"
        np.testing.assert_array_equal(restored.X, source.X)
        assert type(restored.feature_axis) is type(source.feature_axis)
        assert restored.feature_axis.model_dump() == source.feature_axis.model_dump()
        assert restored.sample_axis.model_dump() == source.sample_axis.model_dump()
        if source.target is None:
            assert restored.target is None
        else:
            np.testing.assert_array_equal(restored.target, source.target)
        assert restored.target_context.model_dump() == source.target_context.model_dump()
        assert restored.domain.model_dump() == source.domain.model_dump()
        assert restored.title == source.title
        assert restored.units == source.units
        assert restored.data_role == source.data_role


def test_portable_csv_rejects_body_identity_tampering(tmp_path: Path) -> None:
    artifact = build_export_artifact(_spectra(), filename="spectra.csv", format="csv")
    lines = str(artifact["content"]).splitlines()
    lines[1] = lines[1].replace("sample,", "renamed,")
    path = tmp_path / "tampered.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="header contradicts"):
        load_csv_as_sherpa(path)


def test_portable_csv_large_axis_envelope_is_not_limited_by_csv_field_size(tmp_path: Path) -> None:
    feature_count = 6000
    source = SherpaDataset(
        X=np.arange(feature_count, dtype=np.float64).reshape(1, -1),
        feature_axis=FeatureAxis(labels=[f"qualified-feature-{index:04d}" for index in range(feature_count)]),
        sample_axis=SampleAxis(labels=["sample-1"]),
        data_role="X_features",
    )
    artifact = build_export_artifact(source, filename="wide.csv", format="csv")
    path = tmp_path / "wide.csv"
    path.write_bytes(str(artifact["content"]).encode("utf-8"))

    assert len(str(artifact["content"]).splitlines()[0]) > 131_072
    from spectra_sherpa.io import ingest

    restored = ingest(path).assets[0].dataset

    np.testing.assert_array_equal(restored.X, source.X)
    assert restored.feature_axis.labels == source.feature_axis.labels


def test_portable_csv_registry_charges_decoded_envelope_before_base64_expansion(tmp_path: Path) -> None:
    feature_count = 120_000
    source = SherpaDataset(
        X=np.arange(feature_count, dtype=np.float64).reshape(1, -1),
        feature_axis=FeatureAxis(labels=[f"qualified-feature-{index:06d}" for index in range(feature_count)]),
        sample_axis=SampleAxis(labels=["sample-1"]),
        data_role="X_features",
    )
    artifact = build_export_artifact(source, filename="wide-boundary.csv", format="csv")
    path = tmp_path / "wide-boundary.csv"
    path.write_bytes(str(artifact["content"]).encode("utf-8"))

    from spectra_sherpa.io import ingest

    assert len(str(artifact["content"]).splitlines()[0].encode("ascii")) > 8 * 1024 * 1024
    restored = ingest(path).assets[0].dataset

    np.testing.assert_array_equal(restored.X, source.X)
    assert restored.feature_axis.labels == source.feature_axis.labels


def test_portable_csv_without_sample_axis_round_trips_without_inventing_one(tmp_path: Path) -> None:
    source = SherpaDataset(
        X=np.array([[1.0, 2.0], [3.0, 4.0]]),
        feature_axis=FeatureAxis(labels=["first", "second"]),
        data_role="X_features",
    )
    artifact = build_export_artifact(source, filename="axisless.csv", format="csv")
    path = tmp_path / "axisless.csv"
    path.write_bytes(str(artifact["content"]).encode("utf-8"))

    from spectra_sherpa.io import ingest

    restored = ingest(path).assets[0].dataset

    np.testing.assert_array_equal(restored.X, source.X)
    assert restored.sample_axis is None
    assert restored.feature_axis.model_dump() == source.feature_axis.model_dump()


def test_portable_json_round_trip_uses_public_ingestion_and_preserves_identity(tmp_path: Path) -> None:
    source = _spectra()
    source.feature_axis = SpectralAxis(
        values=source.feature_axis.values,
        title=source.feature_axis.title,
        units="cm-1",
        display_units="cm^-1",
        quantity="wavenumber",
    )
    source.domain = source.domain.model_copy(update={"expected_units": "cm-1"})
    source.target = np.array(["control", "treated"])
    source.target_context = TargetContext(
        target_type="categorical",
        target_name="class",
        target_names=["class"],
        class_names=["control", "treated"],
    )
    artifact = build_export_artifact(source, filename="spectra.json", format="json")
    path = tmp_path / "spectra.json"
    path.write_bytes(str(artifact["content"]).encode("utf-8"))

    from spectra_sherpa.io import ingest

    result = ingest(path)
    restored = result.assets[0].dataset

    assert result.format_id == "sherpa-json"
    np.testing.assert_array_equal(restored.X, source.X)
    np.testing.assert_array_equal(restored.target, source.target)
    assert restored.feature_axis.model_dump() == source.feature_axis.model_dump()
    assert restored.sample_axis.model_dump() == source.sample_axis.model_dump()
    assert restored.target_context.model_dump() == source.target_context.model_dump()
    assert restored.domain.model_dump() == source.domain.model_dump()
    assert restored.title == source.title
    assert restored.units == source.units
    assert restored.data_role == source.data_role


def test_portable_json_rejects_resource_excess_before_object_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = build_export_artifact(_spectra(), filename="spectra.json", format="json")
    path = tmp_path / "spectra.json"
    path.write_bytes(str(artifact["content"]).encode("utf-8"))

    from spectra_sherpa.app.lib import portable_json
    from spectra_sherpa.io import ParserLimitError, ParserLimits, ingest

    monkeypatch.setattr(portable_json.json, "loads", lambda *_args, **_kwargs: pytest.fail("JSON allocated early"))
    with pytest.raises(ParserLimitError, match="decoded elements"):
        ingest(path, limits=ParserLimits(max_decoded_elements=1))


@pytest.mark.parametrize("oversized_field", ["target", "extra"])
def test_portable_json_counts_non_x_tree_before_object_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    oversized_field: str,
) -> None:
    source = _spectra(rows=1, columns=1)
    if oversized_field == "target":
        source.target = np.arange(1_000, dtype=np.float64).reshape(1, 1_000)
        source.target_context = TargetContext(target_type="continuous", target_names=[f"y{i}" for i in range(1_000)])
    else:
        source.extra["oversized"] = list(range(1_000))
    artifact = build_export_artifact(source, filename=f"{oversized_field}.json", format="json")
    path = tmp_path / f"{oversized_field}.json"
    path.write_bytes(str(artifact["content"]).encode("utf-8"))

    from spectra_sherpa.app.lib import portable_json
    from spectra_sherpa.io import ParserLimitError, ParserLimits, ingest

    monkeypatch.setattr(portable_json.json, "loads", lambda *_args, **_kwargs: pytest.fail("JSON allocated early"))
    with pytest.raises(ParserLimitError, match="decoded elements"):
        ingest(path, limits=ParserLimits(max_decoded_elements=500))


@pytest.mark.parametrize("oversized_field", ["target", "extra"])
def test_portable_json_producer_caps_the_complete_tree(
    monkeypatch: pytest.MonkeyPatch,
    oversized_field: str,
) -> None:
    from spectra_sherpa.app.lib import portable_json

    source = _spectra(rows=1, columns=1)
    if oversized_field == "target":
        source.target = np.arange(100, dtype=np.float64).reshape(1, 100)
    else:
        source.extra["oversized"] = list(range(100))
    monkeypatch.setattr(portable_json, "MAX_PORTABLE_JSON_ELEMENTS", 50)

    with pytest.raises(ValueError, match="decoded-element limit"):
        build_export_artifact(source, filename=f"{oversized_field}.json", format="json")


def test_portable_json_rejects_false_decoded_node_declaration_before_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = build_export_artifact(_spectra(), filename="spectra.json", format="json")
    content = str(artifact["content"])
    content = re.sub(r'"decoded_nodes":[0-9]+', '"decoded_nodes":1', content, count=1)
    path = tmp_path / "false-node-count.json"
    path.write_text(content, encoding="utf-8")

    from spectra_sherpa.app.lib import portable_json
    from spectra_sherpa.io import UnreadableSpectrumError, ingest

    monkeypatch.setattr(portable_json.json, "loads", lambda *_args, **_kwargs: pytest.fail("JSON allocated early"))
    with pytest.raises(UnreadableSpectrumError, match="decoded-node declaration"):
        ingest(path)


@pytest.mark.parametrize("tampering", ["duplicate", "nonfinite", "reordered"])
def test_portable_json_rejects_noncanonical_fields_and_constants(tmp_path: Path, tampering: str) -> None:
    artifact = build_export_artifact(_spectra(), filename="spectra.json", format="json")
    content = str(artifact["content"])
    if tampering == "duplicate":
        content = content.replace(
            '"type":"SherpaDataset"',
            '"type":"SherpaDataset","type":"SherpaDataset"',
            1,
        )
    elif tampering == "nonfinite":
        content = content.replace('"data":[[0.0,', '"data":[[NaN,', 1)
    else:
        content = content.replace(
            '"title":"Reference spectra","type":"SherpaDataset",',
            '"type":"SherpaDataset","title":"Reference spectra",',
            1,
        )
    path = tmp_path / f"{tampering}.json"
    path.write_text(content, encoding="utf-8")

    from spectra_sherpa.io import UnreadableSpectrumError, ingest

    with pytest.raises(UnreadableSpectrumError):
        ingest(path)


def test_jcamp_is_one_real_spectrum_with_measured_axis_and_honest_units() -> None:
    artifact = build_export_artifact(_spectra(rows=1), filename="spectrum.jdx", format="jdx")
    lines = str(artifact["content"]).splitlines()

    assert "##DATA TYPE=SPECTRUM" in lines
    assert "##XUNITS=cm^-1" in lines
    assert "##YUNITS=absorbance" in lines
    assert "4000, 0" in lines
    assert lines[-1] == "##END="

    with pytest.raises(ValueError, match="exactly one spectrum"):
        build_export_artifact(_spectra(rows=2), filename="spectra.jdx", format="jdx")
    without_axis = SherpaDataset(X=np.ones((1, 3)), units="absorbance")
    with pytest.raises(ValueError, match="measured numeric feature axis"):
        build_export_artifact(without_axis, filename="spectrum.jdx", format="jdx")
    without_axis_units = SherpaDataset(X=np.ones((1, 3)), feature_axis=SpectralAxis(values=[1, 2, 3]))
    with pytest.raises(ValueError, match="feature-axis units"):
        build_export_artifact(without_axis_units, filename="spectrum.jdx", format="jdx")


def test_export_rejects_spreadsheet_formula_labels_and_jcamp_header_injection() -> None:
    spreadsheet_formula = _spectra()
    spreadsheet_formula.sample_axis = SampleAxis(labels=['=HYPERLINK("https://invalid")', "sample-2"])
    with pytest.raises(ValueError, match="formula-like axis labels"):
        build_export_artifact(spreadsheet_formula, filename="spectra.csv", format="csv")

    injected_header = _spectra(rows=1)
    injected_header.title = "Measured spectrum\n##END="
    with pytest.raises(ValueError, match="invalid title header text"):
        build_export_artifact(injected_header, filename="spectrum.jdx", format="jdx")


@pytest.mark.parametrize(
    "parameters",
    [
        {"filename": "../escape.csv", "format": "csv"},
        {"filename": "nested/output.csv", "format": "csv"},
        {"filename": "output.csv", "format": "json"},
        {"filename": " output.csv", "format": "csv"},
        {"filename": "output.csv", "format": "unknown"},
    ],
)
def test_export_admission_rejects_unsafe_or_mismatched_parameters(parameters: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        node_registry.create_node("output.export", "export", parameters)


def test_export_rejects_nonfinite_data_and_tampered_or_open_artifacts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        build_export_artifact(
            SherpaDataset(X=np.array([[1.0, np.nan]])),
            filename="bad.csv",
            format="csv",
        )

    artifact = build_export_artifact(_spectra(), filename="spectra.csv", format="csv")
    for field, replacement in (
        ("content", "changed"),
        ("byte_length", 1),
        ("content_sha256", "0" * 64),
        ("source_digest", "not-a-digest"),
        ("shape", [True, 3]),
    ):
        forged = {**artifact, field: replacement}
        with pytest.raises(ValueError):
            verify_export_artifact(forged)
    with pytest.raises(ValueError, match="closed schema"):
        verify_export_artifact({**artifact, "unexpected": True})

    destination = materialize_export_artifact(artifact, tmp_path)
    assert destination.read_text() == artifact["content"]
    with pytest.raises(FileExistsError):
        materialize_export_artifact(artifact, tmp_path)


def test_generated_script_host_materializes_exact_prepared_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifact = build_export_artifact(_spectra(), filename="scientist.csv", format="csv")
    monkeypatch.setenv("SPECTRA_SHERPA_EXPORT_DIR", str(tmp_path))

    archive_path = Path(export_artifacts({"export": {"artifact": artifact}}, "canonical-export"))
    output_dir = archive_path.with_suffix("")

    assert (output_dir / "scientist.csv").read_text() == artifact["content"]
    summary = json.loads((output_dir / "export_summary.json").read_text())
    assert summary["artifact"]["content_sha256"] == artifact["content_sha256"]
    assert "content" not in summary["artifact"]
    with zipfile.ZipFile(archive_path) as archive:
        exported_name = next(name for name in archive.namelist() if name.endswith("/scientist.csv"))
        assert archive.read(exported_name) == str(artifact["content"]).encode("utf-8")


def test_export_serialization_has_a_fixed_size_performance_ceiling() -> None:
    dataset = _spectra(rows=200, columns=1600)
    with PerformanceCeiling("output.export", "200x1600-csv", 5.0).measure():
        artifact = build_export_artifact(dataset, filename="representative.csv", format="csv")

    assert artifact["shape"] == [200, 1600]
    assert artifact["content_sha256"]


@pytest.mark.parametrize(
    ("template_name", "expected_source", "expected_port"),
    [
        ("preprocessing.yaml", "preprocess_3", None),
        ("mcr_als_kinetics.yaml", "model_1", "C"),
        ("simplisma.yaml", "model_1", "spectra"),
    ],
)
def test_curated_projects_export_scientific_arrays_not_visualizations(
    template_name: str,
    expected_source: str,
    expected_port: str | None,
) -> None:
    template_path = Path(__file__).parents[1] / "src" / "spectra_sherpa" / "data" / "templates" / template_name
    template = yaml.safe_load(template_path.read_text())
    export_edge = next(edge for edge in template["template_data"]["edges"] if edge["to_node_id"] == "export_1")

    assert export_edge["from_node_id"] == expected_source
    assert export_edge.get("from_output") == expected_port
    assert export_edge.get("from_output") != "visualization"
