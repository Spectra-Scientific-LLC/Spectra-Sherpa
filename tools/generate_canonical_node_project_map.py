#!/usr/bin/env python3
"""Generate the curated canonical-node repair and project-coverage map."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import defaultdict
from pathlib import Path, PurePath
from typing import Any

import yaml

SCHEMA_VERSION = "spectrasherpa-canonical-node-project-map/4"
RETENTION_SCHEMA_VERSION = "spectrasherpa-canonical-node-retention-decisions/2"
TEMPLATE_PREFIX = "new-analysis:"
TEMPLATE_INTENT_STATES = {
    "explicit_ready_intent",
    "pending_data_intent",
    "pending_qualification_intent",
    "intent_only_wip",
}

# A ready label is author intent, not execution evidence.  Each promoted entry
# below binds one exact workbench template to a named executable project proof.
# The proof may become cross-platform qualification only when that same test is
# retained by the release/qualification run; this map does not invent that
# later outcome.
EXECUTED_TEMPLATE_PROJECTS: dict[str, dict[str, str]] = {
    "bilinear_mixture_synthesis": {
        "evidence_test_id": (
            "tests/test_c2_synthesis_contracts.py::"
            "test_bilinear_mixture_project_executes_explicit_species_merge_and_mixture"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c2_synthesis_contracts.py",
    },
    "calibration_transfer": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_calibration_transfer_project_fits_and_reuses_three_explicit_states"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "clustering_comparison": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_partition_clustering_project_compares_two_canonical_cluster_definitions"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "msc_reference_correction": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::test_msc_reference_correction_project_uses_one_frozen_reference"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "emsc_reference_correction": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_emsc_reference_correction_project_uses_explicit_fitted_sources"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "efa_analysis": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_efa_project_executes_raw_forward_and_reverse_rank_diagnostics"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "harmonized_nonnegative_spectra": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_harmonized_nonnegative_project_retains_distinct_preparation_branches"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "ica_decomposition": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::test_ica_project_executes_one_seeded_replayable_decomposition"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "hierarchical_clustering": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_hierarchical_clustering_project_executes_one_closed_cohort_hierarchy"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "knn_classification": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_knn_classification_project_executes_explicit_fit_apply_and_heldout_evaluation"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "mcr_als": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_mcr_project_executes_one_replayable_constrained_decomposition"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "nmf_mixture_decomposition": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_nmf_mixture_project_executes_one_replayable_nonnegative_decomposition"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "osc_target_orthogonal_correction": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::test_osc_project_executes_one_target_fitted_projection"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "pca": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_pca_project_executes_one_closed_fit_application_and_diagnostic_authority"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "peaks": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::test_peak_detection_project_executes_one_canonical_peak_table"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "peak_guided_pls": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_peak_guided_pls_project_reuses_one_training_peak_mask_for_held_out_rows"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "pls_calibration": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_pls_calibration_project_fits_once_and_scores_only_the_held_out_partition"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "preprocessing": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_preprocessing_project_executes_the_declared_chain_and_exports_exact_result"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "raman_processing": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::test_raman_processing_project_executes_and_explains_each_step"
        ),
        "evidence_test_path": ("packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py"),
    },
    "simca_classification": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_simca_classification_project_executes_explicit_fit_apply_and_heldout_evaluation"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "nested_cv_validation": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_nested_cv_project_reports_two_complete_out_of_fold_comparisons"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "representative_calibration": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_representative_calibration_project_scores_only_its_kennard_stone_holdout"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "simplisma": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::test_simplisma_project_executes_raw_pure_variable_estimates"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "variable_selection_comparison": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_variable_selection_comparison_project_executes_training_owned_agreement"
        ),
        "evidence_test_path": ("packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py"),
    },
    "variable_selection_pls": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_variable_selection_pls_project_applies_one_training_owned_mask"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
    "vip_assisted_pls": {
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::" "test_vip_assisted_pls_project_applies_one_training_owned_mask"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
    },
}

# These system consumers are intentionally separate from the New Analysis
# template scan. ``existing_execution`` is admitted only when a named,
# collectible test executes the claimed current path; a source file or a plan
# entry is never execution evidence by itself.
SYSTEM_PROJECTS: dict[str, dict[str, Any]] = {
    "fitted-regression-delivery": {
        "kind": "canonical_qualification_project",
        "required_evidence": "fold_local_fit_and_bound_artifact_application",
        "scientific_question": "Do PCR, SVR and linear regression retain fitted-state custody through local delivery?",
        "source_paths": [
            "packages/spectra-sherpa/tests/test_fitted_regression_nodes.py",
            "packages/spectra-sherpa/tests/test_canonical_project_package.py",
        ],
        "evidence_test_id": (
            "tests/test_canonical_project_package.py::"
            "test_new_regression_models_roundtrip_sherpa_and_execute_bound_local_deploy"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_canonical_project_package.py",
        "status": "existing_execution",
    },
    "sample-aligned-feature-engineering": {
        "kind": "canonical_qualification_project",
        "required_evidence": "selected_columns_and_sample_aligned_feature_merge",
        "scientific_question": "Can selected peak features augment spectra without changing sample or target identity?",
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/data/feature_engineering.py",
            "packages/spectra-sherpa/tests/test_feature_engineering_nodes.py",
        ],
        "evidence_test_id": "tests/test_feature_engineering_nodes.py::test_canonical_admission_execution_and_contracts",
        "evidence_test_path": "packages/spectra-sherpa/tests/test_feature_engineering_nodes.py",
        "status": "existing_execution",
    },
    "canonical-managed-pls-campaign": {
        "kind": "managed_optimization_profile",
        "required_evidence": "canonical_campaign_execution_and_project_corpus",
        "scientific_question": (
            "Can a saved quantitative PLS DAG be validated, searched, refit, "
            "exported, and independently reproduced without changing its operations?"
        ),
        "source_paths": [
            "docs/evidence/managed-optimization-runtime-attestation.json",
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/canonical_workbench_baseline.py",
            "packages/spectra-server/tests/test_harness_canonical_search_campaign.py",
        ],
        "evidence_test_id": (
            "tests/test_harness_canonical_search_campaign.py::"
            "test_search_driver_runs_every_ledger_member_and_records_deterministic_decision"
        ),
        "evidence_test_path": "packages/spectra-server/tests/test_harness_canonical_search_campaign.py",
        "status": "existing_execution",
    },
    "imported-model-application": {
        "kind": "canonical_application",
        "required_evidence": "clean_oss_import_application_and_numeric_reproduction",
        "scientific_question": (
            "Can a scientist apply an imported fitted model to compatible spectra "
            "and reproduce the publisher's application result?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/sdk/canonical_application.py",
            "packages/spectra-sherpa/src/spectra_sherpa/sdk/canonical_reproduction.py",
            "packages/spectra-sherpa/tests/test_canonical_reproduction.py",
        ],
        "evidence_test_id": (
            "tests/test_canonical_reproduction.py::"
            "test_oss_reproduction_recomputes_validation_and_application_without_server_import"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_canonical_reproduction.py",
        "status": "existing_execution",
    },
    "model-aware-regression-application": {
        "kind": "canonical_application",
        "required_evidence": "split_train_predict_evaluate_export_without_refit",
        "scientific_question": "Can regression trainers be interchanged without applying another algorithm's state?",
        "source_paths": ["packages/spectra-sherpa/tests/test_regression_application_workflow.py"],
        "evidence_test_id": (
            "tests/test_regression_application_workflow.py::"
            "test_split_train_predict_evaluate_and_export_without_refit"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_regression_application_workflow.py",
        "status": "existing_execution",
    },
    "reference-spectrum-synthesis": {
        "kind": "canonical_application",
        "required_evidence": "cited_response_equation_oracle_and_canonical_dag_execution",
        "scientific_question": (
            "Can explicitly attributed NIST or HITRAN reference responses and ppm concentrations produce "
            "an inspectable synthetic mixture through only cited canonical DAG operations?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/sdk/canonical_synthesis.py",
            "packages/spectra-sherpa/tests/test_c2_synthesis_contracts.py",
            "packages/spectra-sherpa/tests/test_synthesis_service.py",
        ],
        "evidence_test_id": ("tests/test_synthesis_service.py::test_nist_synthesis_uses_decadic_beer_lambert_units"),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_synthesis_service.py",
        "status": "existing_execution",
    },
    "phase-0c-prototype-decommission": {
        "kind": "canonical_decommission",
        "required_evidence": "consumer_migration_and_negative_registry_proof",
        "scientific_question": (
            "Have all shipped consumers moved to the sole canonical operation before the prototype identity is removed?"
        ),
        "source_paths": ["docs/plan/canonical-dag-managed-optimization-plan.md"],
        "status": "transitional",
    },
    "supervised-data-preparation": {
        "kind": "canonical_new_analysis",
        "required_evidence": "typed_template_binding_and_materialization_roundtrip",
        "scientific_question": (
            "Can a scientist bind reference values, filter samples, preserve groups, "
            "and materialize one exact supervised dataset for downstream analysis?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/data/templates/supervised_data_preparation.yaml",
            "packages/spectra-sherpa/tests/test_canonical_sample_table.py",
            "packages/spectra-sherpa/tests/test_workflow_templates.py",
        ],
        "evidence_test_id": (
            "tests/test_canonical_sample_table.py::"
            "test_ready_supervised_template_executes_attach_filter_and_export_without_semantic_loss"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_canonical_sample_table.py",
        "status": "existing_execution",
    },
    "multidimensional-data-preparation": {
        "kind": "canonical_data_preparation",
        "required_evidence": "typed_dimension_projection_and_scientific_identity_roundtrip",
        "scientific_question": (
            "Can a scientist choose one exact plane from a multidimensional dataset "
            "without flattening or losing its axis, provenance, and source identity?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/data/dimension_projection.py",
            "packages/spectra-sherpa/tests/test_dso_durable_propagation.py",
        ],
        "evidence_test_id": (
            "tests/test_dso_durable_propagation.py::"
            "test_dimension_projection_is_exact_and_preserves_remaining_metadata"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_dso_durable_propagation.py",
        "status": "existing_execution",
    },
    "multiway-parafac-decomposition": {
        "kind": "canonical_qualification_project",
        "required_evidence": "native_multiway_fit_application_and_mode_preservation",
        "scientific_question": (
            "Can a scientist decompose a sample-first multiway measurement while "
            "preserving every non-observation mode, apply the fitted model to new "
            "observations, and inspect that no unfolding occurred?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/lib/parafac_core.py",
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/parafac_node.py",
            "packages/spectra-sherpa/tests/test_parafac_node.py",
        ],
        "evidence_test_id": (
            "tests/test_parafac_node.py::" "test_parafac_is_deterministic_preserves_modes_and_records_no_unfolding"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_parafac_node.py",
        "status": "existing_execution",
    },
    "spectral-library-identification": {
        "kind": "canonical_qualification_project",
        "required_evidence": "exact_nist_content_domain_and_identity_admission",
        "scientific_question": (
            "Can an exact NIST JCAMP reference be admitted with its compound identity, "
            "spectral domain, and source-content digest intact?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/data/references.py",
            "packages/spectra-sherpa/tests/test_canonical_data_sources.py",
        ],
        "evidence_test_id": ("tests/test_canonical_data_sources.py::test_nist_library_binds_exact_content_and_domain"),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_canonical_data_sources.py",
        "status": "existing_execution",
    },
    "spectral-library-comparison": {
        "kind": "canonical_qualification_project",
        "required_evidence": "measured_reference_ranking_and_live_generated_equivalence",
        "scientific_question": (
            "Does a measured query rank the matching reference first under the same "
            "axis, overlap, and HQI authority in live and exported execution?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/library_compare_node.py",
            "packages/spectra-sherpa/tests/test_c2_library_comparison_contract.py",
        ],
        "evidence_test_id": (
            "tests/test_c2_library_comparison_contract.py::"
            "test_library_live_generated_and_core_paths_share_one_authority"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c2_library_comparison_contract.py",
        "status": "existing_execution",
    },
    "plsda-fitted-application": {
        "kind": "canonical_qualification_project",
        "required_evidence": "categorical_fit_fitted_application_and_exported_equivalence",
        "scientific_question": (
            "Can one categorical PLS-DA fit classify compatible spectra through the exact "
            "portable fitted-state application operation?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/application_nodes.py",
            "packages/spectra-sherpa/tests/test_c2_plsda_contract.py",
        ],
        "evidence_test_id": (
            "tests/test_c2_plsda_contract.py::"
            "test_plsda_predictor_preserves_class_score_semantics_in_generated_execution"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c2_plsda_contract.py",
        "status": "existing_execution",
    },
    "plsda-classification-fit": {
        "kind": "canonical_qualification_project",
        "required_evidence": "categorical_fit_live_generated_and_diagnostic_equivalence",
        "scientific_question": (
            "Can a categorical PLS-DA fit preserve decisions, dummy-response scores, "
            "loadings, metrics, and plots through editable generated execution?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_nodes.py",
            "packages/spectra-sherpa/tests/test_c2_plsda_contract.py",
        ],
        "evidence_test_id": (
            "tests/test_c2_plsda_contract.py::" "test_plsda_live_and_generated_python_share_the_operation"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c2_plsda_contract.py",
        "status": "existing_execution",
    },
    "scientific-dataset-export": {
        "kind": "canonical_qualification_project",
        "required_evidence": "curated_project_execution_and_digest_bound_scientific_export",
        "scientific_question": (
            "Can a scientist execute a curated preparation project and export its exact "
            "final scientific dataset with a content-bound artifact?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/output/export_node.py",
            "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
        ],
        "evidence_test_id": (
            "tests/test_phase1c_consumer_projects.py::"
            "test_preprocessing_project_executes_the_declared_chain_and_exports_exact_result"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_phase1c_consumer_projects.py",
        "status": "existing_execution",
    },
    "spectral-response-map": {
        "kind": "canonical_qualification_project",
        "required_evidence": "axis_faithful_scientist_facing_response_map",
        "scientific_question": (
            "Can a measured multi-sample response matrix be inspected as one heatmap "
            "without losing its sample or spectral coordinates?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/output/contour_plot_node.py",
            "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        ],
        "evidence_test_id": (
            "tests/test_c3b_missing_consumer_projects.py::" "test_spectral_response_map_executes_the_contour_consumer"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        "status": "existing_execution",
    },
    "synthetic-process-monitoring": {
        "kind": "canonical_qualification_project",
        "required_evidence": "time_ordered_detrending_and_explicit_window_execution",
        "scientific_question": (
            "Can a time-ordered process matrix remove batch-local linear drift and "
            "produce explicit, auditable moving-window summaries?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/time_series.py",
            "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        ],
        "evidence_test_id": (
            "tests/test_c3b_missing_consumer_projects.py::"
            "test_process_monitoring_executes_trend_removal_then_moving_windows"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        "status": "existing_execution",
    },
    "regression-model-comparison": {
        "kind": "canonical_qualification_project",
        "required_evidence": "same_dataset_target_and_prediction_scope_execution",
        "scientific_question": (
            "Which of linear regression, PCR, PLS, and SVR gives the most defensible "
            "validation result under the same split and preprocessing?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        ],
        "evidence_test_id": (
            "tests/test_c3b_missing_consumer_projects.py::"
            "test_regression_model_comparison_uses_one_dataset_target_and_prediction_scope"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        "status": "existing_execution",
    },
    "clustering-comparison": {
        "kind": "planned_new_analysis",
        "required_evidence": "template_semantic_preflight_and_execution",
        "scientific_question": (
            "Do K-means, DBSCAN, and hierarchical clustering reveal stable and "
            "scientifically interpretable sample groups?"
        ),
        "source_paths": [],
        "status": "planned",
    },
    "decomposition-comparison": {
        "kind": "canonical_qualification_project",
        "required_evidence": "fit_application_artifact_projection_equivalence",
        "scientific_question": (
            "Which latent representation—PCA, ICA, or NMF—best explains the major sources of spectral variation?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/pca_nodes.py",
            "packages/spectra-sherpa/tests/test_c2_pca_contract.py",
        ],
        "evidence_test_id": (
            "tests/test_c2_pca_contract.py::"
            "test_pca_live_generated_application_and_artifact_paths_share_one_projection"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c2_pca_contract.py",
        "status": "existing_execution",
    },
    "custom-mixture-design": {
        "kind": "canonical_qualification_project",
        "required_evidence": "typed_curve_generation_and_common_grid_execution",
        "scientific_question": (
            "Can mixture compositions and concentration curves be generated on an "
            "explicit grid with inspectable interpolation rules?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        ],
        "evidence_test_id": (
            "tests/test_c3b_missing_consumer_projects.py::"
            "test_custom_mixture_design_executes_curves_synthetic_source_and_common_grid"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        "status": "existing_execution",
    },
    "custom-calibration-and-selection": {
        "kind": "canonical_qualification_project",
        "required_evidence": "linear_nonlinear_response_and_explicit_mask_execution",
        "scientific_question": (
            "Can a custom calibration and hybrid selection strategy be compared "
            "against a transparent first-party baseline?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        ],
        "evidence_test_id": (
            "tests/test_c3b_missing_consumer_projects.py::"
            "test_custom_calibration_and_selection_compares_linear_and_saturation_responses"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        "status": "existing_execution",
    },
    "instrument-response-simulation": {
        "kind": "canonical_qualification_project",
        "required_evidence": "seeded_noise_and_distinct_saturation_authority_execution",
        "scientific_question": (
            "How do explicit noise and detector-saturation assumptions change a synthetic spectral response?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        ],
        "evidence_test_id": (
            "tests/test_c3b_missing_consumer_projects.py::"
            "test_instrument_response_simulation_retains_noise_and_both_saturation_authorities"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        "status": "existing_execution",
    },
    "validation-diagnostics": {
        "kind": "canonical_qualification_project",
        "required_evidence": "producer_bound_out_of_fold_evidence_consumption",
        "scientific_question": (
            "Are model errors, outliers, and cross-validation results stable enough "
            "to support the intended scientific use?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/diagnostics.py",
            "packages/spectra-sherpa/tests/test_c2_cross_validation_contract.py",
        ],
        "evidence_test_id": (
            "tests/test_c2_cross_validation_contract.py::"
            "test_registered_nested_cv_evidence_is_consumed_without_rebinding_its_parts"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c2_cross_validation_contract.py",
        "status": "existing_execution",
    },
    "variable-selection-comparison": {
        "kind": "canonical_qualification_project",
        "required_evidence": "training_owned_ipls_selection_and_bounded_audit_execution",
        "scientific_question": (
            "Which variables remain defensible across CARS, iPLS, SPA, MC-UVE, and "
            "stability analysis under the same validation design?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        ],
        "evidence_test_id": (
            "tests/test_c3b_missing_consumer_projects.py::"
            "test_variable_selection_comparison_adds_ipls_and_audits_its_training_owned_result"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_c3b_missing_consumer_projects.py",
        "status": "existing_execution",
    },
    "deployed-model-application": {
        "kind": "canonical_qualification_project",
        "required_evidence": "typed_input_and_digest_bound_deployment_response",
        "scientific_question": (
            "Can a deployed model accept a typed sample, produce a typed prediction, "
            "and retain model and input provenance?"
        ),
        "source_paths": [
            "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/deploy_nodes.py",
            "packages/spectra-sherpa/tests/test_canonical_deploy_boundary.py",
        ],
        "evidence_test_id": (
            "tests/test_canonical_deploy_boundary.py::" "test_live_deployment_boundary_returns_digest_bound_response"
        ),
        "evidence_test_path": "packages/spectra-sherpa/tests/test_canonical_deploy_boundary.py",
        "status": "existing_execution",
    },
    "mixture-synthesis": {
        "kind": "planned_new_analysis",
        "required_evidence": "template_semantic_preflight_and_execution",
        "scientific_question": (
            "Can pure-component spectra and concentrations reproduce a known mixture "
            "under explicit blending assumptions?"
        ),
        "source_paths": [],
        "status": "planned",
    },
}


# Existing non-template consumers are exact operation bindings, not a family
# wildcard and not an independent eligibility list. Managed-profile membership
# is derived from the checked runtime attestation in ``build_map`` so this file
# cannot become a second, hand-maintained managed-operation registry.
EXACT_SYSTEM_BINDINGS: dict[str, tuple[str, ...]] = {
    **{
        f"model.{prefix}{family}": ("fitted-regression-delivery",)
        for prefix in ("fitted_", "apply_fitted_")
        for family in ("pcr", "svr", "linear_regression")
    },
    "data.merge_features": ("sample-aligned-feature-engineering",),
    "selection.select_columns": ("sample-aligned-feature-engineering",),
    "analysis.compare_library": ("spectral-library-comparison",),
    "classification.apply_plsda": ("plsda-fitted-application",),
    "classification.plsda": ("plsda-classification-fit",),
    "data.file_load": ("canonical-managed-pls-campaign",),
    "model.apply_fitted_pls": ("imported-model-application",),
    "model.predict_regression": ("model-aware-regression-application",),
    "model.load_apply": ("imported-model-application",),
    "model.parafac": ("multiway-parafac-decomposition",),
    "preprocess.apply_fitted_emsc": ("imported-model-application",),
    "preprocess.apply_fitted_msc": ("imported-model-application",),
    "preprocess.apply_fitted_osc": ("imported-model-application",),
    "preprocess.apply_fitted_scale": ("imported-model-application",),
    "output.export": ("scientific-dataset-export",),
    "output.contour": ("spectral-response-map",),
    "synthesis.hitran_response": ("reference-spectrum-synthesis",),
    "synthesis.nist_quant_ir_response": ("reference-spectrum-synthesis",),
    "synthesis.ppm_fraction": ("reference-spectrum-synthesis",),
    "time_series.moving_window": ("synthetic-process-monitoring",),
    "time_series.trend_removal": ("synthetic-process-monitoring",),
}


# Nodes absent from today's template YAML and from the exact system bindings
# receive an explicit future proof
# consumer. Assigning a node here does not certify it: the generated binding is
# marked planned_addition or system_consumer until C3b supplies executable proof.
UNCOVERED_BINDINGS: dict[str, str] = {
    "custom.catmull_rom_curve": "custom-mixture-design",
    "custom.concentration_curve": "custom-mixture-design",
    "custom.golden_grid_align": "custom-mixture-design",
    "custom.hybrid_selector": "custom-calibration-and-selection",
    "custom.linear_calibration": "custom-calibration-and-selection",
    "custom.noise_injection": "instrument-response-simulation",
    "custom.saturation_model": "instrument-response-simulation",
    "custom.system_saturation": "instrument-response-simulation",
    "data.attach_target": "supervised-data-preparation",
    "data.collection_load": "supervised-data-preparation",
    "data.load_group": "supervised-data-preparation",
    "data.nist_library": "spectral-library-identification",
    "data.synthetic_curve": "custom-mixture-design",
    "deploy.input": "deployed-model-application",
    "deploy.output": "deployed-model-application",
    "diagnostics.cross_validation": "validation-diagnostics",
    "model.linear_regression": "regression-model-comparison",
    "model.pca_transform": "decomposition-comparison",
    "model.pcr": "regression-model-comparison",
    "model.svr": "regression-model-comparison",
    "selection.dimension_project": "multidimensional-data-preparation",
    "selection.audit": "variable-selection-comparison",
    "selection.ipls": "variable-selection-comparison",
}


def _slice_for(node_type: str) -> str:
    if node_type in {"preprocess.emsc", "preprocess.osc"}:
        return "C2g"
    if node_type.startswith(("baseline.", "preprocess.")):
        return "C2f"
    if node_type.startswith("classification."):
        return "C2i"
    if node_type.startswith("model."):
        if node_type in {
            "model.dbscan",
            "model.efa",
            "model.hca",
            "model.ica",
            "model.kmeans",
            "model.mcr_als",
            "model.nmf",
            "model.parafac",
            "model.pca",
            "model.pca_transform",
            "model.simplisma",
        }:
            return "C2j"
        return "C2h"
    if node_type.startswith(("diagnostics.", "selection.")):
        return "C2k"
    if node_type.startswith(("data.", "deploy.", "custom.")):
        return "C2l"
    return "C2m"


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _governed_advisor_actions(repository_root: Path) -> set[str]:
    """Read the shared action vocabulary without importing either runtime."""

    path = repository_root / "packages/spectra-sherpa/src/spectra_sherpa/app/ws_actions.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    string_constants: dict[str, str] = {}
    advisor_names: list[str] | None = None
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            target = statement.target
            value = statement.value
        else:
            continue
        if not isinstance(target, ast.Name) or value is None:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            string_constants[target.id] = value.value
        elif target.id == "SHERPA_WS_ACTIONS" and isinstance(value, (ast.Tuple, ast.List)):
            advisor_names = [element.id for element in value.elts if isinstance(element, ast.Name)]
            if len(advisor_names) != len(value.elts):
                raise ValueError("governed Advisor action vocabulary is not a closed name list")
    if advisor_names is None:
        raise ValueError("governed Advisor action vocabulary is missing")
    try:
        actions = {string_constants[name] for name in advisor_names}
    except KeyError as exc:
        raise ValueError(f"governed Advisor action constant {exc.args[0]!r} is unresolved") from exc
    if len(actions) != len(advisor_names):
        raise ValueError("governed Advisor action vocabulary contains duplicate identities")
    return actions


def _retention_decisions(
    repository_root: Path,
    registry_nodes: dict[str, dict[str, Any]],
    *,
    registry_digest: str,
) -> dict[str, dict[str, Any]]:
    """Load the exact owner-approved catalog disposition; unknown nodes stay undecided."""

    path = repository_root / "docs/plan/canonical-node-retention-decisions.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if set(document) != {
        "registry_digest",
        "retained_node_types",
        "retained_reason",
        "schema_version",
        "superseded_nodes",
    }:
        raise ValueError("canonical node retention decision fields are not closed")
    if document["schema_version"] != RETENTION_SCHEMA_VERSION:
        raise ValueError("canonical node retention decision version is unsupported")
    if document["registry_digest"] != registry_digest:
        raise ValueError("canonical node retention registry digest mismatch")
    retained = document["retained_node_types"]
    reason = document["retained_reason"]
    superseded = document["superseded_nodes"]
    if (
        not isinstance(retained, list)
        or not all(isinstance(value, str) for value in retained)
        or retained != sorted(set(retained))
        or not isinstance(reason, str)
        or not reason.strip()
        or not isinstance(superseded, list)
    ):
        raise ValueError("canonical node retention decisions are malformed")

    superseded_types = [entry.get("node_type") for entry in superseded if isinstance(entry, dict)]
    if (
        len(superseded_types) != len(superseded)
        or not all(isinstance(value, str) for value in superseded_types)
        or superseded_types != sorted(set(superseded_types))
    ):
        raise ValueError("superseded node inventory must be sorted, unique, and named")
    governed_advisor_actions = _governed_advisor_actions(repository_root)

    decisions: dict[str, dict[str, Any]] = {
        node_type: {
            "retention_decision": "retain_and_repair",
            "retention_reason": reason,
            "replacement_node_type": None,
        }
        for node_type in retained
    }
    for entry in superseded:
        if not isinstance(entry, dict) or set(entry) != {"node_type", "reason", "replacement_authorities"}:
            raise ValueError("superseded node decision fields are not closed")
        node_type = entry["node_type"]
        replacement_authorities = entry["replacement_authorities"]
        removal_reason = entry["reason"]
        if (
            not isinstance(node_type, str)
            or not isinstance(removal_reason, str)
            or not removal_reason.strip()
            or not isinstance(replacement_authorities, list)
            or not replacement_authorities
            or node_type in decisions
        ):
            raise ValueError("superseded node decision is malformed or duplicated")

        authority_pairs: list[tuple[str, str]] = []
        for authority in replacement_authorities:
            if not isinstance(authority, dict) or set(authority) != {"authority_type", "identifier"}:
                raise ValueError("replacement authority fields are not closed")
            authority_type = authority["authority_type"]
            identifier = authority["identifier"]
            if authority_type not in {"canonical_node", "governed_advisor_action"} or not isinstance(identifier, str):
                raise ValueError("replacement authority is malformed")
            authority_pairs.append((authority_type, identifier))
        if authority_pairs != sorted(set(authority_pairs)):
            raise ValueError("replacement authorities must be sorted and unique")

        canonical_replacements = [
            identifier for authority_type, identifier in authority_pairs if authority_type == "canonical_node"
        ]
        for replacement in canonical_replacements:
            if (
                replacement not in registry_nodes
                or decisions.get(replacement, {}).get("retention_decision") != "retain_and_repair"
                or not registry_nodes[replacement]["contract_complete"]
            ):
                raise ValueError(f"retired canonical replacement {replacement!r} is not available")
        for authority_type, identifier in authority_pairs:
            if authority_type == "governed_advisor_action" and identifier not in governed_advisor_actions:
                raise ValueError(f"retired governed Advisor replacement {identifier!r} is not available")

        # The plan retains the historical disposition after physical removal,
        # but the live repair map describes only the current registry.
        if node_type not in registry_nodes:
            continue
        if len(authority_pairs) != 1 or authority_pairs[0][0] != "canonical_node":
            raise ValueError("a still-live superseded node requires one canonical-node replacement")
        replacement = canonical_replacements[0]
        decisions[node_type] = {
            "retention_decision": "remove_superseded",
            "retention_reason": removal_reason,
            "replacement_node_type": replacement,
        }

    unknown = sorted(set(decisions) - set(registry_nodes))
    undecided = sorted(set(registry_nodes) - set(decisions))
    if unknown or undecided:
        raise ValueError(f"canonical node retention drift: unknown={unknown}, undecided={undecided}")
    for node_type, decision in decisions.items():
        replacement = decision["replacement_node_type"]
        if replacement is not None:
            if replacement not in registry_nodes or replacement == node_type:
                raise ValueError(f"invalid canonical replacement {replacement!r} for {node_type!r}")
            if decisions.get(replacement, {}).get("retention_decision") != "retain_and_repair":
                raise ValueError(f"replacement {replacement!r} is not retained")
            if not registry_nodes[replacement]["contract_complete"]:
                raise ValueError(f"replacement {replacement!r} is not contract complete")
    return decisions


def _template_intent_status(raw_status: object, *, source_path: Path) -> tuple[str, str]:
    """Preserve the template author's declared status without inventing readiness."""
    if raw_status == "ready":
        return "explicit_ready_intent", "ready"
    if raw_status == "pending_data":
        return "pending_data_intent", "pending_data"
    if raw_status == "pending_qualification":
        return "pending_qualification_intent", "pending_qualification"
    if raw_status == "wip":
        return "intent_only_wip", "wip"
    raise ValueError(f"unsupported template status {raw_status!r} in {source_path}")


