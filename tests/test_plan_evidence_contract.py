"""Keep the canonical-only plan's current evidence authority executable."""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLAN_PATH = _REPO_ROOT / "docs/plan/canonical-dag-managed-optimization-plan.md"
_CENSUS_PATH = _REPO_ROOT / "docs/evidence/m4-node-contract-census.json"
_ATTESTATION_PATH = _REPO_ROOT / "docs/evidence/managed-optimization-runtime-attestation.json"
_CURRENT_EVIDENCE_PATTERN = re.compile(
    r"<!-- managed-optimization-current-evidence\s+"
    r"registry_census_digest=(?P<census>[0-9a-f]{64})\s+"
    r"managed_optimization_profile_digest=(?P<profile>[0-9a-f]{64})\s+"
    r"managed_optimization_runtime_attestation_digest=(?P<attestation>[0-9a-f]{64})\s+"
    r"-->",
    re.MULTILINE,
)
_IMPLEMENTATION_RECORD_PATTERN = re.compile(
    r"^#### C2[^\n]* implementation record[^\n]*\n" r"(?P<body>.*?)(?=^#### |\Z)",
    re.MULTILINE | re.DOTALL,
)
_RELEASE_PLAN_PATH = _REPO_ROOT / "docs/plan/0.6-release-execution-plan.md"
_AVATAR_DISTRIBUTION_CONTRACT_PATH = _REPO_ROOT / "docs/plan/avatar-essential-oils-distribution-contract.md"
_DESKTOP_DELIVERY_PATH = _REPO_ROOT / "docs/plan/desktop-installer-delivery.md"
_OBSERVATION_B_RECORD_PATH = _REPO_ROOT / "docs/science/phase3-observation-b-record.md"
_OBSERVATION_B_PACKET_PATH = _REPO_ROOT / "docs/science/phase3-non-author-observer-packet.md"
_OBSERVATION_B_STAGING_PATH = _REPO_ROOT / "packages/spectra-ops/docs/PHASE3_OBSERVATION_B_STAGING.md"
_OBSERVATION_A_RECORD_PATH = _REPO_ROOT / "docs/science/phase3-observation-a-record.md"
_OBSERVATION_A_CLOSURE_PATH = _REPO_ROOT / "docs/evidence/phase3-observation-a-six-source-closure.json"
_CURRENT_GATE_STATUS_PATH = _REPO_ROOT / "docs/plan/0.6-current-gate-status.md"
_OBSERVATION_B_PREFLIGHT_PATH = _REPO_ROOT / "docs/evidence/phase3-observation-b-local-preflight.json"
_AUTHOR_CANDIDATE_RECEIPT_PATH = _REPO_ROOT / "docs/evidence/phase3-observation-b-author-candidate-369dd.json"
_CURRENT_OBSERVATION_B_SOURCE = "4094cfbf9aba40504446ac81956add1011db2db2"
_CURRENT_OBSERVATION_B_WHEEL_SIZE = 8429306
_CURRENT_OBSERVATION_B_WHEEL_SHA256 = "288d97dba735475819dcbc1842d1b7b3ed2b106bd09105bf20d71a3c0ba98cb4"
_CURRENT_OBSERVATION_B_SDIST_SIZE = 7944641
_CURRENT_OBSERVATION_B_SDIST_SHA256 = "112ad7b0505581072709adc44573cd229c305b80a173e756878dd630e920b34b"
_ARCHITECTURE_REPIN_MARKER = "REPIN_REQUIRED_AFTER_ARCHITECTURE_WORKSTREAM"
_AUTHOR_REHEARSAL_SOURCE = "369dd659a7a290d82903291980989575ad3aaa9c"


def test_plan_current_registry_evidence_matches_checked_artifacts() -> None:
    """The plan may not claim registry identities different from the tree."""

    plan = _PLAN_PATH.read_text(encoding="utf-8")
    matches = list(_CURRENT_EVIDENCE_PATTERN.finditer(plan))
    assert len(matches) == 1, "plan must contain exactly one current registry evidence authority block"

    census = json.loads(_CENSUS_PATH.read_text(encoding="utf-8"))
    attestation = json.loads(_ATTESTATION_PATH.read_text(encoding="utf-8"))
    claimed = matches[0].groupdict()

    assert claimed == {
        "census": census["registry_digest"],
        "profile": attestation["profile_digest"],
        "attestation": attestation["digest"],
    }

    records = list(_IMPLEMENTATION_RECORD_PATTERN.finditer(plan))
    assert records, "plan must retain ordered C2 implementation records"
    latest_record = records[-1].group(0)
    for name, digest in claimed.items():
        assert digest in latest_record, f"latest C2 implementation record does not contain current {name} digest"


