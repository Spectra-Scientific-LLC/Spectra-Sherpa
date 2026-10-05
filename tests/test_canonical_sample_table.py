"""Closed portable sample-table handoff into canonical preparation nodes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - register built-ins
from spectra_sherpa.app.lib.export_artifact import build_export_artifact
from spectra_sherpa.app.lib.io import load_canonical_file_as_sherpa
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.sample_table import (
    SAMPLE_TABLE_SCHEMA_VERSION,
    apply_sample_table_to_dataset,
    inspect_portable_sample_table,
    load_portable_sample_table,
    load_portable_sample_table_editor,
    validate_sample_table_payload,
)
from spectra_sherpa.app.services.dataset_analysis_readiness import validate_analysis_binding
from spectra_sherpa.core.spectra_meta import DataProvenance, SourceType, SpectraMeta, set_spectra_meta


def _write_table(path: Path, *, source_file_id: int = 41) -> Path:
    path.write_text(
        "row_index,source_file_id,sample_id,include,target_schema,moisture,cultivar,plate_id,well,batch\n"
        f'0,{source_file_id},sample-0001,true,"{{""moisture"":""continuous"",""cultivar"":""categorical""}}",10.0,A,plate-1,A01,calibration\n'
        f'1,{source_file_id},sample-0002,false,"{{""moisture"":""continuous"",""cultivar"":""categorical""}}",11.0,B,plate-1,A02,holdout\n'
        f'2,{source_file_id},sample-0003,true,"{{""moisture"":""continuous"",""cultivar"":""categorical""}}",12.0,A,plate-1,A03,calibration\n',
        encoding="utf-8",
    )
    return path


def _spectra(*, file_id: int = 41) -> SherpaDataset:
    dataset = SherpaDataset(
        X=np.arange(12, dtype=np.float64).reshape(3, 4),
        feature_axis=SpectralAxis(
            values=np.linspace(1000.0, 1300.0, 4),
            title="Wavelength",
            units="nm",
        ),
        sample_axis=SampleAxis(labels=["sample-0001", "sample-0002", "sample-0003"]),
        backend="numpy",
    )
    set_spectra_meta(
        dataset,
        SpectraMeta(
            provenance=DataProvenance(
                source_type=SourceType.EXPERIMENT,
                experiment_id=7,
                file_id=file_id,
            )
        ),
    )
    return dataset


def test_dataset_analysis_binding_requires_exact_csv_source_identity(tmp_path: Path) -> None:
    source_path = tmp_path / "source.npz"
    source_path.write_bytes(b"source")
    table_path = _write_table(tmp_path / "samples.csv", source_file_id=41)
    source = type(
        "SourceFile",
        (),
        {
            "id": 41,
            "experiment_id": 7,
            "file_path": source_path.name,
            "created_at": None,
        },
    )()
    table = type(
        "TableFile",
        (),
        {
            "id": 73,
            "experiment_id": 7,
            "file_path": table_path.name,
        },
    )()

    validate_analysis_binding(
        source_file=source,
        sample_table_file=table,
        selected_target="moisture",
        target_type="continuous",
        load_source=lambda _: _spectra(file_id=41),
        experiment_root=tmp_path,
    )

    mismatched = type(
        "WrongTableFile",
        (),
        {"id": 74, "experiment_id": 8, "file_path": table_path.name},
    )()
    with pytest.raises(ValueError, match="same dataset"):
        validate_analysis_binding(
            source_file=source,
            sample_table_file=mismatched,
            selected_target="moisture",
            target_type="continuous",
            load_source=lambda _: _spectra(file_id=41),
            experiment_root=tmp_path,
        )


def test_sample_table_loader_emits_one_closed_json_safe_value(tmp_path: Path) -> None:
    table = load_portable_sample_table(
        _write_table(tmp_path / "samples.csv"),
        selected_target="moisture",
        target_type="continuous",
    )

    assert table == {
        "schema_version": SAMPLE_TABLE_SCHEMA_VERSION,
        "source_file_id": 41,
        "row_indices": [0, 1, 2],
        "sample_ids": ["sample-0001", "sample-0002", "sample-0003"],
        "include": [True, False, True],
        "target_definitions": {"moisture": "continuous", "cultivar": "categorical"},
        "target_name": "moisture",
        "target_type": "continuous",
        "target_values": [10.0, 11.0, 12.0],
        "annotations": {
            "include": ["true", "false", "true"],
            "source_file_id": [41, 41, 41],
            "row_index": [0, 1, 2],
            "plate_id": ["plate-1", "plate-1", "plate-1"],
            "well": ["A01", "A02", "A03"],
            "batch": ["calibration", "holdout", "calibration"],
        },
    }


def test_sample_table_round_trip_preserves_lexical_identities_and_categories(tmp_path: Path) -> None:
    path = tmp_path / "categories.csv"
    path.write_text(
        "row_index,source_file_id,sample_id,include,target_schema,class,plate_id,well,batch\n"
        '0,41,001,true,"{""class"":""categorical""}",01,0001,A01,001\n'
        '1,41,002,true,"{""class"":""categorical""}",02,0001,A02,002\n',
        encoding="utf-8",
    )

    editor = load_portable_sample_table_editor(
        path,
        selected_target="class",
        target_type="categorical",
    )

    assert editor is not None
    assert [row["sample_id"] for row in editor["rows"]] == ["001", "002"]
    assert [row["targets"]["class"] for row in editor["rows"]] == ["01", "02"]
    assert [row["plate_id"] for row in editor["rows"]] == ["0001", "0001"]
    assert [row["annotations"]["batch"] for row in editor["rows"]] == ["001", "002"]

    loaded = load_portable_sample_table(
        path,
        selected_target="class",
        target_type="categorical",
    )
    assert loaded is not None
    assert loaded["sample_ids"] == ["001", "002"]
    assert loaded["target_values"] == ["01", "02"]
    assert loaded["annotations"]["plate_id"] == ["0001", "0001"]


def test_sample_table_inspection_reports_all_typed_targets_without_selecting_one(tmp_path: Path) -> None:
    assert inspect_portable_sample_table(_write_table(tmp_path / "samples.csv")) == {
        "moisture": "continuous",
        "cultivar": "categorical",
    }


@pytest.mark.asyncio
async def test_ready_supervised_template_executes_attach_filter_and_export_without_semantic_loss(
    tmp_path: Path,
) -> None:
    template_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "spectra_sherpa"
        / "data"
        / "templates"
        / "supervised_data_preparation.yaml"
    )
    template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    assert template["status"] == "ready"
    assert template["template_data"]["data_roles"]["Y_reference"]["binding_mode"] == "separate_source"

    table = load_portable_sample_table(
        _write_table(tmp_path / "samples.csv"),
        selected_target="moisture",
        target_type="continuous",
    )
    attach = node_registry.create_node(
        "data.attach_target",
        "attach",
        {"target_type": "continuous"},
    )
    attached = (
        await attach.execute(
            X=_spectra(),
            y=np.asarray([10.0, 11.0, 12.0]),
            sample_table=table,
        )
    )["default"]

    assert attached.target_context.target_names == ["moisture"]
    assert attached.target_context.target_name == "moisture"
    assert attached.target_context.selected_target == "moisture"
    assert attached.sample_axis.labels == ["sample-0001", "sample-0002", "sample-0003"]
    assert attached.sample_axis.include_mask.tolist() == [True, False, True]
    assert attached.sample_axis.sample_table["well"] == ["A01", "A02", "A03"]

    filter_node = node_registry.create_node(
        "data.filter_samples",
        "filter",
        {
            "field": "sample_table",
            "sample_table_column": "include",
            "filter_values": ["true"],
        },
    )
    filtered = (await filter_node.execute(X=attached))["default"]

    assert filtered.shape == (2, 4)
    assert filtered.sample_axis.labels == ["sample-0001", "sample-0003"]
    assert filtered.sample_axis.sample_table["well"] == ["A01", "A03"]
    np.testing.assert_array_equal(filtered.target, np.asarray([10.0, 12.0]))

    export_definition = next(
        node for node in template["template_data"]["nodes"] if node["node_type"] == "output.export"
    )
    export = node_registry.create_node(
        "output.export",
        "export",
        export_definition["parameters"],
    )
    artifact = (await export.execute(filtered))["artifact"]
    assert artifact == build_export_artifact(
        filtered,
        filename="prepared-supervised-data.csv",
        format="csv",
    )
    prepared_path = tmp_path / "prepared.csv"
    prepared_path.write_text(str(artifact["content"]), encoding="utf-8")
    reloaded = load_canonical_file_as_sherpa(
        prepared_path,
        selected_target="moisture",
        target_type="continuous",
    )

    np.testing.assert_array_equal(reloaded.X, filtered.X)
    np.testing.assert_array_equal(reloaded.target, filtered.target)
    assert reloaded.sample_axis.labels == ["sample-0001", "sample-0003"]
    assert reloaded.sample_axis.sample_table["well"] == ["A01", "A03"]
    assert reloaded.target_context.target_name == "moisture"


def test_sample_table_rejects_partial_signature_instead_of_becoming_features(tmp_path: Path) -> None:
    path = tmp_path / "partial.csv"
    path.write_text("row_index,sample_id,moisture\n0,sample-1,10\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing structural columns"):
        load_portable_sample_table(path, selected_target="moisture", target_type="continuous")


def test_single_sample_identity_column_remains_an_ordinary_scientific_csv(tmp_path: Path) -> None:
    path = tmp_path / "spectra.csv"
    path.write_text(
        "sample_id,1000.0,1001.0\nCorn_row_0001,0.1,0.2\nCorn_row_0002,0.3,0.4\n",
        encoding="utf-8",
    )

    assert inspect_portable_sample_table(path) is None
    assert (
        load_portable_sample_table(
            path,
            selected_target="Moisture",
            target_type="continuous",
        )
        is None
    )


def test_sample_table_rejects_plate_coordinates_as_target_names(tmp_path: Path) -> None:
    path = _write_table(tmp_path / "reserved-target.csv")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '""moisture"":""continuous""',
            '""plate_id"":""continuous""',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="closed scientific types"):
        inspect_portable_sample_table(path)


@pytest.mark.asyncio
async def test_categorical_sample_table_preserves_classes_and_exact_identity(tmp_path: Path) -> None:
    path = tmp_path / "classes.csv"
    path.write_text(
        "row_index,source_file_id,sample_id,include,target_schema,class_name,plate_id,well\n"
        '0,41,sample-0001,true,"{""class_name"":""categorical""}",control,plate-1,A01\n'
        '1,41,sample-0002,true,"{""class_name"":""categorical""}",treated,plate-1,A02\n'
        '2,41,sample-0003,true,"{""class_name"":""categorical""}",control,plate-1,A03\n',
        encoding="utf-8",
    )
    table = load_portable_sample_table(
        path,
        selected_target="class_name",
        target_type="categorical",
    )
    attach = node_registry.create_node("data.attach_target", "attach", {"target_type": "categorical"})

    attached = (
        await attach.execute(
            X=_spectra(),
            y=np.asarray(["control", "treated", "control"]),
            sample_table=table,
        )
    )["default"]

    assert attached.target_context.target_name == "class_name"
    assert attached.target_context.class_names == ["control", "treated"]
    assert attached.sample_axis.classes.tolist() == ["control", "treated", "control"]


def test_categorical_sample_table_ignores_missing_target_on_excluded_row(tmp_path: Path) -> None:
    path = tmp_path / "classes-with-exclusion.csv"
    path.write_text(
        "row_index,source_file_id,sample_id,include,target_schema,class_name,plate_id,well\n"
        '0,41,sample-0001,true,"{""class_name"":""categorical""}",control,plate-1,A01\n'
        '1,41,sample-0002,false,"{""class_name"":""categorical""}",,plate-1,A02\n'
        '2,41,sample-0003,true,"{""class_name"":""categorical""}",treated,plate-1,A03\n',
        encoding="utf-8",
    )

    table = load_portable_sample_table(
        path,
        selected_target="class_name",
        target_type="categorical",
    )
    loaded = load_canonical_file_as_sherpa(
        path,
        selected_target="class_name",
        target_type="categorical",
    )

    assert table is not None
    assert table["target_values"] == ["control", None, "treated"]
    assert loaded.target_context.class_names == ["control", "treated"]
    assert loaded.target_context.n_classes == 2
    assert np.isnan(loaded.target[1])


def test_closed_sample_table_rejects_an_empty_cohort(tmp_path: Path) -> None:
    table = load_portable_sample_table(
        _write_table(tmp_path / "samples.csv"),
        selected_target="moisture",
        target_type="continuous",
    )
    assert table is not None
    table["include"] = [False, False, False]
    table["annotations"]["include"] = ["false", "false", "false"]

    with pytest.raises(ValueError, match="at least one sample"):
        validate_sample_table_payload(table)


@pytest.mark.parametrize(
    ("transform", "message"),
    [
        (lambda text: text.replace("1,41,sample-0002", "1.5,41,sample-0002"), "finite integers"),
        (lambda text: text.replace("plate-1,A02", "plate-1,Z99"), "outside 96-well plate"),
    ],
)
def test_sample_table_rejects_malformed_identity_or_plate_coordinates(
    tmp_path: Path,
    transform: object,
    message: str,
) -> None:
    path = _write_table(tmp_path / "samples.csv")
    path.write_text(transform(path.read_text(encoding="utf-8")), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_portable_sample_table(path, selected_target="moisture", target_type="continuous")


def test_sample_table_rejects_duplicate_physical_well_assignments(tmp_path: Path) -> None:
    path = _write_table(tmp_path / "duplicate-well.csv")
    path.write_text(
        path.read_text(encoding="utf-8").replace("plate-1,A02,holdout", "plate-1,A01,holdout"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="rows 1 and 2 assign duplicate.*plate-1/A01"):
        load_portable_sample_table(path, selected_target="moisture", target_type="continuous")

    table = load_portable_sample_table(
        _write_table(tmp_path / "valid.csv"),
        selected_target="moisture",
        target_type="continuous",
    )
    assert table is not None
    table["annotations"]["well"][1] = "A01"
    with pytest.raises(ValueError, match="rows 1 and 2 assign duplicate.*plate-1/A01"):
        validate_sample_table_payload(table)


def test_sample_table_records_explicit_plate_format_and_rejects_unknown_format(tmp_path: Path) -> None:
    path = _write_table(tmp_path / "explicit-format.csv")
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(
        "\n".join(
            [
                lines[0].replace(
                    "moisture,cultivar,plate_id,well,batch",
                    "moisture,cultivar,plate_format,plate_id,well,batch",
                ),
                *(line.replace(",plate-1,", ",plate-96,plate-1,", 1) for line in lines[1:]),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    table = load_portable_sample_table(
        path,
        selected_target="moisture",
        target_type="continuous",
    )
    assert table is not None
    assert table["annotations"]["plate_format"] == ["plate-96"] * 3

    path.write_text(path.read_text(encoding="utf-8").replace("plate-96", "plate-384"), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown plate format"):
        load_portable_sample_table(
            path,
            selected_target="moisture",
            target_type="continuous",
        )


def test_sample_table_attachment_rejects_wrong_source_and_wrong_target(tmp_path: Path) -> None:
    table = load_portable_sample_table(
        _write_table(tmp_path / "samples.csv"),
        selected_target="moisture",
        target_type="continuous",
    )

    with pytest.raises(ValueError, match="source_file_id does not match"):
        apply_sample_table_to_dataset(_spectra(file_id=99), table)


@pytest.mark.asyncio
async def test_attach_target_rejects_target_values_that_disagree_with_sample_table(tmp_path: Path) -> None:
    table = load_portable_sample_table(
        _write_table(tmp_path / "samples.csv"),
        selected_target="moisture",
        target_type="continuous",
    )
    attach = node_registry.create_node(
        "data.attach_target",
        "attach",
        {"target_type": "continuous"},
    )

    with pytest.raises(ValueError, match="do not exactly match"):
        await attach.execute(
            X=_spectra(),
            y=np.asarray([10.0, 99.0, 12.0]),
            sample_table=table,
        )


def test_file_load_and_attach_target_publish_the_typed_sample_table_boundary() -> None:
    file_outputs = {port.name: port.type_ref for port in node_registry.get_metadata("data.file_load").output_ports}
    attach_inputs = {
        port.name: (port.type_ref, port.required)
        for port in node_registry.get_metadata("data.attach_target").input_ports
    }

    assert file_outputs["sample_table"] == "spectrasherpa://types/SampleTable/2.0"
    assert attach_inputs["sample_table"] == ("spectrasherpa://types/SampleTable/2.0", False)
