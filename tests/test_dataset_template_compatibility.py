from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.lib.dataset_compatibility import (
    analysis_profile_from_dataset,
    build_compatibility_matrix,
    build_dataset_analysis_readiness,
    evaluate_template_compatibility,
    normalize_analysis_profile,
)
from spectra_sherpa.app.lib.reference_artifacts import (
    builtin_dataset_catalog,
    model_neutral_dataset_catalog,
    registered_reference_catalog,
)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.modeling.efa_nodes import _efa_numeric_outputs


def _templates() -> dict[str, dict]:
    return {template["slug"]: template for template in TemplateLoader().load_all()}


def _profile(*, target_type: str | None, target_fields: list[str]) -> dict:
    return {
        "primary_role": "X_spectra",
        "modality": "spectra",
        "technique": "FTIR",
        "target_type": target_type,
        "target_fields": target_fields,
        "identity_fields": ["sample_id"],
        "group_fields": ["specimen_id"],
        "ordered_samples": False,
    }


def test_analysis_profile_is_closed_and_role_modality_consistent() -> None:
    profile = _profile(target_type="categorical", target_fields=["botanical_group"])

    assert normalize_analysis_profile(profile) == profile
    with pytest.raises(ValueError, match="fields differ"):
        normalize_analysis_profile({**profile, "supports": ["classification"]})
    with pytest.raises(ValueError, match="role and modality disagree"):
        normalize_analysis_profile({**profile, "modality": "features"})


def test_runtime_group_fields_require_multiple_levels_and_cannot_repeat_target() -> None:
    dataset = SimpleNamespace(
        data_role="X_spectra",
        target_context=SimpleNamespace(
            target_type="categorical",
            target_names=["specimen_id"],
            target_name="specimen_id",
        ),
        sample_axis=SimpleNamespace(
            classes=None,
            sample_table={
                "sample_id": ["s1", "s2", "s3"],
                "specimen_id": ["ESL", "ELF", "ELS"],
                "block": [1, 1, 1],
                "batch": ["A", "A", "B"],
                "group": [None, "", None],
            },
        ),
        domain=SimpleNamespace(technique="FTIR"),
        is_time_series=False,
    )

    profile = analysis_profile_from_dataset(dataset)

    assert profile["identity_fields"] == ["sample_id", "specimen_id"]
    assert profile["group_fields"] == ["batch"]


def test_technique_mismatch_is_an_advisory_not_an_admission_reason() -> None:
    templates = _templates()
    profile = {**_profile(target_type=None, target_fields=[]), "technique": "Customer-defined LIBS variant"}

    decision = evaluate_template_compatibility(profile, templates["emsc_reference_correction"])

    assert decision["scope"] == "structural"
    assert decision["technique_recommended"] is False
    assert decision["advisory_codes"] == ["technique_not_recommended"]
    assert decision["advisories"][0]["code"] == "technique_not_recommended"
    assert "technique_not_recommended" not in decision["reason_codes"]


def test_raman_processing_requires_raman_technique() -> None:
    template = _templates()["raman_processing"]

    wrong_technique = evaluate_template_compatibility(
        _profile(target_type=None, target_fields=[]),
        template,
    )
    raman = evaluate_template_compatibility(
        {**_profile(target_type=None, target_fields=[]), "technique": "Raman"},
        template,
    )

    assert wrong_technique["status"] == "incompatible"
    assert wrong_technique["reason_codes"] == ["technique_incompatible"]
    assert wrong_technique["advisory_codes"] == []
    assert wrong_technique["can_use_as_primary"] is False
    assert raman["status"] == "compatible"


def test_runtime_readiness_names_every_available_analysis_and_splits_missing_inputs() -> None:
    dataset = SimpleNamespace(
        data_role="X_spectra",
        target_context=None,
        sample_axis=SimpleNamespace(classes=None, sample_table={"sample_id": ["s1", "s2"]}),
        domain=SimpleNamespace(technique="FTIR"),
        is_time_series=False,
    )

    readiness = build_dataset_analysis_readiness(dataset, TemplateLoader().load_all())

    assert readiness["scope"] == "structural"
    expected_count = len(TemplateLoader().load_all())
    assert readiness["template_count"] == expected_count
    assert sum(readiness["counts"].values()) == expected_count
    assert readiness["counts"]["compatible"] > 0
    assert readiness["counts"]["needs_target"] > 0
    assert all(item["template_name"] for item in readiness["decisions"])
    assert {
        item["display_status"]
        for item in readiness["decisions"]
        if item["status"] == "needs_input" and any(code.endswith("_target_missing") for code in item["reason_codes"])
    } == {"needs_target"}