def _repository_relative_path(path: PurePath, repository_root: PurePath) -> str:
    """Serialize repository identities independently of the host OS."""
    return path.relative_to(repository_root).as_posix()


def _template_consumers(template_dir: Path, repository_root: Path) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    consumers: list[dict[str, Any]] = []
    node_to_consumers: dict[str, list[str]] = defaultdict(list)
    seen_consumer_ids: set[str] = set()
    for path in sorted(template_dir.glob("*.yaml")):
        if path.name == "_categories.yaml":
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        slug = str(document["slug"])
        consumer_id = f"{TEMPLATE_PREFIX}{slug}"
        if consumer_id in seen_consumer_ids:
            raise ValueError(f"duplicate New Analysis template consumer ID {consumer_id!r}: {path}")
        seen_consumer_ids.add(consumer_id)
        intent_status, source_template_status = _template_intent_status(document.get("status"), source_path=path)
        execution = EXECUTED_TEMPLATE_PROJECTS.get(slug)
        if execution is not None:
            if source_template_status != "ready":
                raise ValueError(f"executed New Analysis project {slug!r} must be explicitly ready")
            evidence_path = repository_root / execution["evidence_test_path"]
            if not evidence_path.is_file():
                raise ValueError(f"executed New Analysis project {slug!r} has no evidence test")
            test_name = execution["evidence_test_id"].split("::", 1)[1]
            if f"def {test_name}(" not in evidence_path.read_text(encoding="utf-8"):
                raise ValueError(f"executed New Analysis project {slug!r} evidence test is absent")
            intent_status = "existing_execution"
        node_types = sorted({str(node["node_type"]) for node in document["template_data"]["nodes"]})
        consumer = {
            "consumer_id": consumer_id,
            "kind": "new_analysis_template",
            "required_evidence": "template_semantic_preflight_and_execution",
            "scientific_question": str(document["description"]).strip(),
            "source_paths": [_repository_relative_path(path, repository_root)],
            "source_template_status": source_template_status,
            "status": intent_status,
        }
        if execution is not None:
            consumer["evidence_test_id"] = execution["evidence_test_id"]
            consumer["evidence_test_path"] = execution["evidence_test_path"]
            consumer["source_paths"].append(execution["evidence_test_path"])
        consumers.append(consumer)
        for node_type in node_types:
            node_to_consumers[node_type].append(consumer_id)
    return consumers, node_to_consumers


