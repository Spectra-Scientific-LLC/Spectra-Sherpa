"""Keep the curated node repair map complete, honest, and reproducible."""

from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import yaml

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MAP_PATH = _REPOSITORY_ROOT / "docs/evidence/canonical-node-project-repair-map.json"
_CENSUS_PATH = _REPOSITORY_ROOT / "docs/evidence/m4-node-contract-census.json"
_ATTESTATION_PATH = _REPOSITORY_ROOT / "docs/evidence/managed-optimization-runtime-attestation.json"
_PLAN_PATH = _REPOSITORY_ROOT / "docs/plan/canonical-dag-managed-optimization-plan.md"
_RETENTION_PATH = _REPOSITORY_ROOT / "docs/plan/canonical-node-retention-decisions.json"
_GENERATOR_PATH = _REPOSITORY_ROOT / "packages/spectra-sherpa/tools/generate_canonical_node_project_map.py"
_TEMPLATE_DIR = _REPOSITORY_ROOT / "packages/spectra-sherpa/src/spectra_sherpa/data/templates"
_SCHEMA_VERSION = "spectrasherpa-canonical-node-project-map/4"
_RETIRED_SUCCESSORS = {
    "analysis.peak_id": (("governed_advisor_action", "sherpa_identify_peaks"),),
    "classification.predict": (
        ("canonical_node", "classification.apply_knn"),
        ("canonical_node", "classification.apply_plsda"),
        ("canonical_node", "classification.apply_simca"),
    ),
    "data.my_dataset": (("canonical_node", "data.file_load"),),
    "data.source": (("canonical_node", "data.file_load"),),
    "diagnostics.holdout_evaluation": (("canonical_node", "diagnostics.regression_evaluator"),),
    "model.pls": (("canonical_node", "model.fitted_pls"),),
    "model.pls_predict": (("canonical_node", "model.apply_fitted_pls"),),
    "selection.sample_partition": (("canonical_node", "data.train_test_split"),),
    "selection.uve": (("canonical_node", "selection.mcuve"),),
    "transfer.sbc": (
        ("canonical_node", "transfer.apply_fitted"),
        ("canonical_node", "transfer.ds"),
        ("canonical_node", "transfer.pds"),
        ("canonical_node", "transfer.sws"),
    ),
}
_TEMPLATE_PROOF_STATES = {
    "explicit_ready_intent",
    "pending_data_intent",
    "pending_qualification_intent",
    "intent_only_wip",
}


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _template_nodes() -> tuple[dict[str, set[str]], dict[str, str]]:
    nodes: dict[str, set[str]] = {}
    statuses: dict[str, str] = {}
    for path in sorted(_TEMPLATE_DIR.glob("*.yaml")):
        if path.name == "_categories.yaml":
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        slug = str(document["slug"])
        nodes[slug] = {str(node["node_type"]) for node in document["template_data"]["nodes"]}
        raw_status = document.get("status")
        assert raw_status in {"ready", "pending_data", "pending_qualification", "wip"}
        statuses[slug] = raw_status
    return nodes, statuses


