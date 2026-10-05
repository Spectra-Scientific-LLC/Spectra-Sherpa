from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.collection_assembly import CollectionMember, assemble_collection
from spectra_sherpa.app.lib.io import inspect_csv_import_plan, load_csv_as_sherpa
from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, SampleAxis, SherpaDataset
from spectra_sherpa.app.services import prepared_data as prepared_data_service
from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode
from spectra_sherpa.app.services.prepared_data import apply_dataset_prepared_data_overrides
from spectra_sherpa.core.prepared_data import PreparedDataOverrides, parser_options_for_prepared_data


def test_csv_layout_sidecar_is_closed_and_source_typed() -> None:
    with pytest.raises(ValueError, match="csv_layout must be one of"):
        PreparedDataOverrides.from_sidecar_mapping({"csv_layout": "supplier_magic"})

    with pytest.raises(ValueError, match="only to a CSV source"):
        parser_options_for_prepared_data(
            "spectrum.spa",
            {"csv_layout": "headerless_two_column_spectrum"},
        )

    assert parser_options_for_prepared_data(
        "spectrum.CSV",
        {"csv_layout": "headered_decimal_comma"},
    ) == {"csv_layout": "headered_decimal_comma"}


def test_csv_layout_cannot_be_persisted_for_a_non_csv_or_reference_source(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prepared_data_service, "_OVERRIDES_DIR", tmp_path / "sidecars")
    override = PreparedDataOverrides(csv_layout="headerless_two_column_spectrum")

    with pytest.raises(ValueError, match="only to a CSV source"):
        prepared_data_service.save_prepared_data_overrides(override, file_path="source.spa")
    with pytest.raises(ValueError, match="requires one exact CSV file"):
        prepared_data_service.save_prepared_data_overrides(override, source="catalog", name="entry")

    prepared_data_service.save_prepared_data_overrides(override, file_path="source.csv")
    assert prepared_data_service.load_prepared_data_overrides(file_path="source.csv") == override