def build_map(repository_root: Path) -> dict[str, Any]:
    census_path = repository_root / "docs/evidence/m4-node-contract-census.json"
    attestation_path = repository_root / "docs/evidence/managed-optimization-runtime-attestation.json"
    template_dir = repository_root / "packages/spectra-sherpa/src/spectra_sherpa/data/templates"
    census = json.loads(census_path.read_text(encoding="utf-8"))
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    template_consumers, template_bindings = _template_consumers(template_dir, repository_root)
    registry_nodes = {entry["node_type"]: entry for entry in census["nodes"]}
    managed_operation_ids = tuple(str(operation_id) for operation_id in attestation["operation_ids"])
    unknown_managed_operations = sorted(set(managed_operation_ids) - set(registry_nodes))
    if unknown_managed_operations:
        raise ValueError(
            "runtime attestation references unregistered managed operations: " + ", ".join(unknown_managed_operations)
        )
    exact_system_bindings = {node_type: list(bindings) for node_type, bindings in EXACT_SYSTEM_BINDINGS.items()}
    for node_type in managed_operation_ids:
        exact_system_bindings.setdefault(node_type, []).append("canonical-managed-pls-campaign")
    retention_decisions = _retention_decisions(
        repository_root,
        registry_nodes,
        registry_digest=census["registry_digest"],
    )

    unregistered_template_types = sorted(set(template_bindings) - set(registry_nodes))
    if unregistered_template_types:
        raise ValueError("templates reference unregistered node types: " + ", ".join(unregistered_template_types))
    uncovered = set(registry_nodes) - set(template_bindings)
    untemplated_assignments = set(UNCOVERED_BINDINGS) | set(exact_system_bindings)
    missing_assignments = sorted(uncovered - untemplated_assignments)
    stale_assignments = sorted(set(UNCOVERED_BINDINGS) - uncovered)
    if missing_assignments or stale_assignments:
        raise ValueError(f"uncovered binding drift: missing={missing_assignments}, stale={stale_assignments}")

    consumers = template_consumers + [
        {"consumer_id": consumer_id, **definition} for consumer_id, definition in sorted(SYSTEM_PROJECTS.items())
    ]
    consumers_by_id = {entry["consumer_id"]: entry for entry in consumers}
    for consumer in consumers:
        if consumer["status"] != "existing_execution":
            continue
        evidence_path = repository_root / consumer["evidence_test_path"]
        if not evidence_path.is_file():
            raise ValueError(f"existing execution {consumer['consumer_id']!r} has no evidence test")
        test_name = consumer["evidence_test_id"].split("::", 1)[1]
        if f"def {test_name}(" not in evidence_path.read_text(encoding="utf-8"):
            raise ValueError(f"existing execution {consumer['consumer_id']!r} evidence test is absent")
    nodes: list[dict[str, Any]] = []
    for node_type, census_entry in sorted(registry_nodes.items()):
        retention = retention_decisions[node_type]
        present = template_bindings.get(node_type, [])
        bindings = []
        for consumer_id in sorted(set(present)):
            consumer = consumers_by_id[consumer_id]
            bindings.append(
                {
                    "binding_status": consumer["status"],
                    "consumer_id": consumer_id,
                    "required_evidence": consumer["required_evidence"],
                }
            )
        for consumer_id in exact_system_bindings.get(node_type, ()):
            consumer = consumers_by_id[consumer_id]
            bindings.append(
                {
                    "binding_status": consumer["status"],
                    "consumer_id": consumer_id,
                    "required_evidence": consumer["required_evidence"],
                }
            )
        if not bindings:
            consumer_id = UNCOVERED_BINDINGS[node_type]
            if consumer_id not in consumers_by_id:
                raise ValueError(f"unknown consumer {consumer_id!r} for {node_type}")
            consumer = consumers_by_id[consumer_id]
            status = "planned_template_addition" if consumer_id.startswith(TEMPLATE_PREFIX) else consumer["status"]
            bindings.append(
                {
                    "binding_status": status,
                    "consumer_id": consumer_id,
                    "required_evidence": consumer["required_evidence"],
                }
            )

        typed_ports = census_entry["typed_ports"]
        compatibility = census_entry["compatibility_types"]
        gaps: list[str] = []
        if census_entry["execution_contract"] is None:
            gaps.append("missing_execution_contract")
        if not census_entry["policy"]["explicit"]:
            gaps.append("missing_explicit_worker_policy")
        if not typed_ports["inputs_declared"]:
            gaps.append("missing_typed_input_ports")
        if not typed_ports["outputs_declared"]:
            gaps.append("missing_typed_output_ports")
        if compatibility["output_type"] == "NDDataset":
            gaps.append("broad_nddataset_output_alias")

        has_present_template = bool(present)
        if retention["retention_decision"] == "remove_superseded":
            disposition = "remove_after_consumer_migration"
        elif census_entry["contract_complete"]:
            disposition = "template_audit_required" if has_present_template else "project_coverage_required"
        else:
            disposition = (
                "contract_and_template_audit_required"
                if has_present_template
                else "contract_and_project_coverage_required"
            )
        nodes.append(
            {
                "consumer_bindings": bindings,
                "contract_complete": bool(census_entry["contract_complete"]),
                "family": node_type.split(".", 1)[0],
                "node_type": node_type,
                "planned_slice": _slice_for(node_type),
                "repair_disposition": disposition,
                "repair_gaps": gaps,
                **retention,
            }
        )

    family_totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"contract_complete": 0, "remove_superseded": 0, "repair_required": 0, "total": 0}
    )
    for node in nodes:
        totals = family_totals[node["family"]]
        totals["total"] += 1
        if node["retention_decision"] == "remove_superseded":
            key = "remove_superseded"
        else:
            key = "contract_complete" if node["contract_complete"] else "repair_required"
        totals[key] += 1

    payload: dict[str, Any] = {
        "aggregates": {
            "explicit_ready_template_intents": sum(
                consumer["status"] == "explicit_ready_intent" for consumer in template_consumers
            ),
            "executed_template_projects": sum(
                consumer["status"] == "existing_execution" for consumer in template_consumers
            ),
            "contract_complete": sum(node["contract_complete"] for node in nodes),
            "existing_template_candidates": len(template_consumers),
            "nodes_in_existing_templates": sum(
                any(
                    binding["consumer_id"].startswith(TEMPLATE_PREFIX)
                    and binding["binding_status"] != "planned_template_addition"
                    for binding in node["consumer_bindings"]
                )
                for node in nodes
            ),
            "planned_or_system_coverage_required": sum(
                all(
                    not binding["consumer_id"].startswith(TEMPLATE_PREFIX)
                    or binding["binding_status"] == "planned_template_addition"
                    for binding in node["consumer_bindings"]
                )
                for node in nodes
            ),
            "repair_required": sum(
                node["retention_decision"] == "retain_and_repair" and not node["contract_complete"] for node in nodes
            ),
            "remove_superseded": sum(node["retention_decision"] == "remove_superseded" for node in nodes),
            "retain_and_repair": sum(node["retention_decision"] == "retain_and_repair" for node in nodes),
            "total_nodes": len(nodes),
            "pending_data_template_intents": sum(
                consumer["status"] == "pending_data_intent" for consumer in template_consumers
            ),
            "pending_qualification_template_intents": sum(
                consumer["status"] == "pending_qualification_intent" for consumer in template_consumers
            ),
            "wip_template_intents": sum(consumer["status"] == "intent_only_wip" for consumer in template_consumers),
        },
        "consumers": sorted(consumers, key=lambda item: item["consumer_id"]),
        "family_totals": dict(sorted(family_totals.items())),
        "nodes": nodes,
        "registry_digest": census["registry_digest"],
        "schema_version": SCHEMA_VERSION,
    }
    return {"map_digest": _canonical_digest(payload), **payload}