def test_current_0_6_plan_keeps_owner_amended_release_scope_closed() -> None:
    """The trial stays mandatory while desktop delivery remains gated."""

    plan = _RELEASE_PLAN_PATH.read_text(encoding="utf-8")
    required_phases = [
        "Phase 1 — Release authority and Avatar distribution contract",
        "Phase 2 — Canonical scientist surface and campaign freeze",
        "Phase 3 — Non-author Avatar and first-value observations",
        "Phase 4 — Unattended public managed-compute trial",
        "Phase 5 — Signed desktop delivery in the 0.6.0 codebase",
        "Phase 6 — Final exact-SHA scientific and artifact qualification",
        "Phase 7 — Approval-gated publication and public-trial launch",
        "Phase 8 — Post-publication verification and closure",
    ]
    positions = [plan.index(phase) for phase in required_phases]
    assert positions == sorted(positions)

    required_scope = (
        "weekly and concurrent campaign quotas",
        "global compute/spend ceiling and kill switch",
        "provider-managed encrypted PostgreSQL",
        "Cross-provider/offsite immutable copies are deferred",
        "incident runbooks",
        "signed/notarized desktop lanes",
        "Mac and Windows developer-program authorities",
        "No signing credential, placeholder signature, unnotarized DMG",
        "pip-first",
        "CC BY 4.0",
        "Correction: None",
        "90 contracted\n   canonical nodes",
        "15 managed-optimization-eligible nodes",
        "Quantitative Calibration Campaign",
        "Categorical Classification Campaign",
        "PCA Exploration & Outlier Diagnostics",
        "PC1 versus PC2",
        "upstream_only_not_redistributed",
        "Prepare Supervised Dataset",
        "no customer-data upload",
        "BYOK Assistance Package",
        "BYOK chat, deterministic guidance, BYOK explanations, BYOK Data\n   Story drafting",
        "Managed Sherpa Advisor uses **Generative mode** by default",
        "no tab/project memory management,\n  tool calling, or automatic model-statistic/data/context injection",
        "Do **not** add a guided intake or template-routing wizard",
        "Keep BYOK stateless and text-only",
        "Never automatically attach raw data, spectra, sample tables, model\n   statistics",
        "Permit an allowlisted Advisor tool path to generate a workflow",
        "campaign may be created\n   only from the scientist-confirmed saved DAG",
        "Campaign Review Package",
        "OSS no-account inspector",
        "cannot create,\n   search, select, settle, resume, or rerun a campaign",
        "Enterprise Hybrid",
        "sovereign/no-egress\n     on-prem control plane remains a separate future delivery shape",
        "pip install 'spectra-sherpa[scp]'",
        "Dependency-aware qualification",
    )
    for authority in required_scope:
        assert authority in plan

    assert "not a `0.6.0` or `0.6.0rc1` publication gate" not in plan
    assert "0.6.0 does not publish until the signed desktop artifacts" not in plan
    assert "Build wheel/sdist and desktop artifacts from the frozen source" not in plan
    assert "Publish the signed desktop artifacts and manifest from the exact tag" not in plan

    desktop = _DESKTOP_DELIVERY_PATH.read_text(encoding="utf-8")
    assert "The OSS BYOK Assistance Package may expose simple chat" in desktop
    assert "BYOK has no tab/project memory management, tools, agent loop" in desktop
    assert "cannot silently alter scientific state" in desktop
    assert "Paid Sherpa Advisor Generative mode and managed optimization-campaign surfaces are absent" in desktop
    assert "Bundled AI credentials" in desktop