@pytest.mark.parametrize(
    "target_context",
    [
        SimpleNamespace(target_type=None, target_names=["Moisture"], target_name="Moisture"),
        SimpleNamespace(
            target_type="continuous",
            target_names=["Moisture", " Moisture "],
            target_name="Moisture",
        ),
    ],
)
def test_incomplete_target_metadata_degrades_readiness_without_aborting_preview(target_context) -> None:
    dataset = SimpleNamespace(
        data_role="X_spectra",
        target_context=target_context,
        sample_axis=SimpleNamespace(classes=None, sample_table={"sample_id": ["s1", "s2"]}),
        domain=SimpleNamespace(technique="NIR"),
        is_time_series=False,
    )

    readiness = build_dataset_analysis_readiness(dataset, TemplateLoader().load_all())

    assert readiness["status"] == "unavailable"
    assert readiness["profile"] is None
    assert readiness["template_count"] == 0
    assert readiness["diagnostics"][0]["code"] == "analysis_profile_incomplete"


def test_one_malformed_template_is_isolated_from_other_readiness_decisions() -> None:
    dataset = SimpleNamespace(
        data_role="X_spectra",
        target_context=None,
        sample_axis=SimpleNamespace(classes=None, sample_table={"sample_id": ["s1", "s2"]}),
        domain=SimpleNamespace(technique="FTIR"),
        is_time_series=False,
    )
    [valid, *rest] = TemplateLoader().load_all()
    malformed = {**valid, "slug": "malformed", "name": "Malformed", "template_data": {"status": "invented"}}

    readiness = build_dataset_analysis_readiness(dataset, [malformed, *rest])

    assert readiness["status"] == "partial"
    assert readiness["counts"]["unavailable"] == 1
    assert readiness["diagnostics"][0]["code"] == "template_contract_invalid"
    assert len(readiness["decisions"]) == len(rest)


def test_same_generic_categorical_profile_enables_classification_and_pca() -> None:
    templates = _templates()
    lavender = _profile(target_type="categorical", target_fields=["claimed_botanical_group"])

    plsda = evaluate_template_compatibility(lavender, templates["classification_plsda"])
    pca = evaluate_template_compatibility(lavender, templates["pca"])
    regression = evaluate_template_compatibility(lavender, templates["pls_calibration"])

    assert plsda["status"] == "compatible"
    assert pca["status"] == "compatible"
    assert regression["status"] == "needs_input"
    assert regression["reason_codes"] == ["continuous_target_missing"]


def test_distributed_lavender_declares_the_same_generic_categorical_profile() -> None:
    [lavender] = builtin_dataset_catalog()

    assert lavender["dataset_id"] == "builtin:lavender-essential-oil-v1"
    profile = lavender["analysis_profile"]
    assert profile["target_type"] == "categorical"
    assert profile["target_fields"] == [
        "specimen_id",
        "claimed_botanical_group",
        "author_reported_authenticity_status",
    ]
    assert profile["identity_fields"] == ["sample_id", "specimen_id"]
    assert profile["group_fields"] == ["block"]


def test_registered_continuous_and_target_free_profiles_have_explicit_results() -> None:
    templates = _templates()
    catalog = {item["name"]: item for item in registered_reference_catalog()}
    corn = catalog["public-corn-m5-moisture-v1"]["analysis_profile"]
    oes = catalog["public-metal-etch-oes-v1"]["analysis_profile"]

    assert evaluate_template_compatibility(corn, templates["pls_calibration"])["status"] == "compatible"
    assert evaluate_template_compatibility(corn, templates["classification_plsda"])["reason_codes"] == [
        "categorical_target_missing"
    ]
    assert evaluate_template_compatibility(oes, templates["pca"])["status"] == "compatible"
    assert evaluate_template_compatibility(oes, templates["pls_calibration"])["reason_codes"] == [
        "continuous_target_missing"
    ]


def test_hyperspectral_pixel_tables_have_an_exclusion_aware_pca_path() -> None:
    templates = _templates()
    catalog = {item["name"]: item for item in registered_reference_catalog()}
    pca = templates["pca"]

    for projection_id in ("public-art-image-paint-demo-v1", "public-iasim16-test1-v1"):
        decision = evaluate_template_compatibility(catalog[projection_id]["analysis_profile"], pca)
        assert decision["status"] == "compatible"

    nodes = {node["node_id"]: node for node in pca["template_data"]["nodes"]}
    assert nodes["inclusion_1"]["node_type"] == "data.filter_samples"
    assert nodes["inclusion_1"]["parameters"]["field"] == "source_inclusion"
    assert any(
        edge["from_node_id"] == "inclusion_1" and edge["to_node_id"] == "preprocess_1"
        for edge in pca["template_data"]["edges"]
    )


