from __future__ import annotations

import pytest

from spectra_sherpa.app.services.plate_formats import (
    DEFAULT_PLATE_FORMAT_ID,
    PLATE_FORMAT_REGISTRY_SCHEMA,
    PLATE_FORMATS,
    get_plate_format,
    infer_legacy_plate_format,
)


def test_registry_publishes_only_the_qualified_96_well_format() -> None:
    assert PLATE_FORMAT_REGISTRY_SCHEMA == "spectrasherpa.plate-formats/1"
    assert DEFAULT_PLATE_FORMAT_ID == "plate-96"
    assert set(PLATE_FORMATS) == {"plate-96"}
    plate = get_plate_format("plate-96")
    assert plate.label == "96-well plate"
    assert plate.capacity == 96
    assert (plate.first_well, plate.last_well) == ("A01", "H12")
    assert plate.parse_well("h12") == (7, 11)


def test_registry_rejects_unqualified_formats_and_validates_legacy_against_only_format() -> None:
    with pytest.raises(ValueError, match="Unknown plate format"):
        get_plate_format("plate-384")
    with pytest.raises(ValueError, match="outside 96-well plate"):
        get_plate_format("plate-96").parse_well("A13")
    assert infer_legacy_plate_format(["Z99"]).id == "plate-96"
