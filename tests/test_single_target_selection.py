"""Exact named response selection preserves portable one-column target identity."""

import numpy as np
import pytest

from spectra_sherpa.app.lib.io import select_dataset_target
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext


@pytest.mark.parametrize("target_type,values", [("continuous", [1.0, 2.0, 3.0]), ("categorical", ["A", "B", "A"])])
def test_sole_named_vector_can_be_explicitly_selected(target_type, values):
    dataset = SherpaDataset(
        np.eye(3),
        target=np.asarray(values),
        target_context=TargetContext(target_type=target_type, target_names=["response"]),
    )
    selected = select_dataset_target(dataset, selected_target="response", target_type=target_type)
    np.testing.assert_array_equal(selected.target, values)
    np.testing.assert_array_equal(selected.X, np.eye(3))
    assert selected.target_context.selected_target == "response"


@pytest.mark.parametrize(
    "names,selected,type_",
    [
        (["response"], "other", "continuous"),
        (["response", "other"], "response", "continuous"),
        (["response"], "response", "categorical"),
    ],
)
def test_single_vector_selection_does_not_invent_authority(names, selected, type_):
    dataset = SherpaDataset(
        np.eye(3), target=np.arange(3.0), target_context=TargetContext(target_type="continuous", target_names=names)
    )
    with pytest.raises(ValueError):
        select_dataset_target(dataset, selected_target=selected, target_type=type_)
