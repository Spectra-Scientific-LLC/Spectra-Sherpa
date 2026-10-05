"""Live-registry catalog and census contract tests."""

from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.api.v1.routes.workflows.catalog import get_node_library
from spectra_sherpa.app.services.dag import node_catalog_contract, node_registry
from spectra_sherpa.app.services.dag.catalog_presentation import CANONICAL_CATALOG_FAMILIES
from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
from spectra_sherpa.app.services.dag.node_base import NodeMetadata
from spectra_sherpa.app.services.dag.node_catalog_contract import (
    NODE_CONTRACT_CENSUS_SCHEMA_VERSION,
    build_node_contract_census,
    census_digest,
    node_library_cache_identity,
    render_census_markdown,
    validate_census_help_references,
)
from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract, RuntimeFamily
from spectra_sherpa.sdk.execution_contract import RuntimeFamily as PublicSDKRuntimeFamily

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_BASELINE_PATH = _REPOSITORY_ROOT / "docs" / "evidence" / "m4-node-contract-census.json"
_REPORT_PATH = _REPOSITORY_ROOT / "docs" / "evidence" / "m4-node-contract-census.md"
_TOOLS_PATH = Path(__file__).resolve().parents[1] / "tools"
_SOURCE_PATH = Path(__file__).resolve().parents[1] / "src"
_SCP_OPERATIONS = {
    "model.efa",
    "model.mcr_als",
    "model.simplisma",
}


def test_live_catalog_and_sdk_share_the_exact_closed_vocabulary() -> None:
    assert RuntimeFamily is PublicSDKRuntimeFamily


def test_builtin_catalog_uses_coherent_scientist_families() -> None:
    counts: dict[str, int] = {}
    for metadata in node_registry.list_catalog_nodes():
        counts[metadata.category] = counts.get(metadata.category, 0) + 1

    assert counts == {
        "classification": 6,
        "clustering": 3,
        "data": 8,
        "deploy": 3,
        "exploratory": 10,
        "output": 4,
        "preprocessing": 18,
        "regression": 12,
        "selection": 11,
        "synthesis": 14,
        "time_series": 2,
        "transfer": 4,
        "validation": 6,
    }
    assert set(counts) == CANONICAL_CATALOG_FAMILIES
    assert not ({"custom", "diagnostics", "modeling"} & counts.keys())
    assert node_registry.get_catalog_metadata("data.merge_features").category == "data"
    assert node_registry.get_catalog_metadata("selection.select_columns").category == "selection"

    fit = node_registry.get_catalog_metadata("model.fitted_pls")
    apply = node_registry.get_catalog_metadata("model.apply_fitted_pls")
    assert fit.category == apply.category == "regression"
    assert fit.label == "Fit PLS1 / PLS2 Regression (SIMPLS)"
    assert apply.label == "Apply PLS1 / PLS2 Model (SIMPLS)"
    assert "One response is PLS1; multiple responses are PLS2" in fit.description


def test_node_library_cache_identity_tracks_visible_taxonomy_and_copy() -> None:
    metadata = node_registry.get_catalog_metadata("model.fitted_pls")
    original = node_library_cache_identity([metadata])

    assert node_library_cache_identity([replace(metadata, category="exploratory")]) != original
    assert node_library_cache_identity([replace(metadata, label="Changed label")]) != original
    assert node_library_cache_identity([replace(metadata, description="Changed purpose")]) != original


def test_internal_binding_and_source_identity_fields_are_not_scientist_parameters() -> None:
    internal_markers = (
        "artifact_digest",
        "serializer",
        "source_contract_digest",
        "state_node_id",
        "state_digest",
        "state_content_digest",
        "source_manifest_sha256",
        "collection_definition_sha256",
        "scientific_collection_sha256",
        "target_authority",
    )
    exposed = [
        (metadata.node_type, parameter.name)
        for metadata in node_registry.list_nodes()
        for parameter in metadata.parameters
        if parameter.name in internal_markers and parameter.category != "internal"
    ]

    assert exposed == []


