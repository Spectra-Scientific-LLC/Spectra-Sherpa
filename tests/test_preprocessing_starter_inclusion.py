"""The shipped preprocessing graph materializes source inclusion before numerics."""

from copy import deepcopy

import numpy as np
import pytest

from tests.test_accessible_template_execution_matrix import _executor, _spectral_fixture, _template_entries


@pytest.mark.parametrize("excluded", [False, True])
@pytest.mark.asyncio
async def test_preprocessing_starter_preserves_active_identity_axes_and_source(tmp_path, excluded):
    entry = deepcopy(next(item for item in _template_entries() if item["slug"] == "preprocessing"))
    dataset, target = _spectral_fixture("preprocessing")
    n_rows, n_columns = dataset.shape
    ids = [f"specimen-{index:03d}" for index in range(n_rows)]
    sample_axis = dataset.sample_axis
    feature_axis = dataset.feature_axis
    sample_axis.sample_table = {"sample_id": ids}
    rows = np.ones(n_rows, dtype=bool)
    columns = np.ones(n_columns, dtype=bool)
    if excluded:
        rows[[2, 9]] = False
        sample_axis.include_mask = rows.copy()
        feature_axis.include_mask = columns.copy()
    dataset.sample_axis = sample_axis
    dataset.feature_axis = feature_axis
    before = dataset.copy()
    executor = _executor(entry, tmp_path)
    executor.inject_result("data_1", {"default": dataset, "target": target})
    results = await executor.execute()
    active = results["inclusion_1"]["default"]
    prepared = results["preprocess_3"]["default"]
    np.testing.assert_array_equal(active.X, before.X[np.ix_(rows, columns)])
    for result in [active, prepared]:
        assert result.shape == (int(rows.sum()), int(columns.sum()))
        assert list(result.sample_axis.labels) == list(np.asarray(before.sample_axis.labels)[rows])
        assert result.sample_axis.sample_table["sample_id"] == list(np.asarray(ids)[rows])
        np.testing.assert_array_equal(result.feature_axis.values, before.feature_axis.values[columns])
        assert result.feature_axis.units == "cm-1"
        np.testing.assert_array_equal(result.target, target[rows])
        assert np.isfinite(result.X).all()
    np.testing.assert_array_equal(dataset.X, before.X)
    if excluded:
        np.testing.assert_array_equal(dataset.sample_axis.include_mask, rows)
        np.testing.assert_array_equal(dataset.feature_axis.include_mask, columns)


@pytest.mark.parametrize("axis_kind", ["samples", "features"])
@pytest.mark.asyncio
async def test_preprocessing_starter_preserves_population_and_feature_refusals(tmp_path, axis_kind):
    entry = deepcopy(next(item for item in _template_entries() if item["slug"] == "preprocessing"))
    dataset, target = _spectral_fixture("preprocessing")
    if axis_kind == "samples":
        axis = dataset.sample_axis
        axis.include_mask = np.zeros(dataset.shape[0], dtype=bool)
        dataset.sample_axis = axis
        message = "selected 0"
    else:
        # A sample filter is not an implicit feature-selection operation.
        axis = dataset.feature_axis
        axis.include_mask = np.ones(dataset.shape[1], dtype=bool)
        axis.include_mask[3] = False
        dataset.feature_axis = axis
        message = "excluded variables"
    executor = _executor(entry, tmp_path)
    executor.inject_result("data_1", {"default": dataset, "target": target})
    with pytest.raises(ValueError, match=message):
        await executor.execute()