def test_observation_b_record_is_standalone_and_author_rehearsal_is_bounded() -> None:
    """The observer packet stays SHA-free while only the author candidate opens."""

    record = _OBSERVATION_B_RECORD_PATH.read_text(encoding="utf-8")
    packet = _OBSERVATION_B_PACKET_PATH.read_text(encoding="utf-8")
    staging = _OBSERVATION_B_STAGING_PATH.read_text(encoding="utf-8")
    status = _CURRENT_GATE_STATUS_PATH.read_text(encoding="utf-8")
    release_plan = _RELEASE_PLAN_PATH.read_text(encoding="utf-8")
    assert "Record the current executable pin" in record
    assert "Record the current executable pin" in packet
    assert f"export OBSERVATION_B_COMMIT='{_CURRENT_OBSERVATION_B_SOURCE}'" not in staging
    assert _AUTHOR_REHEARSAL_SOURCE in staging
    assert _AUTHOR_REHEARSAL_SOURCE in status
    assert _AUTHOR_REHEARSAL_SOURCE in release_plan
    assert "Exact candidate and closed Ubuntu deployment" in staging
    assert "candidate-status=passed" in staging
    assert "Registration remains closed" in staging
    assert "JF remains uninvited" in status
    assert "Registration remains closed until a distinct" in status
    assert "This development-only decision does not waive the" in release_plan
    assert _ARCHITECTURE_REPIN_MARKER in status
    assert _ARCHITECTURE_REPIN_MARKER in release_plan
    assert "Target-authority handoff correction closure" in release_plan
    normalized_staging = " ".join(staging.replace(">", "").split())
    assert "a distinct author identity" in normalized_staging
    assert "No additional Cloudflare or direct-origin narrowing is required" in normalized_staging
    assert "not author rehearsal or confirmation" in normalized_staging
    for handoff in (record, packet):
        assert _CURRENT_OBSERVATION_B_SOURCE not in handoff
        assert _CURRENT_OBSERVATION_B_WHEEL_SHA256 not in handoff
        assert "Provider-acquired Corn ZIP" in handoff
        assert "--registered-reference-projection public-corn-m5-moisture-v1" in handoff
    assert "python -m pip install --no-cache-dir" in record
    assert "poetry install" not in record
    assert "source checkout" in record
    assert "The observer must not\nneed a source checkout or another instruction document" in record
    for task in range(1, 8):
        assert f"### Task {task} —" in record
    assert "JF is the designated non-author scientist" in record
    assert "The owner does not require JF to provide or configure\na BYOK credential" in record
    assert "site profile `demo`" in record
    assert "Username `JF`" in record
    assert "ordinary and non-admin" in record
    assert "it is not a Pro subscription" in record
    assert "real six-digit signup-email round trip" in record
    assert "The operator immediately\n      returns registration to closed" in record
    assert "consumed exactly once" in record
    assert "Author-tester: Ye Feng" in record
    assert "readiness evidence only" in record
    assert "do not create or\nreserve username `JF`" in record
    assert "Confirm that no provider invocation or outbound provider payload occurs" in record
    assert "Configure the scientist-controlled provider" not in record
    assert "Exact BYOK outbound-payload finding:" not in record
    assert "Observer conclusion in the observer's own words:" in record
    assert "Non-author observer name / signature / date:" in record


def test_observation_a_record_retains_science_boundary_and_closed_viewer_remediation() -> None:
    record = _OBSERVATION_A_RECORD_PATH.read_text(encoding="utf-8")

    assert "This closes the six-source A1 scientific observation as a pass" in record
    assert "15bd7245e187815a0089690e57f02c4d94c06b9d" in record
    assert "956295da7d8de1881a288bee188e180e96cde98a" in record
    assert "accepted by JF and the\nowner" in record
    assert "Workbench usability improvements are a separate corrective" not in record
    assert "the complete 0.6.0 Observation A scope" in record
    assert "six-source closure record" in record
    assert "I did\n> not acquire or review a seventh repeat" in record
    assert "Correction was set to None" in record
    assert "No\nsignature, date of utterance, or additional observation is inferred" in record
    assert "Non-author observer signature / date:" in record