def test_parafac_starter_is_reachable_only_for_multiway_hyperspectral_data() -> None:
    templates = _templates()
    catalog = {item["name"]: item for item in registered_reference_catalog()}
    parafac = templates["parafac_multiway"]

    assert parafac["template_data"]["status"] == "ready"
    assert parafac["template_data"]["data_modalities"] == ["hsi"]
    assert {node["node_type"] for node in parafac["template_data"]["nodes"]} == {
        "data.file_load",
        "model.parafac",
        "output.plot",
        "stats.summary",
    }
    assert parafac["template_data"]["data_roles"]["X_hsi"]["accepted_data_roles"] == ["X_hsi"]

    for projection_id in ("public-art-image-paint-demo-v1", "public-iasim16-test1-v1"):
        decision = evaluate_template_compatibility(catalog[projection_id]["analysis_profile"], parafac)
        assert decision["status"] == "compatible"

    for projection_id in ("public-corn-m5-moisture-v1", "public-metal-etch-oes-v1"):
        decision = evaluate_template_compatibility(catalog[projection_id]["analysis_profile"], parafac)
        assert decision["status"] == "incompatible"
        assert decision["reason_codes"] == ["data_role_incompatible"]


def test_efa_requires_declared_sample_order_in_catalog_and_runtime_profiles() -> None:
    template = _templates()["efa_analysis"]
    unordered = _profile(target_type=None, target_fields=[])
    ordered = {**unordered, "ordered_samples": True}

    refused = evaluate_template_compatibility(unordered, template)
    admitted = evaluate_template_compatibility(ordered, template)

    assert refused["status"] == "needs_input"
    assert refused["reason_codes"] == ["ordered_samples_required"]
    assert "arbitrary sample order" in refused["reasons"][0]["message"]
    assert admitted["status"] == "compatible"


def test_efa_execution_refuses_arbitrary_sample_order_before_loading_optional_runtime() -> None:
    dataset = SherpaDataset(X=np.ones((4, 3)), is_time_series=False)

    with pytest.raises(ValueError, match="explicitly ordered evolution coordinate"):
        _efa_numeric_outputs(dataset, parameters={"n_components": 2})


def test_registered_projection_template_matrix_is_total() -> None:
    templates = TemplateLoader().load_all()
    datasets = [
        {
            "dataset_id": f"{item['source']}:{item['name']}",
            "analysis_profile": item["analysis_profile"],
        }
        for item in model_neutral_dataset_catalog()
    ]

    matrix = build_compatibility_matrix(datasets, templates)

    assert [item["dataset_id"] for item in datasets] == [
        "builtin:lavender-essential-oil-v1",
        "synthetic:Synthetic_atmospheric-6",
        "synthetic:Library_atmospheric-9",
        "synthetic:msc_application_spectra",
        "synthetic:msc_reference_spectra",
        "sklearn:iris",
        "sklearn:wine",
        "sklearn:breast_cancer",
        "registered:public-art-image-paint-demo-v1",
        "registered:public-cgl-nir-lactate-v1",
        "registered:public-corn-m5-moisture-v1",
        "registered:public-corn-mp5-moisture-v1",
        "registered:public-corn-mp6-moisture-v1",
        "registered:public-diesel-d4052-v1",
        "registered:public-diesel-high-level-d4052-v1",
        "registered:public-diesel-low-level-b-d4052-v1",
        "registered:public-iasim16-test1-v1",
        "registered:public-metal-etch-machine-v1",
        "registered:public-metal-etch-oes-v1",
        "registered:public-metal-etch-rfm-v1",
        "registered:public-nir-shootout-cal1-assay-v1",
        "registered:public-nir-shootout-cal2-assay-v1",
        "registered:public-nir-shootout-test1-assay-v1",
        "registered:public-nir-shootout-test2-assay-v1",
        "registered:public-nir-shootout-validation1-assay-v1",
        "registered:public-nir-shootout-validation2-assay-v1",
    ]
    assert len(templates) == 34
    assert len(matrix) == 884
    assert len({(item["dataset_id"], item["template_slug"]) for item in matrix}) == 884
    assert Counter(item["status"] for item in matrix) == {
        "compatible": 327,
        "needs_input": 254,
        "incompatible": 199,
        "pending": 104,
    }
    assert all(item["status"] in {"compatible", "needs_input", "incompatible", "pending"} for item in matrix)
    assert all(item["status"] == "compatible" or item["reason_codes"] for item in matrix)
    assert not any("unsupported_template_requirement" in item["reason_codes"] for item in matrix)


