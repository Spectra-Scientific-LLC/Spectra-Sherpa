from __future__ import annotations

import pytest

from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext
from spectra_sherpa.core.dimension_roles import DimensionRole, canonical_dimension_role


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("samples", DimensionRole.SAMPLE),
        ("features", DimensionRole.FEATURE),
        ("mode-2", DimensionRole.INNER),
        ("inner-0", DimensionRole.INNER),
        ("spatial-1", DimensionRole.SPATIAL_COORDINATE),
        ("image-row", DimensionRole.SPATIAL_Y),
    ],
)
def test_source_role_aliases_project_to_closed_vocabulary(source: str, expected: DimensionRole) -> None:
    assert canonical_dimension_role(source) is expected


def test_dataset_layout_refuses_open_ended_dimension_role() -> None:
    with pytest.raises(ValueError, match="unsupported dimension role"):
        DatasetLayoutContext(source_shape=(2, 3), mode_roles=("sample", "vendor-secret-axis"))


def test_dataset_layout_serializes_only_canonical_roles() -> None:
    layout = DatasetLayoutContext(
        source_shape=(2, 3, 4),
        mode_roles=("samples", "mode-2", "features"),
    )

    assert layout.mode_roles == (DimensionRole.SAMPLE, DimensionRole.INNER, DimensionRole.FEATURE)
    assert layout.model_dump(mode="json")["mode_roles"] == ["sample", "inner", "feature"]