def test_observation_a_six_source_closure_is_bounded_and_exact() -> None:
    closure = json.loads(_OBSERVATION_A_CLOSURE_PATH.read_text(encoding="utf-8"))

    assert closure["schema_version"] == "spectra-phase3-observation-a-six-source-closure/1"
    assert closure["claim_scope"] == "spectra_sherpa_0_6_0_phase3_observation_a_six_source_exit"
    assert closure["accepted_evidence"]["archive_authorities"] == {
        "spa_sha256": "84fd799647a4a69782a33fda961b5a09119a5565225d9e11be1d08498aed8868",
        "csv_sha256": "438ab82b33463fcc0fcc690fe2830f9a94a84cedb955e91ad5ca2acdab1e60c1",
        "jdx_sha256": "b1cbb0d1eded802fcb99dc7184e8fc3c5163cf2cf93648bf2a45bd6018951069",
    }
    parity = closure["accepted_evidence"]["native_parser_parity"]
    assert parity["member_count"] == 18
    assert parity["spectrochempy_loaded"] is False
    assert parity["csv_synthetic_zero_endpoint_per_source"] == 1
    assert closure["accepted_evidence"]["jf_a2_statement"].endswith("I did not acquire or review a seventh repeat.")
    assert "Correction was set to None." in closure["accepted_evidence"]["operator_statement"]

    exit_record = closure["observation_a_exit"]
    assert exit_record["complete"] is True
    assert exit_record["accepted_source_count"] == 6
    assert exit_record["same_source_formats"] == ["spa", "csv", "jdx"]
    assert exit_record["historical_larger_acquisition_design_status"] == ("superseded_for_0_6_0_exit")
    assert exit_record["original_33_source_corpus_authority_unchanged"] is True
    assert closure["provenance"]["signature_status"] == "not_supplied_no_signature_inferred"
    assert "no_observation_b_execution" in closure["nonclaims"]


