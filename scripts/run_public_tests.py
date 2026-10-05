#!/usr/bin/env python3
"""Run the standalone OSS test profile without upstream release authorities.

The public repository is an object-faithful copy of the OSS subtree, so it
contains qualification tests whose checked evidence deliberately remains
outside the public distribution. Those modules are executed by upstream CI and
cannot run standalone. This closed profile excludes only named upstream-authority modules
or node IDs; every other OSS test runs on Ubuntu, macOS, and Windows.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

UPSTREAM_AUTHORITY_MODULES = (
    "tests/test_avatar_essential_oils_distribution.py",
    "tests/test_avatar_omnic_canonical_dataset.py",
    "tests/test_avatar_omnic_corpus.py",
    "tests/test_avatar_omnic_phase53c_portability.py",
    "tests/test_avatar_omnic_phase6_pca.py",
    "tests/test_avatar_omnic_reproducibility.py",
    "tests/test_avatar_omnic_workbench_journey.py",
    "tests/test_canonical_node_project_map.py",
    "tests/test_canonical_registry_authority.py",
    "tests/test_dataset_axis_constructor_census.py",
    "tests/test_native_omnic_ingestion.py",
    "tests/test_native_opus_qualification.py",
    "tests/test_native_opus_reader.py",
    "tests/test_native_spc_reader.py",
    "tests/test_node_readiness_audit.py",
    "tests/test_plan_evidence_contract.py",
    "tests/test_scientific_authority.py",
    "tests/test_scp_ingestion_reachability.py",
    "tests/test_unified_matlab_dso_qualification.py",
)

UPSTREAM_AUTHORITY_NODE_IDS = (
    "tests/test_avatar_omnic_phase8_application.py::test_checked_phase8_report_is_closed_and_exact",
    "tests/test_collection_definition.py::test_checked_avatar_definition_binds_phase4_projection",
    "tests/test_core_runtime_profile.py::test_retained_baseline_preserves_its_historical_harness_and_lock",
    "tests/test_core_runtime_profile.py::test_s1b_profile_advances_from_orm_metadata_to_artifact_capability",
    "tests/test_core_runtime_profile.py::test_s1d_profile_is_a_commit_bound_native_runtime_proof",
    "tests/test_data_format_capabilities.py::test_current_plan_capability_block_matches_live_registry_and_contracts",
    "tests/test_native_vendor_conformance_guards.py::test_every_bundled_vendor_fixture_has_exact_fail_closed_attribution",
    "tests/test_native_vendor_conformance_guards.py::test_opusreader2_attribution_refuses_an_unpinned_upstream",
    "tests/test_native_vendor_conformance_guards.py::test_scp_ci_runs_every_native_reader_with_required_external_corpus",
    "tests/test_native_wdf_reader.py::test_external_wdf_conformance_binds_full_science_and_sample_identity",
    "tests/test_node_catalog_contract.py::test_census_is_complete_deterministic_and_matches_checked_baseline",
    "tests/test_node_catalog_contract.py::test_census_classifies_the_entire_catalog_against_the_managed_optimization_profile",
    "tests/test_node_catalog_contract.py::test_current_catalog_authority_contains_no_retired_ambiguous_profile_terms",
    "tests/test_package_metadata_profiles.py::test_retained_public_profile_qualification_is_commit_and_lock_bound",
    "tests/test_phase7_classification_authority.py::test_phase7_ast_gate_accepts_the_current_repository",
    "tests/test_presentation_contract.py::test_live_presentation_census_matches_checked_authority",
    "tests/test_scientific_core_import_boundary.py::test_post_664_coupling_inventory_matches_source_exactly",
    "tests/test_scientific_values.py::test_live_scientific_output_census_matches_checked_authority",
    "tests/test_validation_graph.py::test_checked_runtime_attestation_names_the_profile_pins",
)

_PRIVATE_AUTHORITY_SIGNALS = (
    "docs/evidence",
    "docs/plan",
    "docs/science",
    "private-input",
    "packages/spectra-server",
    "tools/scientific_authority.py",
    "parents[3]",
)


def profile_failures() -> list[str]:
    failures: list[str] = []
    if len(set(UPSTREAM_AUTHORITY_MODULES)) != len(UPSTREAM_AUTHORITY_MODULES):
        failures.append("duplicate upstream-authority module")
    if len(set(UPSTREAM_AUTHORITY_NODE_IDS)) != len(UPSTREAM_AUTHORITY_NODE_IDS):
        failures.append("duplicate upstream-authority node id")

    for relative in UPSTREAM_AUTHORITY_MODULES:
        path = PACKAGE_ROOT / relative
        if not path.is_file() or path.is_symlink():
            failures.append(f"invalid upstream-authority module:{relative}")
            continue
        source = path.read_text(encoding="utf-8")
        if not any(signal in source for signal in _PRIVATE_AUTHORITY_SIGNALS):
            failures.append(f"module has no private-authority signal:{relative}")

    for node_id in UPSTREAM_AUTHORITY_NODE_IDS:
        relative, separator, function = node_id.partition("::")
        path = PACKAGE_ROOT / relative
        if not separator or not function.startswith("test_"):
            failures.append(f"invalid upstream-authority node id:{node_id}")
            continue
        if not path.is_file() or path.is_symlink():
            failures.append(f"missing upstream-authority node module:{relative}")
            continue
        source = path.read_text(encoding="utf-8")
        if f"def {function}(" not in source:
            failures.append(f"missing upstream-authority test function:{node_id}")
    return failures


def pytest_arguments() -> list[str]:
    arguments = ["tests", "-v", "--no-cov"]
    arguments.extend(f"--ignore={relative}" for relative in UPSTREAM_AUTHORITY_MODULES)
    arguments.extend(f"--deselect={node_id}" for node_id in UPSTREAM_AUTHORITY_NODE_IDS)
    return arguments


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    failures = profile_failures()
    if failures:
        for failure in failures:
            print(f"public test profile refused: {failure}")
        return 2
    print(
        "public test profile: "
        f"{len(UPSTREAM_AUTHORITY_MODULES)} upstream-authority modules and "
        f"{len(UPSTREAM_AUTHORITY_NODE_IDS)} upstream-authority node IDs excluded; "
        "all remaining OSS tests required"
    )
    if args.validate_only:
        return 0
    return pytest.main(pytest_arguments())


if __name__ == "__main__":
    raise SystemExit(main())