def test_checked_map_is_the_deterministic_generator_output() -> None:
    result = subprocess.run(
        [sys.executable, str(_GENERATOR_PATH), "--check"],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_generator_serializes_repository_paths_independently_of_host_os() -> None:
    generator = runpy.run_path(str(_GENERATOR_PATH))
    serialize = generator["_repository_relative_path"]

    repository_root = PureWindowsPath(r"D:\a\spectra\spectra")
    template_path = repository_root / "packages" / "spectra-sherpa" / "templates" / "example.yaml"

    assert serialize(template_path, repository_root) == "packages/spectra-sherpa/templates/example.yaml"


def test_map_covers_the_exact_curated_registry_after_prototype_removal() -> None:
    document = _load(_MAP_PATH)
    census = _load(_CENSUS_PATH)
    nodes = document["nodes"]
    mapped_types = [node["node_type"] for node in nodes]
    census_types = [node["node_type"] for node in census["nodes"]]
    registered_count = len(census_types)

    assert document["schema_version"] == _SCHEMA_VERSION
    assert document["registry_digest"] == census["registry_digest"]
    assert len(mapped_types) == len(set(mapped_types)) == registered_count
    assert set(mapped_types) == set(census_types)
    decisions = {node["node_type"]: node for node in nodes}
    assert set(decisions).isdisjoint(_RETIRED_SUCCESSORS)
    assert not any(entry["retention_decision"] == "remove_superseded" for entry in nodes)
    assert all(
        entry["retention_decision"] == "retain_and_repair"
        and entry["replacement_node_type"] is None
        and entry["retention_reason"]
        for node_type, entry in decisions.items()
        if node_type not in _RETIRED_SUCCESSORS
    )
    assert document["aggregates"]["retain_and_repair"] == registered_count
    assert document["aggregates"]["remove_superseded"] == 0
    assert document["aggregates"]["repair_required"] == sum(
        not entry["contract_complete"] for entry in nodes if entry["retention_decision"] == "retain_and_repair"
    )
    canonical_replacements = {
        identifier
        for successors in _RETIRED_SUCCESSORS.values()
        for authority_type, identifier in successors
        if authority_type == "canonical_node"
    }
    assert all(
        decisions[replacement]["contract_complete"]
        and decisions[replacement]["retention_decision"] == "retain_and_repair"
        for replacement in canonical_replacements
    )
    assert {node["planned_slice"] for node in nodes} <= {
        "C2f",
        "C2g",
        "C2h",
        "C2i",
        "C2j",
        "C2k",
        "C2l",
        "C2m",
    }

    payload = {key: value for key, value in document.items() if key != "map_digest"}
    assert document["map_digest"] == _canonical_digest(payload)


def test_retention_authority_records_every_node_removed_since_0_5_30() -> None:
    document = _load(_RETENTION_PATH)
    assert document["schema_version"] == "spectrasherpa-canonical-node-retention-decisions/2"
    recorded = {
        entry["node_type"]: tuple(
            (authority["authority_type"], authority["identifier"]) for authority in entry["replacement_authorities"]
        )
        for entry in document["superseded_nodes"]
    }

    assert recorded == _RETIRED_SUCCESSORS

    from spectra_sherpa.app.ws_actions import SHERPA_WS_ACTIONS

    governed_actions = {
        identifier
        for successors in recorded.values()
        for authority_type, identifier in successors
        if authority_type == "governed_advisor_action"
    }
    assert governed_actions <= set(SHERPA_WS_ACTIONS)


def test_template_bindings_distinguish_intent_from_current_execution() -> None:
    document = _load(_MAP_PATH)
    template_nodes, template_statuses = _template_nodes()
    consumer_entries = document["consumers"]
    consumer_ids = [entry["consumer_id"] for entry in consumer_entries]
    assert len(consumer_ids) == len(set(consumer_ids))
    consumers = {entry["consumer_id"]: entry for entry in consumer_entries}
    mapped = {entry["node_type"]: entry for entry in document["nodes"]}
    executed_projects = {
        "bilinear_mixture_synthesis": (
            "tests/test_c2_synthesis_contracts.py::"
            "test_bilinear_mixture_project_executes_explicit_species_merge_and_mixture"
        ),
        "calibration_transfer": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_calibration_transfer_project_fits_and_reuses_three_explicit_states"
        ),
        "clustering_comparison": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_partition_clustering_project_compares_two_canonical_cluster_definitions"
        ),
        "msc_reference_correction": (
            "tests/test_phase1c_consumer_projects.py::test_msc_reference_correction_project_uses_one_frozen_reference"
        ),
        "emsc_reference_correction": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_emsc_reference_correction_project_uses_explicit_fitted_sources"
        ),
        "efa_analysis": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_efa_project_executes_raw_forward_and_reverse_rank_diagnostics"
        ),
        "harmonized_nonnegative_spectra": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_harmonized_nonnegative_project_retains_distinct_preparation_branches"
        ),
        "ica_decomposition": (
            "tests/test_phase1c_consumer_projects.py::test_ica_project_executes_one_seeded_replayable_decomposition"
        ),
        "hierarchical_clustering": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_hierarchical_clustering_project_executes_one_closed_cohort_hierarchy"
        ),
        "knn_classification": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_knn_classification_project_executes_explicit_fit_apply_and_heldout_evaluation"
        ),
        "mcr_als": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_mcr_project_executes_one_replayable_constrained_decomposition"
        ),
        "nmf_mixture_decomposition": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_nmf_mixture_project_executes_one_replayable_nonnegative_decomposition"
        ),
        "osc_target_orthogonal_correction": (
            "tests/test_phase1c_consumer_projects.py::test_osc_project_executes_one_target_fitted_projection"
        ),
        "pca": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_pca_project_executes_one_closed_fit_application_and_diagnostic_authority"
        ),
        "peaks": (
            "tests/test_phase1c_consumer_projects.py::test_peak_detection_project_executes_one_canonical_peak_table"
        ),
        "peak_guided_pls": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_peak_guided_pls_project_reuses_one_training_peak_mask_for_held_out_rows"
        ),
        "pls_calibration": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_pls_calibration_project_fits_once_and_scores_only_the_held_out_partition"
        ),
        "preprocessing": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_preprocessing_project_executes_the_declared_chain_and_exports_exact_result"
        ),
        "raman_processing": (
            "tests/test_phase1c_consumer_projects.py::test_raman_processing_project_executes_and_explains_each_step"
        ),
        "simca_classification": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_simca_classification_project_executes_explicit_fit_apply_and_heldout_evaluation"
        ),
        "nested_cv_validation": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_nested_cv_project_reports_two_complete_out_of_fold_comparisons"
        ),
        "representative_calibration": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_representative_calibration_project_scores_only_its_kennard_stone_holdout"
        ),
        "simplisma": (
            "tests/test_phase1c_consumer_projects.py::test_simplisma_project_executes_raw_pure_variable_estimates"
        ),
        "variable_selection_comparison": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_variable_selection_comparison_project_executes_training_owned_agreement"
        ),
        "variable_selection_pls": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_variable_selection_pls_project_applies_one_training_owned_mask"
        ),
        "vip_assisted_pls": (
            "tests/test_phase1c_consumer_projects.py::" "test_vip_assisted_pls_project_applies_one_training_owned_mask"
        ),
    }

    assert len(template_nodes) == 34
    assert list(template_statuses.values()).count("ready") == 30
    assert list(template_statuses.values()).count("pending_data") == 0
    assert list(template_statuses.values()).count("pending_qualification") == 4
    assert list(template_statuses.values()).count("wip") == 0
    for slug, node_types in template_nodes.items():
        consumer_id = f"new-analysis:{slug}"
        consumer = consumers[consumer_id]
        expected_state = {
            "ready": "explicit_ready_intent",
            "pending_data": "pending_data_intent",
            "pending_qualification": "pending_qualification_intent",
            "wip": "intent_only_wip",
        }[template_statuses[slug]]
        if slug in executed_projects:
            expected_state = "existing_execution"
        assert consumer["status"] == expected_state
        assert consumer["source_template_status"] == template_statuses[slug]
        assert consumer["required_evidence"] == ("template_semantic_preflight_and_execution")
        assert len(consumer["source_paths"]) == (2 if slug in executed_projects else 1)
        assert (_REPOSITORY_ROOT / consumer["source_paths"][0]).is_file()
        for node_type in node_types:
            bindings = mapped[node_type]["consumer_bindings"]
            assert {
                "binding_status": expected_state,
                "consumer_id": consumer_id,
                "required_evidence": "template_semantic_preflight_and_execution",
            } in bindings

    for slug, test_id in executed_projects.items():
        executed = consumers[f"new-analysis:{slug}"]
        assert executed["status"] == "existing_execution"
        assert executed["evidence_test_id"] == test_id
        assert len(executed["source_paths"]) == 2
        assert all((_REPOSITORY_ROOT / path).is_file() for path in executed["source_paths"])
    assert {
        binding["consumer_id"]
        for node in document["nodes"]
        for binding in node["consumer_bindings"]
        if binding["binding_status"] == "existing_execution" and binding["consumer_id"].startswith("new-analysis:")
    } == {f"new-analysis:{slug}" for slug in executed_projects}