def test_observation_b_local_preflight_is_exact_and_does_not_claim_observation() -> None:
    receipt = json.loads(_OBSERVATION_B_PREFLIGHT_PATH.read_text(encoding="utf-8"))
    record = _OBSERVATION_B_RECORD_PATH.read_text(encoding="utf-8")
    status = _CURRENT_GATE_STATUS_PATH.read_text(encoding="utf-8")

    assert receipt["schema_version"] == "spectra-phase3-observation-b-local-preflight/1"
    assert receipt["claim_scope"] == "author_local_observation_b_readiness_only"
    assert receipt["candidate"] == {
        "source_revision": _CURRENT_OBSERVATION_B_SOURCE,
        "package_version": "0.6.0",
        "wheel_filename": "spectra_sherpa-0.6.0-py3-none-any.whl",
        "wheel_size": _CURRENT_OBSERVATION_B_WHEEL_SIZE,
        "wheel_sha256": _CURRENT_OBSERVATION_B_WHEEL_SHA256,
    }
    assert receipt["wheel_rebuild"]["byte_identity_matches_candidate"] is True
    assert receipt["wheel_rebuild"]["network_used"] is False
    assert receipt["wheel_rebuild"]["network_scope"] == "none_exact_local_build_backends"

    release_artifacts = receipt["release_artifact_qualification"]
    assert release_artifacts == {
        "source_export": "two_independent_git_archives_of_exact_source_revision",
        "release_tag": "spectra-sherpa-v0.6.0",
        "manifest_schema": "spectra-sherpa-release-artifacts/1",
        "wheel_filename": "spectra_sherpa-0.6.0-py3-none-any.whl",
        "wheel_size": _CURRENT_OBSERVATION_B_WHEEL_SIZE,
        "wheel_sha256": _CURRENT_OBSERVATION_B_WHEEL_SHA256,
        "sdist_filename": "spectra_sherpa-0.6.0.tar.gz",
        "sdist_size": _CURRENT_OBSERVATION_B_SDIST_SIZE,
        "sdist_sha256": _CURRENT_OBSERVATION_B_SDIST_SHA256,
        "independent_sdist_builds_byte_identical": True,
        "archive_content_inspection": "passed",
        "required_reader_license_notice_count": 4,
        "status": "passed",
    }

    qualification = receipt["public_install_profile_qualification"]
    assert qualification == {
        "report": "docs/evidence/public-install-profiles-s2a.json",
        "report_sha256": "102c54a1d1178446629d6ef352eea785927049691e95666ed0ccb4a2e61b6f14",
        "source_revision": _CURRENT_OBSERVATION_B_SOURCE,
        "poetry_lock_sha256": "1e405924cb4735539dfb82dabc0123d9cb45f080514a00cffc7f3c4c4c756ba5",
        "candidate_poetry_lock_matches_qualified_source": True,
        "candidate_distribution_tree_matches_qualified_source": True,
        "authority_scope": "current_candidate_lock_and_wheel_profiles",
        "candidate_wheel_sha256": _CURRENT_OBSERVATION_B_WHEEL_SHA256,
        "profile_count": 7,
        "all_profiles_passed": True,
        "network_used": True,
    }

    custody = receipt["private_handoff_custody"]
    assert custody["repository_content"] is False
    assert custody["all_members_present"] is True
    assert custody["all_member_hashes_match"] is True
    assert custody["all_members_owner_only_mode"] is True
    assert custody["backup_status"] == "not_observed_by_this_preflight"
    assert len(custody["members"]) == 5
    assert {member["role"] for member in custody["members"]} == {
        "wheel",
        "avatar_campaign_review_package",
        "corn_campaign_review_package",
        "avatar_fixture",
        "publisher_trust_anchors",
    }

    provider_reference = receipt["provider_acquired_reference"]
    assert provider_reference["sha256"] == ("8a2d1a03648b6ad334caaafa5d8377bf945ba1477a5082c4963d705d07cca795")
    assert provider_reference["registered_reference_projection"] == "public-corn-m5-moisture-v1"
    assert provider_reference["spectra_handoff_asset"] is False
    assert provider_reference["retrieved_or_redistributed_by_spectra"] is False

    phase2 = receipt["phase2_reference_qualification"]
    assert phase2["qualification_execution_source_revision"] == ("234896169ace442e65daceb74849569a880f7534")
    assert phase2["qualification_report_validator_source_revision"] == (_CURRENT_OBSERVATION_B_SOURCE)
    assert phase2["report_sha256"] == ("4c4523dbad98d8c4c8df182379b9ae50914e161803a42f8c0149fb9dd0d89f7f")
    assert phase2["provider_acquired_corn_projection_used"] is True
    assert phase2["all_journeys_passed"] is True

    assert receipt["workbench_smoke"]["status"] == "passed"
    parser = receipt["native_parser_preflight"]
    assert parser["source_count"] == 39
    assert parser["shape"] == [39, 1868]
    assert parser["common_axis_byte_identical"] is True
    assert parser["all_values_finite"] is True
    assert parser["warning_count"] == 0

    for journey in receipt["no_account_reproduction"].values():
        assert journey["integrity_verified"] == "passed"
        assert journey["publisher_authenticated"] == "passed"
        assert journey["validation_reproduced"] == "passed"
        assert journey["fold_metric_matches"] == [True, True, True]
        assert journey["pooled_metric_match"] is True
        assert journey["application_reproduced"] == "passed"

    assert receipt["operator_authority"]["non_author_scientist_participated"] is False
    for nonclaim in (
        "no_non_author_observation_or_signature",
        "no_managed_campaign_execution",
        "no_paid_sherpa_advisor_observation",
        "no_byok_provider_interaction",
        "no_phase3_exit_closure",
        "no_publication_or_registration_activation",
    ):
        assert nonclaim in receipt["nonclaims"]

    for document in (record, status):
        assert "phase3-observation-b-local-preflight.json" in document
    assert "the receipt is not the non-author\nobservation or a Phase 3 exit" in record
    assert "The receipt does not\nreplace the demo-profile account, managed surface" in status


def test_observation_b_historical_preflight_stays_exact_after_new_repin() -> None:
    """The last receipt remains truthful but cannot authorize changed code."""

    receipt = json.loads(_OBSERVATION_B_PREFLIGHT_PATH.read_text(encoding="utf-8"))
    runtime_tree = receipt["candidate_runtime_tree"]
    assert runtime_tree["source_revision"] == _CURRENT_OBSERVATION_B_SOURCE
    assert runtime_tree["algorithm"] == "sha256(path-nul-file-sha256-newline)"
    assert runtime_tree["file_count"] == 1405
    assert runtime_tree["sha256"] == "686a95cf6eee424e16909249fdb3fd2406cd9d92d3ef9457d91b5ce40706b1ca"

    staging = _OBSERVATION_B_STAGING_PATH.read_text(encoding="utf-8")
    status = _CURRENT_GATE_STATUS_PATH.read_text(encoding="utf-8")
    release_plan = _RELEASE_PLAN_PATH.read_text(encoding="utf-8")
    assert f"export OBSERVATION_B_COMMIT='{_CURRENT_OBSERVATION_B_SOURCE}'" not in staging
    assert _AUTHOR_REHEARSAL_SOURCE in staging
    assert _AUTHOR_REHEARSAL_SOURCE in status
    assert _CURRENT_OBSERVATION_B_SOURCE in status
    assert _ARCHITECTURE_REPIN_MARKER in release_plan
    assert "Reference package/Data Views execution and Observation B repin" in release_plan


