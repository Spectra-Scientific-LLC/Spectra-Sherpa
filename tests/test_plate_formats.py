from __future__ import annotations

import pytest

from spectra_sherpa.app.services.plate_formats import (
    DEFAULT_PLATE_FORMAT_ID,
    PLATE_FORMAT_REGISTRY_SCHEMA,
    PLATE_FORMATS,
    get_plate_format,
    infer_legacy_plate_format,
)


@pytest.mark.parametrize(
    "capacity,rows,columns,last",
    [
        (6, 2, 3, "B03"),
        (12, 3, 4, "C04"),
        (24, 4, 6, "D06"),
        (48, 6, 8, "F08"),
        (96, 8, 12, "H12"),
        (384, 16, 24, "P24"),
        (1536, 32, 48, "AF48"),
    ],
)
def test_registry_publishes_explicit_plate_formats(capacity, rows, columns, last) -> None:
    assert PLATE_FORMAT_REGISTRY_SCHEMA == "spectrasherpa.plate-formats/1"
    assert DEFAULT_PLATE_FORMAT_ID == "plate-96"
    assert set(PLATE_FORMATS) == {f"plate-{n}" for n in [6, 12, 24, 48, 96, 384, 1536]}
    plate = get_plate_format(f"plate-{capacity}")
    assert plate.label == f"{capacity}-well plate"
    assert plate.capacity == capacity
    assert (len(plate.rows), plate.columns) == (rows, columns)
    assert (plate.first_well, plate.last_well) == ("A01", last)
    assert plate.parse_well(last.lower()) == (rows - 1, columns - 1)

    from spectra_sherpa.app.services.acquisition_plans import canonicalize_acquisition_plan

    wells = [plate.format_well(r, c) for r in range(rows) for c in range(columns)]
    document = canonicalize_acquisition_plan(
        {"plate_format_id": plate.id, "wells": [{"well_position": w} for w in reversed(wells)]}
    )
    assert [w["well_position"] for w in document["wells"]] == wells


def test_registry_rejects_unqualified_formats_and_validates_legacy_against_only_format() -> None:
    with pytest.raises(ValueError, match="Unknown plate format"):
        get_plate_format("plate-72")
    with pytest.raises(ValueError, match="outside 96-well plate"):
        get_plate_format("plate-96").parse_well("A13")
    assert infer_legacy_plate_format(["A01", "H12"]).id == "plate-96"
    with pytest.raises(ValueError, match="outside 96-well plate"):
        infer_legacy_plate_format(["Z99"])


def test_api_plate_enum_and_limit_are_derived_from_registry():
    from spectra_sherpa.app.schemas.acquisition_plans import AcquisitionPlanDocument, WorkbenchPreferencesUpdate

    schema = AcquisitionPlanDocument.model_json_schema()
    assert set(schema["$defs"]["PlateFormatId"]["enum"]) == set(PLATE_FORMATS)
    assert schema["properties"]["wells"]["maxItems"] == 1536
    for format_id in PLATE_FORMATS:
        assert WorkbenchPreferencesUpdate(default_plate_format_id=format_id).model_dump(mode="json") == {
            "default_plate_format_id": format_id
        }


def test_legacy_error_reports_original_row_including_unassigned_rows():
    from spectra_sherpa.app.services.dag.nodes.data.sample_table import _validate_plate_well_coordinates

    with pytest.raises(ValueError, match="Sample table.*row 3.*outside 96-well plate"):
        _validate_plate_well_coordinates(
            ["", "p1", "p1"], ["", "A01", "H13"], format_values=None, row_prefix="Sample table"
        )


@pytest.mark.parametrize("format_id", list(PLATE_FORMATS))
def test_sample_table_coordinates_preserve_explicit_format(format_id):
    from spectra_sherpa.app.services.dag.nodes.data.sample_table import _validate_plate_well_coordinates

    plate = get_plate_format(format_id)
    positions = [plate.first_well, plate.last_well]
    wells, formats = _validate_plate_well_coordinates(
        ["p1", "p1"], positions, format_values=[format_id, format_id], row_prefix="Sample table"
    )
    assert wells == positions
    assert formats == [format_id, format_id]