def test_untemplated_nodes_have_explicit_non_deleting_consumers() -> None:
    document = _load(_MAP_PATH)
    template_nodes, _ = _template_nodes()
    directly_templated = set().union(*template_nodes.values())
    consumers = {entry["consumer_id"]: entry for entry in document["consumers"]}

    for node in document["nodes"]:
        bindings = node["consumer_bindings"]
        assert bindings
        if node["node_type"] not in directly_templated:
            assert all(binding["binding_status"] not in _TEMPLATE_PROOF_STATES for binding in bindings)
        for binding in bindings:
            consumer = consumers[binding["consumer_id"]]
            assert binding["required_evidence"] == consumer["required_evidence"]
            if consumer["status"] in {"existing_execution", "transitional"}:
                assert consumer["source_paths"]
                assert all((_REPOSITORY_ROOT / source_path).is_file() for source_path in consumer["source_paths"])


def test_custom_nodes_never_gain_managed_authority_from_the_map() -> None:
    document = _load(_MAP_PATH)
    consumers = {entry["consumer_id"]: entry for entry in document["consumers"]}
    custom_nodes = [node for node in document["nodes"] if node["node_type"].startswith("custom.")]

    assert len(custom_nodes) == 8
    assert all(
        consumers[binding["consumer_id"]]["kind"] in {"planned_new_analysis", "canonical_qualification_project"}
        and binding["consumer_id"] != "canonical-managed-pls-campaign"
        for node in custom_nodes
        for binding in node["consumer_bindings"]
    )