def render_markdown(document: dict[str, Any]) -> str:
    aggregates = document["aggregates"]
    lines = [
        "# Canonical node project and repair map",
        "",
        f"- Map digest: `{document['map_digest']}`",
        f"- Registry digest: `{document['registry_digest']}`",
        f"- Curated nodes: **{aggregates['total_nodes']}**",
        f"- Contract complete: **{aggregates['contract_complete']}**",
        f"- Contract repair required: **{aggregates['repair_required']}**",
        f"- Retained canonical capabilities: **{aggregates['retain_and_repair']}**",
        f"- Superseded operations awaiting migration/removal: **{aggregates['remove_superseded']}**",
        f"- Existing New Analysis templates: **{aggregates['existing_template_candidates']}**",
        f"  - Explicitly ready intent: **{aggregates['explicit_ready_template_intents']}**",
        f"  - Executable current project: **{aggregates['executed_template_projects']}**",
        f"  - Pending data: **{aggregates['pending_data_template_intents']}**",
        f"  - Pending qualification: **{aggregates['pending_qualification_template_intents']}**",
        f"  - WIP intent only: **{aggregates['wip_template_intents']}**",
        f"- Nodes present in an existing template: **{aggregates['nodes_in_existing_templates']}**",
        "- Nodes requiring a planned template addition or exact system-consumer proof: "
        f"**{aggregates['planned_or_system_coverage_required']}**",
        "",
        "Every disposition is explicit. `explicit_ready_intent`, `pending_data_intent`, "
        "`pending_qualification_intent`, and `intent_only_wip` mean a checked-in template uses "
        "the node; none certifies "
        "semantic validity or execution. `existing_execution` additionally binds the exact "
        "template to a named current-tree project proof, but does not by itself claim "
        "cross-platform qualification.",
        "",
        "| Node | Decision | Replacement | Family | Slice | Contract | "
        "Repair disposition | Project/consumer bindings |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for node in document["nodes"]:
        bindings = ", ".join(
            f"`{binding['consumer_id']}` ({binding['binding_status']})" for binding in node["consumer_bindings"]
        )
        contract = "complete" if node["contract_complete"] else "repair required"
        replacement = f"`{node['replacement_node_type']}`" if node["replacement_node_type"] else "—"
        lines.append(
            f"| `{node['node_type']}` | {node['retention_decision']} | {replacement} | "
            f"{node['family']} | {node['planned_slice']} | "
            f"{contract} | {node['repair_disposition']} | {bindings} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    package_root = Path(__file__).resolve().parents[1]
    repository_root = package_root.parents[1]
    evidence_dir = repository_root / "docs/evidence"
    json_path = evidence_dir / "canonical-node-project-repair-map.json"
    markdown_path = evidence_dir / "canonical-node-project-repair-map.md"
    document = build_map(repository_root)
    expected = {
        json_path: json.dumps(document, indent=2, sort_keys=True) + "\n",
        markdown_path: render_markdown(document),
    }
    if args.check:
        stale = [
            str(path)
            for path, content in expected.items()
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        if stale:
            raise SystemExit("stale canonical node project map: " + ", ".join(stale))
        return
    for path, content in expected.items():
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
