"""One capsule-independent authority for dataset and split identities."""

from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.sdk import dataset_identity
from spectra_sherpa.sdk.validate import make_split_plan


def test_public_dataset_identity_is_container_independent_and_content_bound() -> None:
    X = np.arange(24, dtype=np.float32).reshape(6, 4)  # noqa: N806 - scientific convention
    y = np.linspace(0.25, 1.5, 6, dtype=np.float32)
    groups = np.asarray(["a", "a", "b", "b", "c", "c"])

    expected = dataset_identity.public_dataset_digest(X, y, groups=groups)

    assert dataset_identity.public_dataset_digest(X.tolist(), y.tolist(), groups=groups.tolist()) == expected
    assert dataset_identity.public_dataset_digest(np.asfortranarray(X), y.astype(">f8"), groups=groups) == expected
    assert dataset_identity.public_dataset_digest(X, y, groups=None) != expected
    changed = X.copy()
    changed[0, 0] = -1
    assert dataset_identity.public_dataset_digest(changed, y, groups=groups) != expected


def test_split_identity_binds_exact_fold_membership() -> None:
    first = make_split_plan(12, n_splits=3)
    repeat = make_split_plan(12, n_splits=3)
    changed = make_split_plan(12, n_splits=4)

    assert dataset_identity.split_plan_digest(first) == dataset_identity.split_plan_digest(repeat)
    assert dataset_identity.split_plan_digest(first) != dataset_identity.split_plan_digest(changed)


@pytest.mark.parametrize(
    ("X", "y", "groups", "message"),
    [
        ([[1.0]], [1.0], None, "feature shape"),
        ([[1.0], [2.0]], [1.0], None, "one value per sample"),
        ([[1.0], [2.0]], [1.0, float("nan")], None, "finite"),
        ([[1.0], [2.0]], [1.0, 2.0], ["only-one"], "groups"),
    ],
)
def test_public_dataset_identity_rejects_malformed_arrays(X, y, groups, message: str) -> None:
    with pytest.raises(dataset_identity.DatasetIdentityError, match=message):
        dataset_identity.public_dataset_digest(X, y, groups=groups)
