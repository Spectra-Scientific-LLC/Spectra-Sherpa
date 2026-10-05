from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.lib.target_authority import issue_target_authority, verify_target_authority
from spectra_sherpa.core.target_authority import TargetAuthority, admit_target_authority


def _dataset() -> SherpaDataset:
    dataset = SherpaDataset(
        X=np.arange(18, dtype=float).reshape(3, 6),
        sample_axis=SampleAxis(
            labels=["s1", "s2", "s3"],
            sample_table={
                "sample_id": ["s1", "s2", "s3"],
                "moisture": [10.1, 10.4, 10.8],
            },
        ),
        target_context=TargetContext(
            target_type="continuous",
            target_name="moisture",
            target_names=["moisture"],
            target_units="%",
        ),
    )
    dataset.meta["source_collection"] = {
        "scientific_collection_sha256": "a" * 64,
        "manifest_digest": "b" * 64,
    }
    return dataset


def test_target_authority_is_one_closed_canonical_value() -> None:
    authority = issue_target_authority(
        _dataset(),
        column="moisture",
        target_type="continuous",
    )

    assert authority.canonical_dict() == {
        "schema_version": "spectrasherpa-target-authority/1",
        "column": "moisture",
        "target_type": "continuous",
        "units": "%",
        "source_digest": "a" * 64,
    }
    assert admit_target_authority(authority.canonical_dict(), optional=False) == authority


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"column": " moisture"}, "canonical text"),
        ({"target_type": "numeric"}, "literal_error"),
        ({"source_digest": "A" * 64}, "lowercase SHA-256"),
        ({"extra": "repair-me"}, "extra_forbidden"),
    ],
)
def test_target_authority_refuses_loose_or_partial_dialects(update: dict[str, str], message: str) -> None:
    payload = {
        "schema_version": "spectrasherpa-target-authority/1",
        "column": "moisture",
        "target_type": "continuous",
        "units": "%",
        "source_digest": "a" * 64,
        **update,
    }
    with pytest.raises((ValueError, ValidationError), match=message):
        admit_target_authority(payload, optional=False)


def test_target_authority_refuses_source_or_unit_drift() -> None:
    dataset = _dataset()
    authority = issue_target_authority(dataset, column="moisture", target_type="continuous")

    dataset.meta["source_collection"]["scientific_collection_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="does not match"):
        verify_target_authority(dataset, authority)

    dataset.meta["source_collection"]["scientific_collection_sha256"] = "a" * 64
    dataset.target_context = dataset.target_context.model_copy(update={"target_units": "fraction"})
    with pytest.raises(ValueError, match="does not match"):
        verify_target_authority(dataset, authority)


def test_target_context_preserves_selected_authority() -> None:
    authority = TargetAuthority(
        column="moisture",
        target_type="continuous",
        units="%",
        source_digest="a" * 64,
    )
    context = TargetContext(
        target_type="continuous",
        target_name="moisture",
        target_names=["moisture"],
        target_units="%",
        selected_target="moisture",
        selected_authority=authority,
    )

    assert context.model_dump(mode="json")["selected_authority"] == authority.canonical_dict()
