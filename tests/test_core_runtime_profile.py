"""Contract tests for the internal R1 clean-room runtime harness."""

from __future__ import annotations

import ast
import importlib.util
import json
import socket
import sys
from pathlib import Path

import numpy as np
import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PACKAGE_ROOT / "scripts" / "core_runtime_profile.py"
WORKBENCH_SMOKE_PATH = PACKAGE_ROOT / "scripts" / "workbench_runtime_smoke.py"


def _load_profile_module():
    spec = importlib.util.spec_from_file_location("spectra_core_runtime_profile", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


profile = _load_profile_module()


def _load_workbench_smoke_module():
    spec = importlib.util.spec_from_file_location("spectra_workbench_runtime_smoke", WORKBENCH_SMOKE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


workbench_smoke = _load_workbench_smoke_module()


def test_canonical_bridge_keeps_application_runtime_import_lazy() -> None:
    source = (PACKAGE_ROOT / "src/spectra_sherpa/app/services/canonical_model_bridge.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "spectra_sherpa.app.services.execution_runtime"
        for node in tree.body
    )
    assert source.count("from spectra_sherpa.app.services.execution_runtime import ApplicationModelArtifactReplay") == 1


def test_current_runtime_profile_tracks_only_the_three_retained_scp_algorithms() -> None:
    from spectra_sherpa.app.services.dag import nodes as _nodes  # noqa: F401
    from spectra_sherpa.app.services.dag.node_base import node_registry

    assert set(profile.OPTIONAL_OPERATION_CASES) == {
        "model.efa",
        "model.mcr_als",
        "model.simplisma",
    }
    assert {item.node_type for item in node_registry.list_nodes() if item.requires_scp} == set(
        profile.OPTIONAL_OPERATION_CASES
    )
    assert profile.ORDERED_OPTIONAL_OPERATIONS == {"model.efa"}
    assert profile.ORDERED_OPTIONAL_OPERATIONS <= set(profile.OPTIONAL_OPERATION_CASES)


def test_r2_efa_fixture_declares_order_without_weakening_the_runtime_guard() -> None:
    from spectra_sherpa.app.services.dag.nodes.modeling.efa_nodes import _efa_numeric_outputs

    matrix = np.arange(48, dtype=np.float64).reshape(12, 4)
    efa_input = profile._scp_input_dataset("model.efa", matrix)
    assert efa_input.is_time_series is True
    assert profile._scp_input_dataset("model.mcr_als", matrix).is_time_series is False
    assert profile._scp_input_dataset("model.simplisma", matrix).is_time_series is False

    efa_input.is_time_series = False
    with pytest.raises(ValueError, match="explicitly ordered evolution coordinate"):
        _efa_numeric_outputs(efa_input, parameters={"n_components": 2})


def test_locked_projection_comes_from_poetry_authority(tmp_path: Path) -> None:
    destination = tmp_path / "constraints.txt"
    roots, lock_digest, projection_digest = profile._write_lock_projection(PACKAGE_ROOT / "poetry.lock", destination)

    constraints = set(destination.read_text(encoding="utf-8").splitlines())
    assert roots
    assert all("==" in value for value in roots)
    assert set(profile.CORE_ROOT_DISTRIBUTIONS) == {value.split("==", 1)[0] for value in roots}
    assert not any(value.split("==", 1)[0] in profile.FORBIDDEN_DISTRIBUTIONS for value in constraints)
    assert len(lock_digest) == 64
    assert len(projection_digest) == 64


def test_r2_locked_projection_adds_scp_without_adding_application_dependencies(tmp_path: Path) -> None:
    destination = tmp_path / "constraints.txt"
    roots, _, _ = profile._write_lock_projection(
        PACKAGE_ROOT / "poetry.lock",
        destination,
        profile_id="R2",
    )

    root_names = {value.split("==", 1)[0] for value in roots}
    constraint_names = {value.split("==", 1)[0] for value in destination.read_text(encoding="utf-8").splitlines()}
    _, forbidden, expect_scp_ready = profile._profile_settings("R2")
    assert root_names == set(profile.CORE_ROOT_DISTRIBUTIONS) | {"spectrochempy"}
    assert "spectrochempy" in constraint_names
    assert not (forbidden & constraint_names)
    assert expect_scp_ready is True


def test_clean_child_environment_cannot_inherit_source_tree_or_user_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/tmp/unsafe-source-tree")
    monkeypatch.setenv("PYTHONHOME", "/tmp/unsafe-home")
    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/unsafe-venv")
    monkeypatch.setenv("CONDA_PREFIX", "/tmp/unsafe-conda")

    environment = profile._clean_child_environment()

    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    assert "VIRTUAL_ENV" not in environment
    assert "CONDA_PREFIX" not in environment
    assert environment["PYTHONNOUSERSITE"] == "1"


def test_clean_room_evidence_rejects_dirty_or_ambiguous_source_identity() -> None:
    revision = "a" * 40

    assert profile._validated_source_revision(f"{revision}\n", "") == revision
    with pytest.raises(RuntimeError, match="clean source tree"):
        profile._validated_source_revision(revision, " M changed.py\n")
    with pytest.raises(RuntimeError, match="full Git SHA"):
        profile._validated_source_revision("abc123", "")


def test_forbidden_module_mutation_makes_the_gate_fail() -> None:
    passing_stages = [{"name": "representative", "status": "passed"}]

    assert (
        profile._profile_status(
            forbidden_installed=[],
            forbidden_imported=[],
            stages=passing_stages,
        )
        == "passed"
    )
    assert (
        profile._profile_status(
            forbidden_installed=[],
            forbidden_imported=["fastapi"],
            stages=passing_stages,
        )
        == "failed"
    )


def test_probe_report_is_closed_enough_for_operator_consumption(tmp_path: Path) -> None:
    report = {
        "schema_version": profile.PROFILE_SCHEMA_VERSION,
        "profile_id": profile.PROFILE_ID,
        "status": "blocked",
        "installed_distributions": [],
        "imported_modules": [],
        "stages": [],
    }
    destination = tmp_path / "report.json"

    profile._write_report(report, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == report


def test_paired_profile_gate_requires_one_registry_and_exact_base_plus_optional_boundary() -> None:
    def report(profile_id: str, *, installed: bool) -> dict:
        base_operations = [f"node-{index}" for index in range(profile.EXPECTED_BASE_OPERATION_COUNT)]
        optional_operations = sorted(profile.OPTIONAL_OPERATION_CASES)
        node_identities = base_operations + optional_operations
        ready_operations = node_identities if installed else base_operations
        stages = [
            {
                "name": "canonical_registry",
                "status": "passed",
                "node_count": profile.EXPECTED_NODE_COUNT,
                "base_ready_count": profile.EXPECTED_BASE_OPERATION_COUNT,
                "scp_operations": sorted(profile.OPTIONAL_OPERATION_CASES),
                "registry_digest": "a" * 64,
                "ready_count": profile.EXPECTED_NODE_COUNT if installed else profile.EXPECTED_BASE_OPERATION_COUNT,
                "unavailable_count": 0 if installed else 3,
                "unavailable_operations": [] if installed else optional_operations,
                "node_identities": node_identities,
                "execution_contract_digests": {node: str(index) for index, node in enumerate(node_identities)},
                "runtime_requirement_attestation": {
                    "ready_operation_count": (
                        profile.EXPECTED_NODE_COUNT if installed else profile.EXPECTED_BASE_OPERATION_COUNT
                    ),
                    "installed_versions": {},
                    "operations": {operation: {} for operation in ready_operations},
                },
            },
            {
                "name": "profile_isolation",
                "status": "passed",
                "spectrochempy_distribution": "installed" if installed else "absent",
                "network_attempts": [],
            },
        ]
        if installed:
            stages.append(
                {
                    "name": "scp_execution",
                    "status": "passed",
                    "operations": {operation: {} for operation in profile.OPTIONAL_OPERATION_CASES},
                }
            )
        return {
            "schema_version": profile.PROFILE_SCHEMA_VERSION,
            "profile_id": profile_id,
            "status": "passed",
            "source_revision": "c" * 40,
            "installed_distributions": [],
            "stages": stages,
        }

    r1 = report("R1", installed=False)
    r2 = report("R2", installed=True)
    result = profile._compare_profile_reports(r1, r2)
    assert result["base_ready_count"] == profile.EXPECTED_BASE_OPERATION_COUNT
    assert result["optional_operations"] == sorted(profile.OPTIONAL_OPERATION_CASES)

    r2["stages"][0]["registry_digest"] = "b" * 64
    with pytest.raises(RuntimeError, match="registry digest changes"):
        profile._compare_profile_reports(r1, r2)

    r2["stages"][0]["registry_digest"] = "a" * 64
    r2["stages"][0]["execution_contract_digests"]["node-1"] = "mutated"
    with pytest.raises(RuntimeError, match="execution contract digests change"):
        profile._compare_profile_reports(r1, r2)

    r2["stages"][0]["execution_contract_digests"]["node-1"] = "1"
    r1_attestation = r1["stages"][0]["runtime_requirement_attestation"]
    removed = r1_attestation["operations"].pop("node-1")
    with pytest.raises(RuntimeError, match="does not cover every ready operation"):
        r1_attestation["ready_operation_count"] = profile.EXPECTED_BASE_OPERATION_COUNT - 1
        profile._compare_profile_reports(r1, r2)

    r1_attestation["ready_operation_count"] = profile.EXPECTED_BASE_OPERATION_COUNT
    r1_attestation["operations"]["bogus.operation"] = removed
    with pytest.raises(RuntimeError, match="operation identities are not exact"):
        profile._compare_profile_reports(r1, r2)


def test_paired_profile_gate_cross_checks_attestation_against_installed_inventory() -> None:
    base_operations = [f"node-{index}" for index in range(profile.EXPECTED_BASE_OPERATION_COUNT)]
    optional_operations = sorted(profile.OPTIONAL_OPERATION_CASES)
    nodes = base_operations + optional_operations

    def report(profile_id: str, *, installed: bool) -> dict:
        ready = nodes if installed else base_operations
        requirements = {operation: {"scipy": "1.17.1"} for operation in ready}
        stages = [
            {
                "name": "canonical_registry",
                "status": "passed",
                "node_count": profile.EXPECTED_NODE_COUNT,
                "base_ready_count": profile.EXPECTED_BASE_OPERATION_COUNT,
                "scp_operations": optional_operations,
                "registry_digest": "a" * 64,
                "ready_count": profile.EXPECTED_NODE_COUNT if installed else profile.EXPECTED_BASE_OPERATION_COUNT,
                "unavailable_count": 0 if installed else 3,
                "unavailable_operations": [] if installed else optional_operations,
                "node_identities": nodes,
                "execution_contract_digests": {node: node for node in nodes},
                "runtime_requirement_attestation": {
                    "ready_operation_count": len(ready),
                    "installed_versions": {"scipy": "1.17.1"},
                    "operations": requirements,
                },
            },
            {
                "name": "profile_isolation",
                "status": "passed",
                "spectrochempy_distribution": "installed" if installed else "absent",
                "network_attempts": [],
            },
        ]
        if installed:
            stages.append(
                {
                    "name": "scp_execution",
                    "status": "passed",
                    "operations": {operation: {} for operation in optional_operations},
                }
            )
        return {
            "schema_version": profile.PROFILE_SCHEMA_VERSION,
            "profile_id": profile_id,
            "status": "passed",
            "source_revision": "c" * 40,
            "installed_distributions": [{"name": "scipy", "version": "1.17.1"}],
            "stages": stages,
        }

    r1 = report("R1", installed=False)
    r2 = report("R2", installed=True)
    profile._compare_profile_reports(r1, r2)

    r2["installed_distributions"][0]["version"] = "1.13.1"
    with pytest.raises(RuntimeError, match="disagrees with installed distributions"):
        profile._compare_profile_reports(r1, r2)


def test_clean_room_attests_every_ready_contract_against_the_locked_runtime() -> None:
    from spectra_sherpa.app.services.dag import nodes as _nodes  # noqa: F401
    from spectra_sherpa.app.services.dag.node_base import node_registry

    metadata = list(node_registry.list_nodes())
    base_operation_ids = {item.node_type for item in metadata if not item.requires_scp}
    r1_versions, _ = profile._load_main_lock(PACKAGE_ROOT / "poetry.lock", profile_id="R1")
    r1 = profile._attest_ready_runtime_requirements(
        metadata,
        ready_operation_ids=base_operation_ids,
        installed_versions=r1_versions,
    )
    assert r1["ready_operation_count"] == profile.EXPECTED_BASE_OPERATION_COUNT

    r2_versions, _ = profile._load_main_lock(PACKAGE_ROOT / "poetry.lock", profile_id="R2")
    r2 = profile._attest_ready_runtime_requirements(
        metadata,
        ready_operation_ids={item.node_type for item in metadata},
        installed_versions=r2_versions,
    )
    assert r2["ready_operation_count"] == profile.EXPECTED_NODE_COUNT
    assert r2["operations"]["model.mcr_als"]["scipy"] == r2_versions["scipy"] == "1.17.1"
    assert r2["operations"]["model.ica"]["scikit-learn"] == r2_versions["scikit-learn"] == "1.9.0"

    mismatched = dict(r2_versions)
    mismatched["scipy"] = "0.0.0"
    with pytest.raises(RuntimeError, match=r"classification\.simca:scipy.*model\.mcr_als:scipy"):
        profile._attest_ready_runtime_requirements(
            metadata,
            ready_operation_ids={item.node_type for item in metadata},
            installed_versions=mismatched,
        )


def test_runtime_network_and_home_mutations_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    try:
        profile._NETWORK_ATTEMPTS.clear()
        profile._install_network_guard()
        with pytest.raises(RuntimeError, match="network access"):
            socket.socket().connect(("example.invalid", 443))
        with pytest.raises(RuntimeError, match="DNS resolution"):
            socket.getaddrinfo("example.invalid", 443)
        assert profile._NETWORK_ATTEMPTS
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        socket.getaddrinfo = original_getaddrinfo

    profile._NETWORK_ATTEMPTS.clear()
    monkeypatch.setenv("SPECTRA_PROFILE_HOME", str(tmp_path))
    monkeypatch.setattr(profile.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(profile, "_distribution_inventory", lambda: [])
    # Pytest imports every selected test module during collection. Optional-
    # profile tests in the same invocation may therefore have loaded SCP before
    # this isolated R1 mutation check executes; remove and automatically restore
    # those collection-time modules so this test reaches the home-write seam it
    # is specifically proving.
    for module_name in tuple(profile.sys.modules):
        if module_name == "spectrochempy" or module_name.startswith("spectrochempy."):
            monkeypatch.delitem(profile.sys.modules, module_name)
    (tmp_path / ".spectrochempy").mkdir()
    with pytest.raises(RuntimeError, match="touched or created"):
        profile._profile_isolation(expect_scp_ready=False)


def test_workbench_network_guard_allows_only_stdlib_socketpair_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_socketpair = socket.socketpair
    original_getaddrinfo = socket.getaddrinfo
    internal_connects: list[object] = []

    def simulated_windows_connect(instance: socket.socket, address: object) -> None:
        del instance
        internal_connects.append(address)

    def simulated_windows_connect_ex(instance: socket.socket, address: object) -> int:
        simulated_windows_connect(instance, address)
        return 0

    def simulated_windows_socketpair(*args: object, **kwargs: object) -> tuple[socket.socket, socket.socket]:
        del args, kwargs
        left = socket.socket()
        right = socket.socket()
        left.connect(("127.0.0.1", 49152))
        return left, right

    try:
        monkeypatch.setattr(socket.socket, "connect", simulated_windows_connect)
        monkeypatch.setattr(socket.socket, "connect_ex", simulated_windows_connect_ex)
        monkeypatch.setattr(socket, "socketpair", simulated_windows_socketpair)
        workbench_smoke._NETWORK_ATTEMPTS.clear()
        workbench_smoke._install_network_guard()

        left, right = socket.socketpair()
        left.close()
        right.close()
        assert internal_connects == [("127.0.0.1", 49152)]
        assert workbench_smoke._NETWORK_ATTEMPTS == []

        with pytest.raises(RuntimeError, match="network access"):
            socket.socket().connect(("127.0.0.1", 49153))
        with pytest.raises(RuntimeError, match="DNS resolution"):
            socket.getaddrinfo("example.invalid", 443)
    finally:
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        socket.socketpair = original_socketpair
        socket.getaddrinfo = original_getaddrinfo


def test_retained_baseline_preserves_its_historical_harness_and_lock() -> None:
    report = json.loads(
        (PACKAGE_ROOT.parents[1] / "docs/evidence/r1-core-native-baseline.json").read_text(encoding="utf-8")
    )
    assert report["schema_version"] == profile.HISTORICAL_PROFILE_SCHEMA_VERSION
    assert report["profile_id"] == profile.PROFILE_ID
    assert report["status"] == "blocked"
    assert report["source_revision"] == "1b7542c29cce82e82b91d3d42fad433f83097483"
    assert report["poetry_lock_sha256"] == "1ec8d7215e1a6d02bad197e9cc20c5650e44381230852c4df7b35671f02796dd"
    assert report["dependency_projection_sha256"] == "3a7622265a841f24eabf35534812fd34af15d778dad67ea81a3c6f3321a95099"
    assert report["harness_sha256"] == "606a356173ae25669ed259b2d5b949456c44371d1e5f185dc5df3ebb25ebe34a"
    assert report["forbidden_distributions_installed"] == []
    assert report["forbidden_modules_imported"] == []
    assert report["stages"][0]["status"] == "passed"
    assert {stage.get("missing_module") for stage in report["stages"][1:]} == {"sqlalchemy"}


def test_s1b_profile_advances_from_orm_metadata_to_artifact_capability() -> None:
    report = json.loads((PACKAGE_ROOT.parents[1] / "docs/evidence/r1-core-native-s1b.json").read_text(encoding="utf-8"))

    assert report["profile_id"] == profile.PROFILE_ID
    assert report["status"] == "blocked"
    assert report["source_revision"] == "fe382662b03a77901423024d0332d46bded68e93"
    assert report["forbidden_distributions_installed"] == []
    assert report["forbidden_modules_imported"] == []
    assert report["stages"][0]["status"] == "passed"
    for stage in report["stages"][1:]:
        assert stage["missing_module"] == "sqlalchemy"
        trace = "\n".join(stage["traceback_tail"])
        assert "modeling/load_apply_node.py" in trace
        assert "app/models/spectra_meta.py" not in trace


def test_s1d_profile_is_a_commit_bound_native_runtime_proof() -> None:
    report = json.loads((PACKAGE_ROOT.parents[1] / "docs/evidence/r1-core-native-s1d.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == profile.HISTORICAL_PROFILE_SCHEMA_VERSION
    assert report["profile_id"] == profile.PROFILE_ID
    assert report["status"] == "passed"
    assert report["source_revision"] == "46e468c1a24893742e40b5d2282e7705db4a2f69"
    assert report["poetry_lock_sha256"] == "1ec8d7215e1a6d02bad197e9cc20c5650e44381230852c4df7b35671f02796dd"
    assert report["dependency_projection_sha256"] == "3a7622265a841f24eabf35534812fd34af15d778dad67ea81a3c6f3321a95099"
    assert report["harness_sha256"] == "606a356173ae25669ed259b2d5b949456c44371d1e5f185dc5df3ebb25ebe34a"
    assert report["forbidden_distributions_installed"] == []
    assert report["forbidden_modules_imported"] == []
    assert len(report["installed_distributions"]) == 32
    assert len(report["imported_modules"]) == 1883
    assert [(stage["name"], stage["status"]) for stage in report["stages"]] == [
        ("sdk_import", "passed"),
        ("portable_surfaces", "passed"),
        ("canonical_registry", "passed"),
        ("saved_workflow_execution", "passed"),
    ]
    registry = report["stages"][2]
    # This report is immutable evidence from the S1d qualification commit; the
    # live registry may grow only through separately regenerated evidence.
    assert registry["node_count"] == registry["contract_count"] == 85
    assert len(registry["scp_operations"]) == 6
    assert not any(value["ready"] for value in registry["scp_readiness"].values())
    execution = report["stages"][3]
    assert execution["result_digest"] == execution["reproduced_result_digest"]