def test_load_csv_as_sherpa_named_feature_columns_preserves_target(tmp_path):
    csv_path = tmp_path / "sklearn_wine.csv"
    csv_path.write_text(
        "alcohol,malic_acid,ash,target\n" "14.23,1.71,2.43,class_0\n" "13.20,1.78,2.14,class_1\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path)

    assert isinstance(dataset, SherpaDataset)
    assert dataset.data_role == "X_features"
    assert dataset.X.shape == (2, 3)
    assert dataset.feature_axis is not None
    assert dataset.feature_axis.labels == ["alcohol", "malic_acid", "ash"]
    assert dataset.sample_axis is not None
    assert dataset.sample_axis.title == "Sample"
    np.testing.assert_array_equal(dataset.target, np.array(["class_0", "class_1"]))
    assert dataset.target_context is not None
    assert dataset.target_context.target_type == "categorical"
    assert dataset.target_context.target_name == "target"
    assert dataset.target_context.target_names == ["target"]
    assert dataset.target_context.selected_target == "target"
    assert dataset.target_context.class_names == ["class_0", "class_1"]


def test_load_csv_as_sherpa_respects_explicit_feature_role_with_numeric_headers(tmp_path):
    csv_path = tmp_path / "ambiguous.csv"
    csv_path.write_text("1000,1001,class\n1.0,2.0,A\n3.0,4.0,B\n", encoding="ascii")

    dataset = load_csv_as_sherpa(csv_path, data_role="X_features", target_column="class")

    assert dataset.data_role == "X_features"
    assert dataset.feature_axis is not None
    assert dataset.feature_axis.labels == ["1000", "1001"]
    np.testing.assert_array_equal(dataset.target, np.array(["A", "B"]))


def test_header_only_spectral_csv_preserves_a_typed_positional_sample_axis(tmp_path):
    csv_path = tmp_path / "UVSpectra10.csv"
    csv_path.write_text("190.5,191.0,191.5\n0.1,0.2,0.3\n0.4,0.5,0.6\n", encoding="ascii")

    dataset = load_csv_as_sherpa(csv_path)

    assert dataset.data_role == "X_spectra"
    assert dataset.feature_axis is not None
    assert dataset.feature_axis.title == "Wavelength"
    assert dataset.feature_axis.units == "nm"
    assert dataset.sample_axis is not None
    assert dataset.sample_axis.title == "Sample"
    assert dataset.sample_axis.labels is None
    np.testing.assert_array_equal(dataset.sample_axis.values, np.array([0.0, 1.0]))

    admitted = assemble_collection(
        [
            CollectionMember(
                dataset=dataset,
                file_name=csv_path.name,
                size_bytes=csv_path.stat().st_size,
                sha256="a" * 64,
            )
        ],
        title="UV/OES upload",
    )
    assert admitted.X.shape == (2, 3)


def test_csv_inspector_reports_the_final_spectral_property_and_metadata_mapping(tmp_path):
    csv_path = tmp_path / "portable-spectra.csv"
    csv_path.write_text(
        "sample,400,401,reference_a,reference_b,sample_meta.fault_name\n"
        "s1,0.1,0.2,1,0,normal\n"
        "s2,0.3,0.4,0,1,fault\n",
        encoding="ascii",
    )

    plan = inspect_csv_import_plan(csv_path)

    assert plan["layout"] == "sample_rows_spectral_matrix"
    assert plan["shape"] == {"rows": 2, "columns": 6, "samples": 2, "features": 2}
    assert plan["target"] == {"column": None, "type": None, "candidates": []}
    assert {column["name"]: column["role"] for column in plan["columns"]} == {
        "sample": "I",
        "400": "F",
        "401": "F",
        "reference_a": "P",
        "reference_b": "P",
        "sample_meta.fault_name": "M",
    }


def test_load_csv_as_sherpa_axis_column_conditions_as_shared_x_spectra(tmp_path):
    csv_path = tmp_path / "Au NPs PEDOTPSS Raman Spectra.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n"
        "200,2139,9549\n"
        "201,2159,9538\n"
        "202,2178,9537\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path)

    assert dataset.data_role == "X_spectra"
    assert dataset.X.shape == (2, 3)
    np.testing.assert_allclose(dataset.X[0], np.array([2139.0, 2159.0, 2178.0]))
    assert dataset.feature_axis is not None
    assert dataset.feature_axis.title == "Wavenumber"
    assert dataset.feature_axis.units == "cm-1"
    np.testing.assert_allclose(dataset.feature_axis.values, np.array([200.0, 201.0, 202.0]))
    assert dataset.sample_axis is not None
    assert dataset.sample_axis.labels == ["Aqueous PP", "15:85 AuNPs:PP AuNPs with KCl"]
    assert dataset.domain.technique == "raman"
    assert dataset.domain.data_quantity is None


def test_load_csv_as_sherpa_axis_column_unit_header_with_bom(tmp_path):
    csv_path = tmp_path / "pedot.csv"
    csv_path.write_text("\ufeffcm-1,PEDOT:PSS,PEDOT:PSS and NPs\n400,0.1,0.2\n401,0.3,0.4\n", encoding="utf-8")

    dataset = load_csv_as_sherpa(csv_path)

    assert dataset.data_role == "X_spectra"
    assert dataset.X.shape == (2, 2)
    assert dataset.feature_axis is not None
    assert dataset.feature_axis.title == "Wavenumber"
    assert dataset.feature_axis.units == "cm-1"
    np.testing.assert_allclose(dataset.feature_axis.values, np.array([400.0, 401.0]))
    assert dataset.sample_axis is not None
    assert dataset.sample_axis.labels == ["PEDOT:PSS", "PEDOT:PSS and NPs"]


def test_inspect_csv_import_plan_axis_column_roles(tmp_path):
    csv_path = tmp_path / "pedot.csv"
    csv_path.write_text("\ufeffcm-1,PEDOT:PSS,PEDOT:PSS and NPs\n400,0.1,0.2\n401,0.3,0.4\n", encoding="utf-8")

    plan = inspect_csv_import_plan(csv_path)

    assert plan["layout"] == "axis_column_spectra"
    assert plan["role_sequence"] == "WFF"
    assert plan["shape"]["samples"] == 2
    assert plan["shape"]["features"] == 2
    assert plan["axis"] == {"column": "cm-1", "title": "Wavenumber", "units": "cm-1"}
    assert plan["recommended_layout"] == "headered"
    assert {option["value"] for option in plan["layout_options"]} == {
        "headered",
        "headerless_two_column_spectrum",
        "headerless_axis_column_spectra",
        "headered_decimal_comma",
        "headerless_two_column_spectrum_decimal_comma",
        "headerless_axis_column_spectra_decimal_comma",
    }


def test_inspect_csv_import_plan_recommends_unheaded_xy_without_silently_losing_choice(tmp_path):
    csv_path = tmp_path / "supplier-export.csv"
    csv_path.write_text("400.0,0.10\n401.0,0.20\n402.0,0.30\n", encoding="ascii")

    plan = inspect_csv_import_plan(csv_path)

    assert plan["layout"] == "headerless_two_column_spectrum"
    assert plan["recommended_layout"] == "headerless_two_column_spectrum"
    assert plan["requires_confirmation"] is True
    assert plan["delimiter"] == "comma"
    assert plan["decimal"] == "point"
    assert plan["shape"] == {"rows": 3, "columns": 2, "samples": 1, "features": 3}


def test_unheaded_axis_column_matrix_preserves_uv_orientation_and_axis(tmp_path):
    csv_path = tmp_path / "UVSpectra10.csv"
    rows = [f"{190.529 + index:.3f},{index + 0.1},{index + 0.2},{index + 0.3}" for index in range(8)]
    csv_path.write_text("\n".join(rows) + "\n", encoding="ascii")

    plan = inspect_csv_import_plan(csv_path)
    dataset = load_csv_as_sherpa(csv_path, csv_layout="headerless_axis_column_spectra")

    assert plan["recommended_layout"] == "headerless_axis_column_spectra"
    assert plan["shape"] == {"rows": 8, "columns": 4, "samples": 3, "features": 8}
    assert plan["axis"] == {"column": "column 1", "title": "Wavelength", "units": "nm"}
    assert dataset.shape == (3, 8)
    assert dataset.feature_axis.title == "Wavelength"
    assert dataset.feature_axis.units == "nm"
    np.testing.assert_allclose(dataset.feature_axis.values, [190.529 + index for index in range(8)])
    np.testing.assert_allclose(dataset.X[0], [index + 0.1 for index in range(8)])


def test_decimal_comma_supplier_profiles_cover_headered_and_unheaded_spectra(tmp_path):
    headered = tmp_path / "supplier-headered.csv"
    headered.write_text("Wavenumber (cm-1);A;B\n400,0;0,10;0,20\n401,0;0,30;0,40\n", encoding="ascii")
    unheaded = tmp_path / "supplier-unheaded.csv"
    unheaded.write_text("400,0;0,10\n401,0;0,30\n402,0;0,50\n", encoding="ascii")

    headered_plan = inspect_csv_import_plan(headered)
    unheaded_plan = inspect_csv_import_plan(unheaded)
    headered_dataset = load_csv_as_sherpa(headered, csv_layout="headered_decimal_comma")
    unheaded_dataset = load_csv_as_sherpa(
        unheaded,
        csv_layout="headerless_two_column_spectrum_decimal_comma",
    )

    assert headered_plan["recommended_layout"] == "headered_decimal_comma"
    assert unheaded_plan["recommended_layout"] == "headerless_two_column_spectrum_decimal_comma"
    np.testing.assert_allclose(headered_dataset.feature_axis.values, [400.0, 401.0])
    np.testing.assert_allclose(headered_dataset.X, [[0.1, 0.3], [0.2, 0.4]])
    np.testing.assert_allclose(unheaded_dataset.feature_axis.values, [400.0, 401.0, 402.0])
    np.testing.assert_allclose(unheaded_dataset.X, [[0.1, 0.3, 0.5]])


def test_headerless_supplier_csv_preserves_explicit_missing_values_and_rejects_infinity(tmp_path):
    missing = tmp_path / "supplier-missing.csv"
    missing.write_text("400.0,#NaN\n401.0,0.20\n402.0,0.30\n", encoding="ascii")

    plan = inspect_csv_import_plan(missing)
    dataset = load_csv_as_sherpa(missing, csv_layout="headerless_two_column_spectrum")

    assert plan["recommended_layout"] == "headerless_two_column_spectrum"
    assert np.isnan(dataset.X[0, 0])
    np.testing.assert_array_equal(dataset.X[0, 1:], [0.2, 0.3])

    infinite = tmp_path / "supplier-infinite.csv"
    infinite.write_text("400.0,inf\n401.0,0.20\n402.0,0.30\n", encoding="ascii")
    with pytest.raises(ValueError, match="explicit headerless two-column"):
        load_csv_as_sherpa(infinite, csv_layout="headerless_two_column_spectrum")


def test_inspect_csv_import_plan_axis_column_reports_full_feature_count(tmp_path):
    csv_path = tmp_path / "long_axis.csv"
    rows = ["cm-1,A,B"]
    rows.extend(f"{400 + idx},{0.1 + idx},{0.2 + idx}" for idx in range(150))
    csv_path.write_text("\n".join(rows) + "\n", encoding="ascii")

    plan = inspect_csv_import_plan(csv_path)

    assert plan["layout"] == "axis_column_spectra"
    assert plan["shape"]["samples"] == 2
    assert plan["shape"]["features"] == 150
    assert plan["shape"]["rows"] == 150


def test_inspect_csv_import_plan_sample_rows_reports_full_sample_count(tmp_path):
    csv_path = tmp_path / "long_matrix.csv"
    rows = ["sample_id,1000,1001,1002"]
    rows.extend(f"s{idx},{idx}.0,{idx + 1}.0,{idx + 2}.0" for idx in range(125))
    csv_path.write_text("\n".join(rows) + "\n", encoding="ascii")

    plan = inspect_csv_import_plan(csv_path)

    assert plan["layout"] == "sample_rows_spectral_matrix"
    assert plan["shape"]["samples"] == 125
    assert plan["shape"]["features"] == 3
    assert plan["shape"]["rows"] == 125


def test_inspect_csv_import_plan_feature_table_target_roles(tmp_path):
    csv_path = tmp_path / "features.csv"
    csv_path.write_text("sample_id,alcohol,ash,species\ns1,1.0,2.0,A\ns2,3.0,4.0,B\n", encoding="ascii")

    plan = inspect_csv_import_plan(csv_path)

    assert plan["layout"] == "feature_table_with_target"
    assert plan["role_sequence"] == "IFFT"
    assert plan["target"]["column"] == "species"
    assert plan["target"]["type"] == "categorical"


def test_load_csv_as_sherpa_axis_column_layout_wins_over_feature_role(tmp_path):
    csv_path = tmp_path / "feature_table.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n" "200,2139,9549\n" "201,2159,9538\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path, data_role="X_features")

    assert dataset.data_role == "X_spectra"
    assert dataset.X.shape == (2, 2)
    assert dataset.feature_axis is not None
    np.testing.assert_allclose(dataset.feature_axis.values, np.array([200.0, 201.0]))
    assert dataset.sample_axis is not None
    assert dataset.sample_axis.labels == ["Aqueous PP", "15:85 AuNPs:PP AuNPs with KCl"]


def test_axis_column_csv_cannot_be_downgraded_by_prepared_feature_override(tmp_path):
    csv_path = tmp_path / "feature_table.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n" "200,2139,9549\n" "201,2159,9538\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path)
    dataset = apply_dataset_prepared_data_overrides(dataset, {"data_role": "X_features"})

    assert dataset.data_role == "X_spectra"
    assert dataset.X.shape == (2, 2)


def test_prepared_target_column_binds_registry_preserved_csv_property(tmp_path):
    csv_path = tmp_path / "feature_table.csv"
    csv_path.write_text(
        "length,width,target\n5.1,3.5,setosa\n7.0,3.2,versicolor\n",
        encoding="ascii",
    )

    from spectra_sherpa.app.services.dag.nodes.data.loaders import _load_registry_asset

    loaded = _load_registry_asset(
        csv_path,
        prepared_overrides={
            "data_role": "X_features",
            "target_column": "target",
            "target_type": "categorical",
        },
    )

    assert loaded.dataset.data_role == "X_features"
    assert loaded.dataset.feature_axis.labels == ["length", "width"]
    assert loaded.dataset.target.tolist() == ["setosa", "versicolor"]
    assert loaded.dataset.target_context.target_type == "categorical"
    assert loaded.dataset.target_context.target_names == ["target"]
    assert loaded.dataset.target_context.selected_target == "target"
    assert loaded.dataset.target_context.class_names == ["setosa", "versicolor"]


def test_prepared_target_column_replaces_an_inferred_target(tmp_path):
    csv_path = tmp_path / "feature_table.csv"
    csv_path.write_text(
        "length,width,inferred_target,chosen_target\n" "5.1,3.5,old-a,selected-b\n" "7.0,3.2,old-b,selected-a\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path, data_role="X_features", target_column="inferred_target")
    dataset = apply_dataset_prepared_data_overrides(
        dataset,
        {
            "target_column": "chosen_target",
            "target_type": "categorical",
        },
    )

    assert dataset.target.tolist() == ["selected-b", "selected-a"]
    assert dataset.target_context.target_name == "chosen_target"
    assert dataset.target_context.class_names == ["selected-a", "selected-b"]


@pytest.mark.asyncio
async def test_filter_samples_node_selects_shared_axis_csv_condition_by_label(tmp_path):
    csv_path = tmp_path / "raman_conditions.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n"
        "200,2139,9549\n"
        "201,2159,9538\n"
        "202,2178,9537\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path)
    node = FilterSamplesNode(
        "filter_kcl",
        parameters={
            "field": "sample_label",
            "pattern": "KCl",
            "match_mode": "contains",
        },
    )

    output = (await node.execute(X=dataset))["default"]

    assert output.data_role == "X_spectra"
    assert output.X.shape == (1, 3)
    np.testing.assert_allclose(output.X[0], np.array([9549.0, 9538.0, 9537.0]))
    assert output.feature_axis is not None
    assert output.feature_axis.title == "Wavenumber"
    assert output.feature_axis.units == "cm-1"
    np.testing.assert_allclose(output.feature_axis.values, np.array([200.0, 201.0, 202.0]))
    assert output.sample_axis is not None
    assert output.sample_axis.labels == ["15:85 AuNPs:PP AuNPs with KCl"]


@pytest.mark.asyncio
async def test_filter_samples_node_inverts_shared_axis_csv_label_selection(tmp_path):
    csv_path = tmp_path / "raman_conditions.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n"
        "200,2139,9549\n"
        "201,2159,9538\n"
        "202,2178,9537\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path)
    node = FilterSamplesNode(
        "filter_not_kcl",
        parameters={
            "field": "sample_label",
            "pattern": "KCl",
            "match_mode": "contains",
            "invert": True,
        },
    )

    output = (await node.execute(X=dataset))["default"]

    assert output.X.shape == (1, 3)
    np.testing.assert_allclose(output.X[0], np.array([2139.0, 2159.0, 2178.0]))
    assert output.sample_axis is not None
    assert output.sample_axis.labels == ["Aqueous PP"]


@pytest.mark.asyncio
async def test_filter_samples_node_selects_shared_axis_csv_condition_by_index(tmp_path):
    csv_path = tmp_path / "raman_conditions.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n"
        "200,2139,9549\n"
        "201,2159,9538\n"
        "202,2178,9537\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path)
    node = FilterSamplesNode(
        "filter_second",
        parameters={
            "field": "sample_index",
            "pattern": "2",
        },
    )

    output = (await node.execute(X=dataset))["default"]

    assert output.X.shape == (1, 3)
    np.testing.assert_allclose(output.X[0], np.array([9549.0, 9538.0, 9537.0]))
    assert output.sample_axis is not None
    assert output.sample_axis.labels == ["15:85 AuNPs:PP AuNPs with KCl"]


@pytest.mark.asyncio
async def test_filter_samples_node_selects_explicit_checkbox_values(tmp_path):
    csv_path = tmp_path / "raman_conditions.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n"
        "200,2139,9549\n"
        "201,2159,9538\n"
        "202,2178,9537\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path)
    node = FilterSamplesNode(
        "filter_checkbox",
        parameters={
            "field": "sample_label",
            "pattern": "",
            "filter_values": ["15:85 AuNPs:PP AuNPs with KCl"],
        },
    )

    output = (await node.execute(X=dataset))["default"]

    assert output.X.shape == (1, 3)
    np.testing.assert_allclose(output.X[0], np.array([9549.0, 9538.0, 9537.0]))
    assert output.sample_axis is not None
    assert output.sample_axis.labels == ["15:85 AuNPs:PP AuNPs with KCl"]


@pytest.mark.asyncio
async def test_filter_samples_node_allows_empty_explicit_checkbox_values(tmp_path):
    csv_path = tmp_path / "raman_conditions.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n"
        "200,2139,9549\n"
        "201,2159,9538\n"
        "202,2178,9537\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path)
    node = FilterSamplesNode(
        "filter_none",
        parameters={
            "field": "sample_label",
            "pattern": "",
            "filter_values": [],
            "allow_empty": True,
        },
    )

    output = (await node.execute(X=dataset))["default"]

    assert output.X.shape == (0, 3)
    assert output.sample_axis is not None
    assert output.sample_axis.labels == []


@pytest.mark.asyncio
async def test_filter_samples_node_selects_shared_axis_csv_condition_by_intensity(tmp_path):
    csv_path = tmp_path / "raman_conditions.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n"
        "200,2139,9549\n"
        "201,2159,9538\n"
        "202,2178,9537\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path)
    node = FilterSamplesNode(
        "filter_high_intensity",
        parameters={
            "field": "intensity",
            "intensity_metric": "max",
            "intensity_operator": "gte",
            "intensity_threshold": 9000.0,
        },
    )

    output = (await node.execute(X=dataset))["default"]

    assert output.X.shape == (1, 3)
    np.testing.assert_allclose(output.X[0], np.array([9549.0, 9538.0, 9537.0]))
    assert output.sample_axis is not None
    assert output.sample_axis.labels == ["15:85 AuNPs:PP AuNPs with KCl"]


@pytest.mark.asyncio
async def test_filter_samples_node_honors_unfolded_image_source_inclusions():
    dataset = SherpaDataset(
        X=np.arange(24.0).reshape(6, 4),
        sample_axis=SampleAxis(labels=[f"pixel-{index}" for index in range(1, 7)]),
        layout=DatasetLayoutContext(
            kind="image",
            source_type="image",
            source_dtype="float64",
            source_shape=(6, 4),
            mode_roles=("sample", "feature"),
            image_size=(2, 3),
            image_mode=1,
            image_include=(True, True, False, False, True, True),
            original_unfolded_shape=(6, 4),
        ),
        data_role="X_hsi",
    )
    node = FilterSamplesNode("filter_source_inclusions", parameters={"field": "source_inclusion"})

    output = (await node.execute(X=dataset))["default"]

    np.testing.assert_array_equal(output.X, dataset.X[[0, 1, 4, 5]])
    assert output.sample_axis is not None
    assert output.sample_axis.labels == ["pixel-1", "pixel-2", "pixel-5", "pixel-6"]
    assert output.data_role == "X_spectra"
    assert output.layout.kind == "generic"
    assert output.layout.source_type == "image-row-selection"
    assert output.layout.image_size is None
    assert output.layout.image_include is None
    assert output.layout.original_unfolded_shape == (6, 4)
    assert output.provenance[-1].parameters["selected_indices"] == (0, 1, 4, 5)


def test_filter_samples_node_is_available_in_data_sources_category():
    assert FilterSamplesNode.metadata.category == "data"
    assert FilterSamplesNode.metadata.node_type == "data.filter_samples"
    assert FilterSamplesNode.metadata.label == "Filter Samples"
    field_param = next(param for param in FilterSamplesNode.metadata.parameters if param.name == "field")
    assert {"label": "Intensity", "value": "intensity"} in field_param.options
    assert {"label": "Source Inclusion", "value": "source_inclusion"} in field_param.options