def test_family_leader_interaction_matrix_is_total() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    specification = json.loads(
        (repository_root / "docs/evidence/chemometric-interaction-qualification-matrix.json").read_text(
            encoding="utf-8"
        )
    )
    templates = _templates()
    datasets = [
        {
            "dataset_id": f"{item['source']}:{item['name']}",
            "analysis_profile": item["analysis_profile"],
        }
        for item in model_neutral_dataset_catalog()
    ]
    leaders = specification["column_axis"]["family_leaders"]
    equivalence_classes = specification["row_axis"]["equivalence_classes"]
    classified_datasets = [
        dataset_id for equivalence_class in equivalence_classes for dataset_id in equivalence_class["datasets"]
    ]

    assert specification["schema_version"] == "spectrasherpa-chemometric-interaction-qualification/3"
    assert specification["row_axis"]["datasets"] == [item["dataset_id"] for item in datasets]
    assert [item["step"] for item in specification["row_axis"]["method"]] == [
        "identify",
        "materialize",
        "preserve_rows",
        "bind_meaning",
        "classify",
        "reinspect",
    ]
    assert Counter(classified_datasets) == Counter(specification["row_axis"]["datasets"])
    assert len(classified_datasets) == len(set(classified_datasets))
    assert all(
        item["live_representative"] is None or item["live_representative"] in item["datasets"]
        for item in equivalence_classes
    )
    assert len(specification["cell_gates"]) == 6
    assert len(specification["column_axis"]["method"]) == 5
    assert len({item["family"] for item in leaders}) == len(leaders) == 7
    assert all(item["template_slug"] in templates for item in leaders)
    assert all(item["input_contract"] for item in leaders)
    assert all(len(item["result_contract"]) >= 4 for item in leaders)
    assert all(len(item["quality_checks"]) >= 3 for item in leaders)
    assert set(specification["evidence_policy"]) == {
        "exact_cell",
        "live_representative",
        "private_source",
        "optional_runtime",
        "failure",
        "supplemental_method",
    }
    assert all(
        observation["dataset_id"] in specification["row_axis"]["datasets"]
        and observation["family"] in {item["family"] for item in leaders}
        and observation["status"] == "passed"
        for observation in specification["live_observations"]
    )
    assert all(
        observation["family"] in {item["family"] for item in leaders}
        and observation["status"] == "unavailable"
        and observation["reason"]
        for observation in specification["runtime_observations"]
    )
    assert all(
        observation["dataset_id"] in specification["row_axis"]["datasets"]
        and observation["family"] in {item["family"] for item in leaders}
        and observation["method_slug"] in templates
        and observation["status"] == "passed"
        and observation["leader_substitute"] is False
        for observation in specification["supplemental_live_observations"]
    )

    cells = [
        {
            "dataset_id": dataset["dataset_id"],
            "family": leader["family"],
            **evaluate_template_compatibility(
                dataset["analysis_profile"],
                templates[leader["template_slug"]],
            ),
        }
        for dataset in datasets
        for leader in leaders
    ]

    assert len(cells) == 26 * 7
    assert len({(item["dataset_id"], item["family"]) for item in cells}) == len(cells)
    assert all(item["status"] == "compatible" or item["reason_codes"] for item in cells)
    assert all(item["status"] == "compatible" for item in cells if item["family"] == "exploratory")

    structural_matrix = {item["row"]: item for item in specification["structural_matrix"]}
    assert set(structural_matrix) == {item["class"] for item in equivalence_classes}
    assert all(set(item) == {"row", *(leader["family"] for leader in leaders)} for item in structural_matrix.values())
    for equivalence_class in equivalence_classes:
        row = structural_matrix[equivalence_class["class"]]
        for leader in leaders:
            statuses = {
                item["status"]
                for item in cells
                if item["dataset_id"] in equivalence_class["datasets"] and item["family"] == leader["family"]
            }
            assert statuses == {row[leader["family"]]}

    qualification_matrix = {item["row"]: item for item in specification["qualification_matrix"]}
    assert set(qualification_matrix) == {item["class"] for item in equivalence_classes}
    assert all(
        set(item) == {"row", *(leader["family"] for leader in leaders)} for item in qualification_matrix.values()
    )
    qualification_states = set(specification["qualification_matrix_policy"])
    assert qualification_states == {
        "passed",
        "pending_live",
        "needs_input",
        "incompatible",
        "runtime_unavailable",
    }
    for equivalence_class in equivalence_classes:
        compatibility_row = structural_matrix[equivalence_class["class"]]
        qualification_row = qualification_matrix[equivalence_class["class"]]
        for leader in leaders:
            family = leader["family"]
            qualification = qualification_row[family]
            assert qualification in qualification_states
            if compatibility_row[family] in {"needs_input", "incompatible"}:
                assert qualification == compatibility_row[family]
            else:
                assert qualification in {"passed", "pending_live", "runtime_unavailable"}
