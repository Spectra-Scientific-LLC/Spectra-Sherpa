from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.io import load_csv_as_sherpa, stack_datasets
from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode
from spectra_sherpa.app.services.prepared_data import apply_dataset_prepared_data_overrides

try:
    from spectra_sherpa.app.lib.spectral.dataset import SpectralUnit, create_spectral_dataset
except ImportError:
    create_spectral_dataset = None


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


def test_load_csv_as_sherpa_respects_explicit_feature_role_with_numeric_headers(tmp_path):
    csv_path = tmp_path / "ambiguous.csv"
    csv_path.write_text("1000,1001,class\n1.0,2.0,A\n3.0,4.0,B\n", encoding="ascii")

    dataset = load_csv_as_sherpa(csv_path, data_role="X_features", target_column="class")

    assert dataset.data_role == "X_features"
    assert dataset.feature_axis is not None
    assert dataset.feature_axis.labels == ["1000", "1001"]
    np.testing.assert_array_equal(dataset.target, np.array(["A", "B"]))


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
    assert dataset.domain.data_quantity == "Intensity"


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


def test_filter_samples_node_is_available_in_data_sources_category():
    assert FilterSamplesNode.metadata.category == "data"
    assert FilterSamplesNode.metadata.node_type == "data.filter_samples"
    assert FilterSamplesNode.metadata.label == "Filter Samples"
    field_param = next(param for param in FilterSamplesNode.metadata.parameters if param.name == "field")
    assert {"label": "Intensity", "value": "intensity"} in field_param.options


@pytest.mark.skipif(not HAS_SCP, reason="SpectroChemPy not installed")
def test_stack_datasets_preserves_string_sample_labels_for_multispectrum_files():
    wavenumbers = np.array([1000.0, 1001.0, 1002.0])
    ds1 = create_spectral_dataset(
        data=np.array([1.0, 2.0, 3.0]),
        wavenumbers=wavenumbers,
        units=SpectralUnit.ABSORBANCE,
        title="scan_001",
    )
    ds2 = create_spectral_dataset(
        data=np.array([4.0, 5.0, 6.0]),
        wavenumbers=wavenumbers,
        units=SpectralUnit.ABSORBANCE,
        title="scan_002",
    )

    stacked = stack_datasets([ds1, ds2])

    assert stacked.shape == (2, 3)
    np.testing.assert_array_equal(stacked.y.data, np.array([0, 1]))
    assert list(stacked.y.labels) == ["scan_001", "scan_002"]