@pytest.mark.parametrize(
    "generator_name",
    [
        "generate_node_contract_census.py",
        "generate_managed_optimization_runtime_attestation.py",
        "generate_scientific_output_semantics_census.py",
    ],
)
def test_registry_generators_import_their_own_checkout(generator_name: str) -> None:
    """Evidence generation must not resolve an editable package from another worktree.

    Every such generator must, in order: (1) put its own checkout on
    ``sys.path`` via the shared ``tools/_provenance.py`` helper before
    importing ``spectra_sherpa``, and (2) verify the import actually
    resolved there afterward — path insertion alone does not prove it won
    against a shadowing editable install elsewhere. See manifest.md §4 and
    tools/_provenance.py.
    """

    generator = _TOOLS_PATH / generator_name
    source = generator.read_text(encoding="utf-8")
    path_setup = "ensure_local_checkout_on_path(__file__)"
    first_package_import = "import spectra_sherpa"
    verification = "require_local_checkout(_PACKAGE_ROOT)"

    assert path_setup in source
    assert verification in source
    assert source.index(path_setup) < source.index(first_package_import) < source.index(verification)


def test_census_is_complete_deterministic_and_matches_checked_baseline() -> None:
    census = build_node_contract_census(node_registry.list_nodes())
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    assert census["schema_version"] == NODE_CONTRACT_CENSUS_SCHEMA_VERSION
    assert [row["node_type"] for row in census["nodes"]] == sorted(row["node_type"] for row in census["nodes"])
    assert len(census["nodes"]) == len({row["node_type"] for row in census["nodes"]})
    assert census["aggregates"] == baseline["aggregates"]
    if census_digest(census) != baseline["registry_digest"]:
        actual_by_type = {row["node_type"]: row for row in census["nodes"]}
        expected_by_type = {row["node_type"]: row for row in baseline["nodes"]}
        changed = {
            node_type: {"actual": actual_by_type.get(node_type), "expected": expected_by_type.get(node_type)}
            for node_type in sorted(set(actual_by_type) | set(expected_by_type))
            if actual_by_type.get(node_type) != expected_by_type.get(node_type)
        }
        pytest.fail(f"live node census differs from the checked baseline: {changed}")
    assert census_digest(census) == baseline["registry_digest"]
    assert _REPORT_PATH.read_text(encoding="utf-8") == render_census_markdown(census)


def test_execution_contract_source_components_are_platform_neutral() -> None:
    """External packages are version-bound, never source-byte-bound.

    NumPy and scikit-learn ship platform-specific Python source shims. Hashing
    those installed files made otherwise identical contracts drift on Windows.
    In-tree source remains exact; external authority is the reviewed pinned
    distribution version declared by the same contract.
    """

    for metadata in node_registry.list_nodes():
        contract = metadata.resolved_execution_contract()
        assert contract is not None
        for component in contract.payload["implementation_components"]:
            component_id = component["component_id"]
            assert component_id.startswith(("spectra_sherpa.", "distribution.")), (
                metadata.node_type,
                component_id,
            )


def test_census_rejects_duplicate_node_types() -> None:
    metadata = NodeMetadata(node_type="_test.same", category="test", label="Same", description="")
    with pytest.raises(ValueError, match="exactly once"):
        build_node_contract_census([metadata, metadata])


def test_every_contract_help_reference_resolves_and_names_its_operation() -> None:
    census = build_node_contract_census(node_registry.list_nodes())

    validate_census_help_references(census, package_root=Path(__file__).resolve().parents[1])


def test_help_reference_gate_rejects_one_dangling_mutation() -> None:
    census = build_node_contract_census(node_registry.list_nodes())
    mutated = json.loads(json.dumps(census))
    mutated["nodes"][0]["execution_contract"]["payload"]["help_reference"] = "docs/nodes/missing.md"

    with pytest.raises(ValueError, match="help target does not exist"):
        validate_census_help_references(mutated, package_root=Path(__file__).resolve().parents[1])


