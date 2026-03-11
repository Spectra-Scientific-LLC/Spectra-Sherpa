from __future__ import annotations

import numpy as np

from spectra_sherpa.app.lib.io import load_csv_as_sherpa, stack_datasets
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.spectral.dataset import SpectralUnit, create_spectral_dataset


def test_load_csv_as_sherpa_named_feature_columns_preserves_target(tmp_path):
    csv_path = tmp_path / "sklearn_wine.csv"
    csv_path.write_text(
        "alcohol,malic_acid,ash,target\n" "14.23,1.71,2.43,class_0\n" "13.20,1.78,2.14,class_1\n",
        encoding="ascii",
    )

    dataset = load_csv_as_sherpa(csv_path)

    assert isinstance(dataset, SherpaDataset)
    assert dataset.X.shape == (2, 3)
    assert dataset.feature_axis is not None
    assert dataset.feature_axis.labels == ["alcohol", "malic_acid", "ash"]
    assert dataset.sample_axis is not None
    assert dataset.sample_axis.title == "Sample"
    np.testing.assert_array_equal(dataset.target, np.array(["class_0", "class_1"]))
    assert dataset.target_context is not None
    assert dataset.target_context.target_type == "categorical"
    assert dataset.target_context.target_name == "target"


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
