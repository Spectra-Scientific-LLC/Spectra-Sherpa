from __future__ import annotations

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.data import DataSourceNode


def test_load_csv_pandas_named_feature_columns_returns_sherpa_dataset(tmp_path):
    csv_path = tmp_path / "sklearn_wine.csv"
    csv_path.write_text(
        "alcohol,malic_acid,ash,target\n" "14.23,1.71,2.43,class_0\n" "13.20,1.78,2.14,class_1\n",
        encoding="ascii",
    )

    node = DataSourceNode("csv_test")
    dataset = node._load_csv_pandas(str(csv_path))

    assert isinstance(dataset, SherpaDataset)
    assert dataset.X.shape == (2, 3)
    assert dataset.feature_axis is not None
    assert dataset.feature_axis.labels == ["alcohol", "malic_acid", "ash"]
    np.testing.assert_array_equal(dataset.target, np.array(["class_0", "class_1"]))
    assert dataset.target_context is not None
    assert dataset.target_context.target_type == "categorical"
    assert dataset.target_context.target_name == "target"


def test_load_csv_pandas_axis_column_conditions_returns_spectral_sherpa_dataset(tmp_path):
    csv_path = tmp_path / "raman_conditions.csv"
    csv_path.write_text(
        "Wavenumber (cm-1),Aqueous PP,15:85 AuNPs:PP AuNPs with KCl\n"
        "200,2139,9549\n"
        "201,2159,9538\n"
        "202,2178,9537\n",
        encoding="ascii",
    )

    node = DataSourceNode("csv_test")
    dataset = node._load_csv_pandas(str(csv_path))

    assert isinstance(dataset, SherpaDataset)
    assert dataset.data_role == "X_spectra"
    assert dataset.X.shape == (2, 3)
    assert dataset.feature_axis is not None
    np.testing.assert_allclose(dataset.feature_axis.values, np.array([200.0, 201.0, 202.0]))
    assert dataset.sample_axis is not None
    assert dataset.sample_axis.labels == ["Aqueous PP", "15:85 AuNPs:PP AuNPs with KCl"]
