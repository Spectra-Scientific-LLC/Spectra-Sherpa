from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spectra_sherpa.app.lib.reference_artifacts import (
    ReferenceArtifactRegistryError,
    registered_reference_catalog,
)
from spectra_sherpa.app.lib.reference_dataset_packages import (
    REFERENCE_DATASET_PACKAGES_PATH,
    load_reference_dataset_package_registry,
    package_import_projection,
    package_view_projection,
    reference_dataset_package_registry_digest,
)


def _payload() -> dict:
    return json.loads(REFERENCE_DATASET_PACKAGES_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "packages.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_corn_is_one_package_with_three_target_neutral_views() -> None:
    package = load_reference_dataset_package_registry().package("eigenvector-corn-v1").as_dict()

    assert package["artifact_ids"] == ["eigenvector-corn-archive-v1"]
    assert package["initial_view_ids"] == ["corn-m5"]
    assert [view["view_id"] for view in package["views"]] == ["corn-m5", "corn-mp5", "corn-mp6"]
    assert [view["instrument"] for view in package["views"]] == ["M5", "MP5", "MP6"]
    assert all("Moisture" not in view["view_id"] for view in package["views"])
    assert package["relations"] == [
        {
            "relation_id": "corn-instrument-views",
            "relation_type": "same_specimens_aligned",
            "view_ids": ["corn-m5", "corn-mp5", "corn-mp6"],
            "row_identity": "source_row_index",
        }
    ]


def test_package_view_projection_marks_only_m5_initially_selected() -> None:
    m5 = package_view_projection("public-corn-m5-moisture-v1")
    mp5 = package_view_projection("public-corn-mp5-moisture-v1")

    assert m5 is not None and m5["package_id"] == "eigenvector-corn-v1"
    assert m5["view_id"] == "corn-m5"
    assert m5["initially_selected"] is True
    assert mp5 is not None and mp5["view_id"] == "corn-mp5"
    assert mp5["initially_selected"] is False
    cgl = package_view_projection("public-cgl-nir-lactate-v1")
    assert cgl is not None and cgl["package_id"] == "eigenvector-cgl-nir-v1"


def test_every_qualified_projection_belongs_to_exactly_one_package() -> None:
    from spectra_sherpa.app.lib.reference_artifacts import load_reference_artifact_registry

    artifacts = load_reference_artifact_registry()
    packages = load_reference_dataset_package_registry(artifact_registry=artifacts)
    package_projection_ids = [
        view["projection_id"] for package in packages.packages for view in package.as_dict()["views"]
    ]

    assert sorted(package_projection_ids) == sorted(projection.projection_id for projection in artifacts.projections)
    assert len(package_projection_ids) == len(set(package_projection_ids))


def test_hyperspectral_artifacts_are_explicit_single_view_packages() -> None:
    registry = load_reference_dataset_package_registry()

    for package_id, projection_id in (
        ("eigenvector-art-image-demo-v1", "public-art-image-paint-demo-v1"),
        ("eigenvector-iasim16-test1-v1", "public-iasim16-test1-v1"),
    ):
        package = registry.package(package_id).as_dict()
        assert package["assembly_mode"] == "single_view"
        assert package["annotation_tables"] == []
        assert package["relations"] == []
        assert [view["projection_id"] for view in package["views"]] == [projection_id]


def test_legacy_eigenvector_loader_derives_scientific_metadata_from_packages() -> None:
    from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG

    assert DATASET_CATALOG["cgl_nir"]["prop_names"] == [
        "Casein (wt %)",
        "Glucose (wt %)",
        "Lactate (wt %)",
        "Moisture (wt %)",
    ]
    assert DATASET_CATALOG["nir_shootout_cal1"]["prop_names"] == ["Weight", "Hardness", "Assay"]
    assert DATASET_CATALOG["nir_shootout_cal1"]["label"] == (
        "Eigenvector NIR Shootout 2002 — Calibration — instrument 1"
    )
    assert "assay" not in DATASET_CATALOG["nir_shootout_cal1"]["label"].lower()
    assert DATASET_CATALOG["corn_m5"]["x_title"] == "Wavelength"
    assert DATASET_CATALOG["corn_m5"]["x_units"] == "nm"
    assert DATASET_CATALOG["corn_m5"]["n_samples"] == 80
    assert DATASET_CATALOG["corn_m5"]["n_features"] == 700
    assert "per-wafer time averages" in DATASET_CATALOG["metal_etch_oes"]["description"]


def test_all_shootout_package_view_labels_are_target_neutral() -> None:
    package = load_reference_dataset_package_registry().package("eigenvector-nir-shootout-v1").as_dict()

    assert len(package["views"]) == 6
    assert all("assay" not in view["label"].lower() for view in package["views"])


def test_cgl_package_retains_all_measured_properties_without_imposing_its_source_partition() -> None:
    package = load_reference_dataset_package_registry().package("eigenvector-cgl-nir-v1").as_dict()

    assert package["initial_view_ids"] == ["cgl-spectra"]
    assert [field["name"] for field in package["annotation_tables"][0]["fields"]] == [
        "Casein (wt %)",
        "Glucose (wt %)",
        "Lactate (wt %)",
        "Moisture (wt %)",
    ]
    assert package["relations"] == []


def test_package_import_projection_returns_all_corn_views_without_selecting_a_target() -> None:
    package = package_import_projection("eigenvector-corn-v1")

    assert package["initial_view_ids"] == ["corn-m5"]
    assert [view["projection_id"] for view in package["views"]] == [
        "public-corn-m5-moisture-v1",
        "public-corn-mp5-moisture-v1",
        "public-corn-mp6-moisture-v1",
    ]
    assert [field["name"] for field in package["annotation_tables"][0]["fields"]] == [
        "Moisture",
        "Oil",
        "Protein",
        "Starch",
    ]


def test_diesel_is_one_package_with_all_three_source_cohorts() -> None:
    package = load_reference_dataset_package_registry().package("eigenvector-diesel-d4052-v1").as_dict()

    assert package["artifact_ids"] == ["eigenvector-diesel-d4052-archive-v1"]
    assert package["initial_view_ids"] == ["diesel-low-level-a"]
    assert [view["view_id"] for view in package["views"]] == [
        "diesel-high-level",
        "diesel-low-level-a",
        "diesel-low-level-b",
    ]
    assert [table["n_rows"] for table in package["annotation_tables"]] == [20, 122, 121]
    assert {field["name"] for table in package["annotation_tables"] for field in table["fields"]} == {"D4052 density"}
    assert package["relations"] == [
        {
            "relation_id": "diesel-provider-sets",
            "relation_type": "alignment_unverified",
            "view_ids": ["diesel-high-level", "diesel-low-level-a", "diesel-low-level-b"],
            "row_identity": "provider row order within each set; cross-set specimen alignment is not asserted",
        }
    ]

    for projection_id in (
        "public-diesel-high-level-d4052-v1",
        "public-diesel-d4052-v1",
        "public-diesel-low-level-b-d4052-v1",
    ):
        view = package_view_projection(projection_id)
        assert view is not None
        assert view["relations"][0]["relation_type"] == "alignment_unverified"


def test_registered_catalog_exposes_package_without_changing_admission_identity() -> None:
    corn = [
        item
        for item in registered_reference_catalog()
        if item.get("dataset_package", {}).get("package_id") == "eigenvector-corn-v1"
    ]

    assert [item["name"] for item in corn] == [
        "public-corn-m5-moisture-v1",
        "public-corn-mp5-moisture-v1",
        "public-corn-mp6-moisture-v1",
    ]
    assert {item["dataset_package"]["package_id"] for item in corn} == {"eigenvector-corn-v1"}
    assert {item["expected_size_bytes"] for item in corn} == {1_094_488}


def test_package_registry_digest_is_canonical() -> None:
    payload = _payload()
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert reference_dataset_package_registry_digest() == expected


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["packages"][0].update(artifact_ids=["missing"]), "unknown artifact"),
        (lambda p: p["packages"][0].update(initial_view_ids=["corn-missing"]), "subset"),
        (
            lambda p: p["packages"][0]["views"][0].update(projection_id="missing"),
            "unknown reference projection",
        ),
        (
            lambda p: p["packages"][2]["relations"][0].update(relation_type="looks_similar"),
            "unsupported",
        ),
        (
            lambda p: p["packages"][2]["relations"][0].update(view_ids=["corn-m5"]),
            "at least two",
        ),
        (
            lambda p: p["packages"][1]["annotation_tables"][0].update(object_name="wrong_target"),
            "annotation object disagrees",
        ),
        (
            lambda p: p["packages"][1]["annotation_tables"][0].update(n_rows=999),
            "annotation rows disagree",
        ),
        (
            lambda p: p["packages"][1]["annotation_tables"][0]["fields"][2].update(name="Wrong target"),
            "annotation target disagrees",
        ),
        (
            lambda p: p["packages"][1]["annotation_tables"][0]["fields"][2].update(target_type="categorical"),
            "annotation target disagrees",
        ),
        (lambda p: p["packages"].pop(), "do not account for projection"),
    ],
)
def test_package_registry_refuses_unresolved_or_ambiguous_relationships(tmp_path: Path, mutate, message: str) -> None:
    payload = _payload()
    mutate(payload)
    with pytest.raises(ReferenceArtifactRegistryError, match=message):
        load_reference_dataset_package_registry(_write(tmp_path, payload))