def test_exact_system_bindings_match_current_authorities() -> None:
    document = _load(_MAP_PATH)
    attestation = _load(_ATTESTATION_PATH)

    by_consumer: dict[str, set[str]] = {}
    for node in document["nodes"]:
        for binding in node["consumer_bindings"]:
            by_consumer.setdefault(binding["consumer_id"], set()).add(node["node_type"])

    assert by_consumer["canonical-managed-pls-campaign"] == {
        *attestation["operation_ids"],
        "data.file_load",
    }
    assert by_consumer["imported-model-application"] == {
        "model.apply_fitted_pls",
        "model.load_apply",
        "preprocess.apply_fitted_emsc",
        "preprocess.apply_fitted_msc",
        "preprocess.apply_fitted_osc",
        "preprocess.apply_fitted_scale",
    }
    consumers = {entry["consumer_id"]: entry for entry in document["consumers"]}
    for consumer_id in ("canonical-managed-pls-campaign", "imported-model-application"):
        consumer = consumers[consumer_id]
        assert consumer["status"] == "existing_execution"
        assert "::test_" in consumer["evidence_test_id"]
        assert (_REPOSITORY_ROOT / consumer["evidence_test_path"]).is_file()


def test_plan_records_the_current_map_identity() -> None:
    document = _load(_MAP_PATH)
    plan = _PLAN_PATH.read_text(encoding="utf-8")
    assert plan.count("<!-- canonical-node-project-map-current-evidence") == 1
    assert f"map_digest={document['map_digest']}" in plan
    assert f"registry_digest={document['registry_digest']}" in plan