def test_observation_b_handoff_is_post_publication_not_deployment_prerequisite() -> None:
    staging = _OBSERVATION_B_STAGING_PATH.read_text(encoding="utf-8")
    status = _CURRENT_GATE_STATUS_PATH.read_text(encoding="utf-8")
    release_plan = _RELEASE_PLAN_PATH.read_text(encoding="utf-8")
    record = _OBSERVATION_B_RECORD_PATH.read_text(encoding="utf-8")
    checklist = (_REPO_ROOT / "docs/science/phase3-observation-b-scientist-checklist.md").read_text(encoding="utf-8")
    assert "exact-commit artifact/runtime receipt" in staging
    normalized_staging = " ".join(staging.split())
    assert "two signed Campaign Review Packages are produced only" in normalized_staging
    assert "after the author runs the application/refit" in normalized_staging
    assert "The author rehearsal must also close the private observer handoff" in staging
    assert "before inviting JF" in status
    assert "post-publication author-rehearsal output" in status
    assert (
        "pre-deployment artifact/runtime receipt, staging runbook,\n"
        "and current gate status before the author-only staging deployment" in release_plan
    )
    assert "no-account journeys must pass before JF is invited" in release_plan
    assert "**author-rehearsal** Avatar campaign for pre-JF readiness only" in record
    assert "**JF downloaded in Task 2**, not the author's preflight" in record
    assert "not the author's preflight packages" in checklist


def test_author_candidate_receipt_binds_deployment_without_waiving_later_gates() -> None:
    receipt = json.loads(_AUTHOR_CANDIDATE_RECEIPT_PATH.read_text(encoding="utf-8"))
    staging = _OBSERVATION_B_STAGING_PATH.read_text(encoding="utf-8")
    status = _CURRENT_GATE_STATUS_PATH.read_text(encoding="utf-8")
    release_plan = _RELEASE_PLAN_PATH.read_text(encoding="utf-8")

    assert receipt["schema_version"] == "spectra-phase3-observation-b-author-candidate/1"
    assert receipt["source_revision"] == _AUTHOR_REHEARSAL_SOURCE
    assert receipt["release_artifacts"]["wheel"]["sha256"] == (
        "bfdc255a0e93a6c79f9269d9456de953b646066575eb6d47e9167bb609906052"
    )
    assert receipt["release_artifacts"]["sdist"]["sha256"] == (
        "fa4a291a6398f90fd7ad3f8dd89500b8dd279f4f95ec9ec7aba60f9f21529af1"
    )
    assert receipt["canonical_node_pair"]["macos_test_count"] == 1542
    assert receipt["canonical_node_pair"]["ubuntu_test_count"] == 1542
    assert receipt["canonical_node_pair"]["node_count"] == 91
    assert receipt["staging"]["controller_result"] == "candidate-status=passed"
    assert receipt["staging"]["registration_enabled"] is False
    assert receipt["staging"]["jf_username_unused"] is True
    assert receipt["staging"]["author_staging_ingress_policy"] == (
        "owner_accepts_existing_ip_based_access_without_additional_narrowing"
    )
    assert receipt["staging"]["external_network_access_restriction_independently_attested"] is False
    assert "verified_owner_jf_proxy_and_origin_ingress_before_jf_invitation" in receipt["pending_gates"]
    assert "not_a_predeployment_receipt" in receipt["nonclaims"]
    assert "not_an_access_restriction_attestation" in receipt["nonclaims"]
    assert (
        "seven_exact_candidate_public_install_profiles_after_author_rehearsal_before_jf_invitation"
        in receipt["pending_gates"]
    )
    for document in (staging, status, release_plan):
        assert "phase3-observation-b-author-candidate-369dd.json" in document
        assert _AUTHOR_REHEARSAL_SOURCE in document
    normalized_plan = " ".join(release_plan.split())
    assert normalized_plan.index("closed Ubuntu staging deployment and exact-commit artifact/node qualification") < (
        normalized_plan.index("seven exact-candidate public installation profiles follow the")
    )
    normalized_staging = " ".join(staging.replace(">", "").split())
    assert "The owner accepts the existing IP-based staging policy" in normalized_staging
    assert "bounded author signup" in staging
    assert "historical/recovery-only preparation sequence" in normalized_staging
    assert "update the candidate receipt before author signup" in normalized_staging
    assert "For an ordinary non-mutating check, run `status` instead" in normalized_staging
    assert "Wait for the scientist to receive and consume the emailed code" in normalized_staging
    assert staging.count("export OBSERVATION_B_COMMIT='369dd659a7a290d82903291980989575ad3aaa9c'") == 3
    assert "No additional Cloudflare or direct-origin narrowing is required" in normalized_staging
    assert "JF-specific owner/JF ingress restriction" in normalized_staging
    assert "all seven public install profiles have passed on the exact candidate" in normalized_staging
    assert "the source, wheel SHA-256, and profile-report identity recorded" in normalized_staging


