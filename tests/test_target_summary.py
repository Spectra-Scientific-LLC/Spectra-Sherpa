from __future__ import annotations

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.lib.target_summary import target_summary


def test_target_summary_preserves_categorical_contract_and_completeness() -> None:
    dataset = SherpaDataset(
        X=np.ones((3, 2)),
        target=np.asarray(["class_a", "", None], dtype=object),
        target_context=TargetContext(
            target_type="categorical",
            target_name="target",
            target_names=["target"],
            selected_target="target",
            class_names=["class_a", "class_b"],
            n_classes=2,
        ),
    )

    assert target_summary(dataset) == {
        "target_names": ["target"],
        "target_types": {"target": "categorical"},
        "target_row_count": 3,
        "target_any_rows": 1,
        "target_complete_rows": 1,
    }


def test_target_summary_projects_all_native_numeric_responses() -> None:
    dataset = SherpaDataset(
        X=np.ones((2, 2)),
        target=np.asarray([[1.0, np.nan], [2.0, 3.0]]),
        target_context=TargetContext(
            target_type="continuous",
            target_names=["water", "methane"],
        ),
    )

    assert target_summary(dataset) == {
        "target_names": ["water", "methane"],
        "target_types": {"water": "continuous", "methane": "continuous"},
        "target_row_count": 2,
        "target_any_rows": 2,
        "target_complete_rows": 1,
    }