def test_census_classifies_the_entire_catalog_against_the_managed_optimization_profile() -> None:
    census = build_node_contract_census(node_registry.list_nodes())
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    profile = managed_optimization_profile()
    rows = {row["node_type"]: row for row in census["nodes"]}
    eligible = {node_type for node_type, row in rows.items() if row["managed_optimization_profile"]["eligible"]}

    assert eligible == profile.operation_ids
    assert census["aggregates"]["managed_optimization_profile_eligible"] == len(eligible)
    assert census["aggregates"]["outside_managed_optimization_profile"] == len(rows) - len(eligible)
    assert census["aggregates"]["managed_optimization_profile_eligible"] == 18
    assert census["aggregates"]["outside_managed_optimization_profile"] == 83
    assert "diagnostics.labeled_regression_evaluator" in rows.keys() - eligible
    assert census["aggregates"]["managed_optimization_profile_contract_drift"] == 0
    assert census["aggregates"]["contracted_nodes"] == baseline["aggregates"]["contracted_nodes"]
    artifact_application_nodes = {
        node_type
        for node_type, row in rows.items()
        if row["catalog_classification"]["lifecycle_kind"] == "artifact_application"
    }
    assert artifact_application_nodes == {
        "classification.apply_knn",
        "classification.apply_plsda",
        "classification.apply_simca",
        "model.apply_fitted_pls",
        "model.apply_fitted_pcr",
        "model.apply_fitted_svr",
        "model.apply_fitted_linear_regression",
        "model.load_apply",
        "model.pca_transform",
        "model.predict_regression",
        "preprocess.apply_fitted_emsc",
        "preprocess.apply_fitted_msc",
        "preprocess.apply_fitted_osc",
        "preprocess.apply_fitted_scale",
        "transfer.apply_fitted",
    }
    assert census["aggregates"]["artifact_application_nodes"] == len(artifact_application_nodes)
    for row in rows.values():
        profile_row = row["managed_optimization_profile"]
        classification = row["catalog_classification"]
        assert profile_row["profile_id"] == profile.profile_id
        assert profile_row["profile_version"] == profile.profile_version
        assert profile_row["profile_digest"] == profile.digest
        assert isinstance(profile_row["reason"], str) and profile_row["reason"]
        assert classification["managed_optimization_eligible"] is profile_row["eligible"]
        assert classification["runtime_family"]
        assert classification["lifecycle_kind"]
        assert classification["typed_port_status"] in {
            "typed_input_output",
            "typed_input_only",
            "typed_output_only",
            "untyped",
        }
        assert classification["reason"] == profile_row["reason"]

    assert rows["data.file_load"]["managed_optimization_profile"] == {
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "profile_digest": profile.digest,
        "eligible": False,
        "reason": "outside_managed_optimization_profile",
    }
    assert rows["data.file_load"]["catalog_classification"] == {
        "contract_status": "contracted",
        "runtime_family": "sherpa_native",
        "lifecycle_kind": "data_source",
        "typed_port_status": "typed_input_output",
        "managed_optimization_eligible": False,
        "reason": "outside_managed_optimization_profile",
    }


def test_census_reports_registry_contract_drift_as_local_only() -> None:
    metadata = node_registry.get_metadata("model.fitted_pls")
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    payload = contract.as_dict()
    payload["implementation_version"] = "9.9.9"
    drifted = replace(metadata, execution_contract=NodeExecutionContract.from_dict(payload))

    row = build_node_contract_census([drifted])["nodes"][0]

    assert row["managed_optimization_profile"]["eligible"] is False
    assert row["managed_optimization_profile"]["reason"] == "managed_optimization_profile_contract_drift"
    assert row["catalog_classification"]["managed_optimization_eligible"] is False
    assert row["catalog_classification"]["reason"] == "managed_optimization_profile_contract_drift"


def test_current_catalog_authority_contains_no_retired_ambiguous_profile_terms() -> None:
    """Keep canonical-DAG identity separate from managed-optimization admission."""

    retired_terms = (
        "outside_" + "canonical_profile",
        "managed_" + "eligibility",
        "managed_" + "profiles",
        "canonical_" + "registry_profile",
    )
    current_paths = [
        *_SOURCE_PATH.rglob("*.py"),
        *_TOOLS_PATH.glob("*.py"),
        Path(__file__),
        _BASELINE_PATH,
        _REPORT_PATH,
        _REPOSITORY_ROOT / "docs" / "evidence" / "managed-optimization-runtime-attestation.json",
    ]
    violations = {
        str(path.relative_to(_REPOSITORY_ROOT)): sorted(
            term for term in retired_terms if term in path.read_text(encoding="utf-8")
        )
        for path in current_paths
        if any(term in path.read_text(encoding="utf-8") for term in retired_terms)
    }
    assert violations == {}