def test_current_gate_status_keeps_external_work_and_publication_locked() -> None:
    status = _CURRENT_GATE_STATUS_PATH.read_text(encoding="utf-8")
    plan_index = (_REPO_ROOT / "docs/plan/README.md").read_text(encoding="utf-8")
    project_memory = (_REPO_ROOT / "docs/dev/spectra-monorepo-project-memory.md").read_text(encoding="utf-8")
    release = (_REPO_ROOT / "packages/spectra-sherpa/docs/releases/0.6.0.md").read_text(encoding="utf-8")

    for authority in (
        "0.6.0 is the single code and documentation line",
        "signed/notarized desktop installer lanes, commercial and Hybrid paths",
        "Observation A is complete",
        "six-source closure record",
        "Observation B has not been executed",
        "provider-acquired local Campaign\n" "Review reproduction path, total dataset/template compatibility insertion",
        "JF is the named non-author scientist",
        "Ye Feng must execute the exact thirteen-task procedure",
        "JF does not need a BYOK\ncredential",
        "live Resend authority; Stripe is neither required nor accepted by 0.6.0",
        "temporary paid isolated PostgreSQL\n  restore",
        "official same-commit Ubuntu producer/macOS OSS consumer M4.20",
        "No tag, public push, dataset upload, PyPI upload",
        "c0fe77e3125a353bdfed6854d98e1313cf670eb5",
        "41e0a3093f8ab341a34ce72edba3d4eb16cdf0c8",
    ):
        assert authority in status
    assert "0.6.0 Current Gate Status" in plan_index
    assert "Access-code registration" not in project_memory
    assert "Six-digit single-use email-passcode registration" in project_memory
    assert "eventual signed release artifact" not in release
    assert "Desktop installers for Windows, macOS and Ubuntu will be verified separately" in release
    assert "their publication is not part of this source and PyPI release" in release
    assert "Signed/notarized desktop installers ship with 0.6.0" not in release


def test_avatar_distribution_contract_records_exact_nonpublishing_phase1_preflight() -> None:
    contract = _AVATAR_DISTRIBUTION_CONTRACT_PATH.read_text(encoding="utf-8")
    for authority in (
        "171b74c2abca681d47d65b286629492b9435832ca3aac200504cc4ee125ca85a",
        "524960aed6d2ef8294a7ffed0056f7287a38b611462c12599fc2bd7cf1222db2",
        "85bd5906d85bd7879602a87937d63c90dab8cafb01d1737a3923677b732a9019",
        "a6025aa78f5edddd0d66c5b7889d911d0b25bae953e873e7107cb10189350a4e",
        "Correction: None",
        "Lavender Essential Oil FTIR Corpus v1",
        "Creator:** Ye Feng",
        "Licensor:** Spectra Scientific LLC",
        "original unpublished laboratory dataset",
        "no external publication citation",
        "exactly 41 regular members",
        "archive created: `false`",
        "83623f4f89a6832a3db70060e76d8f91dcc8657321447b17c0ccb5736631babe",
        "built the complete private candidate twice",
        "42565d51e2969c26ee24171f848ff9c3ab5cb429cd6250568993dffa738cd05c",
        "privacy review complete: `true`",
        "Phase 1 is complete",
        "Publication remains an explicit approval-gated Phase 7 action",
    ):
        assert authority in contract

    assert "Phase 1 distribution-qualified; owner privacy/package approval\n  recorded" in contract