def test_scp_availability_is_derived_only_from_execution_contracts() -> None:
    assert "requires_scp" not in {item.name for item in fields(NodeMetadata)}

    projected = {metadata.node_type for metadata in node_registry.list_nodes() if metadata.requires_scp}
    assert projected == _SCP_OPERATIONS
    for metadata in node_registry.list_nodes():
        contract = metadata.resolved_execution_contract()
        assert contract is not None
        distributions = {item["distribution"] for item in contract.payload["runtime_requirements"]}
        assert metadata.requires_scp is ("spectrochempy" in distributions)

    with pytest.raises(TypeError, match="requires_scp"):
        NodeMetadata(
            node_type="_test.node",
            category="test",
            label="Node",
            description="",
            requires_scp=True,  # type: ignore[call-arg]
        )


def test_scp_dependency_readiness_is_bounded_and_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    metadata = node_registry.get_metadata("model.efa")
    monkeypatch.setattr(
        node_catalog_contract,
        "distribution_is_installed",
        lambda distribution: distribution != "spectrochempy",
    )
    readiness = node_catalog_contract.dependency_readiness(metadata)
    assert readiness.ready is False
    assert readiness.blockers == ("spectrochempy_unavailable",)
    assert readiness.remediation == ("Install the optional SpectroChemPy support: pip install 'spectra-sherpa[scp]'.",)


@pytest.mark.asyncio
async def test_node_library_exposes_exact_contract_and_dependency_projections() -> None:
    class _User:
        id = 1

    response = await get_node_library(current_user=_User())
    assert response.contract_schema_version == "spectra-node-library/8"
    assert len(response.registry_digest) == 64
    assert response.cache_identity.endswith(response.registry_digest)

    data_node = next(node for node in response.nodes if node.node_type == "data.file_load")
    assert data_node.execution_contract is not None
    assert data_node.execution_contract.payload["runtime_family"] == "sherpa_native"
    assert data_node.execution_contract.payload["managed_optimization_eligibility"] == ["local"]
    assert data_node.dependency_readiness.ready is True
    assert data_node.requires_scp is False
    assert data_node.catalog_classification.lifecycle_kind == "data_source"
    assert data_node.catalog_classification.managed_optimization_eligible is False
    assert data_node.managed_optimization_profile.eligible is False
    assert data_node.managed_optimization_profile.reason == "outside_managed_optimization_profile"

    model_node = next(node for node in response.nodes if node.node_type == "model.fitted_pls")
    assert model_node.category == "regression"
    assert model_node.label == "Fit PLS1 / PLS2 Regression (SIMPLS)"
    assert model_node.execution_contract is not None
    assert (
        model_node.execution_contract.digest
        == node_registry.get_metadata("model.fitted_pls").resolved_execution_contract().digest
    )
    assert model_node.execution_contract.payload["operation_id"] == "model.fitted_pls"
    presentation = node_registry.get_metadata("model.fitted_pls").resolved_presentation_contract()
    assert presentation is not None
    assert model_node.presentation_contract is not None
    assert model_node.presentation_contract.digest == presentation.digest
    assert model_node.presentation_contract.payload == presentation.as_dict()

    scp_node = next(node for node in response.nodes if node.node_type == "model.efa")
    assert scp_node.requires_scp is True
    assert scp_node.execution_contract is not None
    assert {
        requirement["distribution"] for requirement in scp_node.execution_contract.payload["runtime_requirements"]
    } >= {"spectrochempy"}


@pytest.mark.asyncio
async def test_node_library_catalog_projection_is_exactly_the_live_census() -> None:
    class _User:
        id = 1

    response = await get_node_library(current_user=_User())
    census = build_node_contract_census(node_registry.list_nodes())
    rows = {row["node_type"]: row for row in census["nodes"]}

    assert {node.node_type for node in response.nodes} == set(rows)
    for node in response.nodes:
        row = rows[node.node_type]
        assert node.requires_scp is row["requires_scp"]
        assert node.catalog_classification.model_dump() == row["catalog_classification"]
        assert node.managed_optimization_profile.model_dump() == row["managed_optimization_profile"]
