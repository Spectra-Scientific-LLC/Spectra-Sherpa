#!/usr/bin/env python3
"""Build and exercise the internal R1/R2 scientific-core runtime profiles.

This is an engineering boundary probe, not a customer installation mode. It
builds the same public wheel, installs that wheel without dependency metadata
into a fresh virtual environment, and supplies only a locked projection of the
scientific dependencies. The child probe then records both the complete
installed-distribution set and the complete imported-module set.

During S1 the probe may report ``blocked`` while named application couplings
are being removed. The harness itself must remain unchanged as S1b-S1d drive
that result to ``passed``; otherwise the boundary would move with the
implementation it is meant to measure.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import tomllib
import traceback
import venv
from pathlib import Path
from typing import Any, Callable, Mapping

PROFILE_SCHEMA_VERSION = "spectra-runtime-profile-probe/3"
HISTORICAL_PROFILE_SCHEMA_VERSION = "spectra-runtime-profile-probe/1"
PROFILE_ID = "R1"  # Historical evidence and callers default to the native profile.
FORBIDDEN_DISTRIBUTIONS = frozenset(
    {
        "aiosqlite",
        "alembic",
        "asyncpg",
        "fastapi",
        "spectrochempy",
        "sqlalchemy",
        "starlette",
        "uvicorn",
    }
)
SCP_DISTRIBUTIONS = frozenset({"spectrochempy"})
FORBIDDEN_MODULES = (
    "spectrochempy",
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "aiosqlite",
    "asyncpg",
    "spectra_sherpa.app.api",
    "spectra_sherpa.app.db",
    "spectra_sherpa.app.models",
    "spectrasherpa_server",
    "spectra_hybrid",
    "spectra_hybrid_contracts",
)

# These are the only public-wheel dependencies admitted into the R1
# engineering projection. Versions come from poetry.lock; transitive versions
# are constrained by the complete main-group lock projection.
CORE_ROOT_DISTRIBUTIONS = (
    "cryptography",
    "h5py",
    "idna",
    "jsonschema",
    "numpy",
    "pandas",
    "pydantic",
    "pypdf",
    "scikit-learn",
    "scipy",
    "urllib3",
)

# Current-release runtime qualification authority. Historical R1 evidence
# remains frozen at the node count recorded by its originating commit.
EXPECTED_NODE_COUNT = 101
# These keys are executable smoke cases, not a second capability registry. The
# probe requires exact equality with the live ``requires_scp`` projection.
OPTIONAL_OPERATION_CASES: dict[str, dict[str, object]] = {
    "model.efa": {"n_components": 2},
    "model.mcr_als": {"n_components": 2},
    "model.simplisma": {"n_components": 2},
}
ORDERED_OPTIONAL_OPERATIONS = frozenset({"model.efa"})
EXPECTED_OPTIONAL_OPERATION_COUNT = 3
EXPECTED_BASE_OPERATION_COUNT = EXPECTED_NODE_COUNT - EXPECTED_OPTIONAL_OPERATION_COUNT
_NETWORK_ATTEMPTS: list[str] = []


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _lock_marker_applies(marker: object, *, profile_id: str) -> bool:
    if isinstance(marker, dict):
        marker = marker.get("main")
    if not marker:
        return True
    if not isinstance(marker, str):
        raise RuntimeError(f"unsupported poetry lock marker shape: {marker!r}")
    from packaging.markers import Marker

    return Marker(marker).evaluate(
        {
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "extra": "scp" if profile_id == "R2" else "",
        }
    )


def _load_main_lock(lock_path: Path, *, profile_id: str = PROFILE_ID) -> tuple[dict[str, str], str]:
    raw = lock_path.read_bytes()
    document = tomllib.loads(raw.decode("utf-8"))
    versions: dict[str, str] = {}
    for package in document.get("package", []):
        if "main" not in package.get("groups", []):
            continue
        if not _lock_marker_applies(package.get("markers"), profile_id=profile_id):
            continue
        name = _canonical_name(str(package["name"]))
        version = str(package["version"])
        previous = versions.setdefault(name, version)
        if previous != version:
            raise RuntimeError(f"poetry lock has multiple main versions for {name}: {previous}, {version}")
    missing = sorted(set(CORE_ROOT_DISTRIBUTIONS) - set(versions))
    if missing:
        raise RuntimeError(f"R1 root distributions are absent from poetry.lock: {missing}")
    overlap = sorted(FORBIDDEN_DISTRIBUTIONS & set(CORE_ROOT_DISTRIBUTIONS))
    if overlap:
        raise RuntimeError(f"R1 root set contains forbidden distributions: {overlap}")
    return versions, _digest_bytes(raw)


def _profile_settings(profile_id: str) -> tuple[tuple[str, ...], frozenset[str], bool]:
    if profile_id == "R1":
        return CORE_ROOT_DISTRIBUTIONS, FORBIDDEN_DISTRIBUTIONS, False
    if profile_id == "R2":
        return (*CORE_ROOT_DISTRIBUTIONS, "spectrochempy"), FORBIDDEN_DISTRIBUTIONS - SCP_DISTRIBUTIONS, True
    raise RuntimeError(f"unsupported scientific-core profile: {profile_id}")


def _write_lock_projection(
    lock_path: Path,
    destination: Path,
    *,
    profile_id: str = PROFILE_ID,
) -> tuple[list[str], str, str]:
    versions, lock_digest = _load_main_lock(lock_path, profile_id=profile_id)
    root_distributions, forbidden_distributions, _ = _profile_settings(profile_id)
    missing = sorted(set(root_distributions) - set(versions))
    if missing:
        raise RuntimeError(f"{profile_id} root distributions are absent from poetry.lock: {missing}")
    constraints = [
        f"{name}=={version}" for name, version in sorted(versions.items()) if name not in forbidden_distributions
    ]
    roots = [f"{name}=={versions[name]}" for name in root_distributions]
    payload = {
        "profile_id": profile_id,
        "roots": roots,
        "forbidden_distributions": sorted(forbidden_distributions),
        "poetry_lock_sha256": lock_digest,
    }
    projection_digest = _digest_bytes(_canonical_json(payload))
    destination.write_text("\n".join(constraints) + "\n", encoding="utf-8")
    return roots, lock_digest, projection_digest


def _venv_python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _clean_child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX"):
        environment.pop(name, None)
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "SPECTROCHEMPY_CHECK_UPDATE": "false",
        }
    )
    return environment


def _run(command: list[str], *, cwd: Path, environment: Mapping[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=dict(environment), check=True)


def _validated_source_revision(revision: str, status: str) -> str:
    revision = revision.strip()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise RuntimeError(f"runtime-profile source revision is not a full Git SHA: {revision!r}")
    if status.strip():
        raise RuntimeError("runtime-profile evidence requires a clean source tree")
    return revision


def _source_revision(repository_root: Path) -> str:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return _validated_source_revision(revision, status)


def _distribution_inventory() -> list[dict[str, str]]:
    rows: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        name = metadata.get("Name") if metadata is not None else None
        if name:
            rows[_canonical_name(name)] = distribution.version
    return [{"name": name, "version": rows[name]} for name in sorted(rows)]


def _attest_ready_runtime_requirements(
    metadata: list[Any],
    *,
    ready_operation_ids: set[str],
    installed_versions: Mapping[str, str],
) -> dict[str, Any]:
    """Bind every ready operation to the exact installed numerical runtime.

    Registry readiness answers whether an optional capability is present.  It
    does not attest an execution environment.  The clean-room profiles make a
    stronger release claim, so they must compare every ready operation's
    contract-pinned distributions with the versions actually installed in the
    child before reporting the 86/3 or 89/0 boundary.
    """

    normalized_installed = {_canonical_name(name): str(version) for name, version in installed_versions.items()}
    operation_requirements: dict[str, dict[str, str]] = {}
    mismatches: list[str] = []
    for item in sorted(metadata, key=lambda value: value.node_type):
        if item.node_type not in ready_operation_ids:
            continue
        contract = item.resolved_execution_contract()
        if contract is None:
            raise RuntimeError(f"ready operation {item.node_type} has no execution contract")
        requirements: dict[str, str] = {}
        for requirement in contract.payload["runtime_requirements"]:
            distribution = _canonical_name(str(requirement["distribution"]))
            expected = str(requirement["version"])
            actual = normalized_installed.get(distribution)
            requirements[distribution] = expected
            if actual != expected:
                mismatches.append(
                    f"{item.node_type}:{distribution} expected {expected}, installed {actual or 'absent'}"
                )
        operation_requirements[item.node_type] = requirements
    missing_operations = sorted(ready_operation_ids - set(operation_requirements))
    if missing_operations:
        raise RuntimeError(f"ready runtime attestation omitted operations: {missing_operations}")
    if mismatches:
        raise RuntimeError("ready operation runtime requirement mismatch: " + "; ".join(mismatches))
    relevant_distributions = sorted(
        {distribution for requirements in operation_requirements.values() for distribution in requirements}
    )
    return {
        "ready_operation_count": len(operation_requirements),
        "installed_versions": {
            distribution: normalized_installed[distribution] for distribution in relevant_distributions
        },
        "operations": operation_requirements,
    }


def _stage(name: str, operation: Callable[[], Mapping[str, Any] | None]) -> dict[str, Any]:
    try:
        details = dict(operation() or {})
    except Exception as exc:  # noqa: BLE001 - boundary probe records every blocker
        return {
            "name": name,
            "status": "blocked",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "missing_module": exc.name if isinstance(exc, ModuleNotFoundError) else None,
            "traceback_tail": traceback.format_exc().strip().splitlines()[-8:],
        }
    return {"name": name, "status": "passed", **details}


def _import_sdk() -> dict[str, Any]:
    sdk = importlib.import_module("spectra_sherpa.sdk")
    return {"module": sdk.__name__}


def _import_portable_surfaces() -> dict[str, Any]:
    project = importlib.import_module("spectra_sherpa.sdk.canonical_project")
    evidence = importlib.import_module("spectra_sherpa.sdk.canonical_execution_evidence")
    reproduction = importlib.import_module("spectra_sherpa.sdk.canonical_reproduction")
    return {
        "symbols": [
            project.CanonicalProjectPackage.__name__,
            evidence.CanonicalExecutionEvidence.__name__,
            reproduction.CanonicalReproductionReport.__name__,
        ]
    }


def _import_registry(*, expect_scp_ready: bool) -> dict[str, Any]:
    importlib.import_module("spectra_sherpa.app.services.dag.nodes")
    profile_module = importlib.import_module("spectra_sherpa.app.services.dag.managed_optimization_profile")
    node_base = importlib.import_module("spectra_sherpa.app.services.dag.node_base")
    catalog = importlib.import_module("spectra_sherpa.app.services.dag.node_catalog_contract")

    metadata = node_base.node_registry.list_nodes()
    if len(metadata) != EXPECTED_NODE_COUNT:
        raise RuntimeError(f"expected {EXPECTED_NODE_COUNT} canonical nodes, found {len(metadata)}")
    missing_contracts = sorted(item.node_type for item in metadata if item.resolved_execution_contract() is None)
    if missing_contracts:
        raise RuntimeError(f"registered nodes lack execution contracts: {missing_contracts}")
    scp_operations = {item.node_type for item in metadata if item.requires_scp}
    if len(scp_operations) != EXPECTED_OPTIONAL_OPERATION_COUNT:
        raise RuntimeError(
            f"expected {EXPECTED_OPTIONAL_OPERATION_COUNT} live optional operations, got {sorted(scp_operations)}"
        )
    if scp_operations != set(OPTIONAL_OPERATION_CASES):
        raise RuntimeError("live optional operations do not have an exact executable profile case")
    readiness = {item.node_type: catalog.dependency_readiness(item).as_dict() for item in metadata if item.requires_scp}
    ready_operations = sorted(node_type for node_type, value in readiness.items() if value["ready"])
    if expect_scp_ready and set(ready_operations) != scp_operations:
        raise RuntimeError(f"not every SCP operation is ready in R2: {ready_operations}")
    if not expect_scp_ready and ready_operations:
        raise RuntimeError(f"SCP operations are ready in the R1 no-SCP runtime: {ready_operations}")
    base_ready = sorted(
        item.node_type for item in metadata if not item.requires_scp and catalog.dependency_readiness(item).ready
    )
    if len(base_ready) != EXPECTED_BASE_OPERATION_COUNT:
        raise RuntimeError(f"expected {EXPECTED_BASE_OPERATION_COUNT} ready base operations, found {len(base_ready)}")
    ready_operation_ids = set(base_ready) | set(ready_operations)
    installed_versions = {row["name"]: row["version"] for row in _distribution_inventory()}
    runtime_attestation = _attest_ready_runtime_requirements(
        metadata,
        ready_operation_ids=ready_operation_ids,
        installed_versions=installed_versions,
    )
    profile = profile_module.managed_optimization_profile()
    census = catalog.build_node_contract_census(metadata)
    return {
        "node_count": len(metadata),
        "contract_count": len(metadata) - len(missing_contracts),
        "base_ready_count": len(base_ready),
        "ready_count": len(base_ready) + len(ready_operations),
        "unavailable_count": len(metadata) - len(base_ready) - len(ready_operations),
        "unavailable_operations": sorted(set(scp_operations) - set(ready_operations)),
        "node_identities": [item.node_type for item in sorted(metadata, key=lambda item: item.node_type)],
        "execution_contract_digests": {
            item.node_type: item.resolved_execution_contract().digest
            for item in sorted(metadata, key=lambda item: item.node_type)
        },
        "registry_digest": catalog.census_digest(census),
        "profile_digest": profile.digest,
        "scp_operations": sorted(scp_operations),
        "scp_readiness": readiness,
        "runtime_requirement_attestation": runtime_attestation,
    }


def _result_digest(value: Any) -> str:
    if isinstance(value, Mapping) and "default" in value:
        value = value["default"]
    data = getattr(value, "data", value)
    if hasattr(data, "magnitude"):
        data = data.magnitude
    import numpy as np

    array = np.asarray(data, dtype=np.float64)
    payload = {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "values_sha256": _digest_bytes(array.tobytes(order="C")),
    }
    return _digest_bytes(_canonical_json(payload))


async def _execute_saved_workflow(workflow: Any) -> str:
    executor_module = importlib.import_module("spectra_sherpa.app.services.dag.executor")
    types_module = importlib.import_module("spectra_sherpa.app.services.dag.executor_types")
    executor = executor_module.DAGExecutor(process_pool=None)
    for raw_node in workflow.payload["nodes"]:
        executor.add_node(
            types_module.WorkflowNode(raw_node["node_id"], raw_node["node_type"], dict(raw_node["parameters"]))
        )
    for raw_edge in workflow.payload["edges"]:
        executor.add_edge(
            types_module.WorkflowEdge(
                from_node=raw_edge["from_node_id"],
                to_node=raw_edge["to_node_id"],
                from_output=raw_edge["from_output"],
                to_input=raw_edge["to_input"],
            )
        )
    results = await executor.execute()
    return _result_digest(results["curve"])


def _workflow_journey() -> dict[str, Any]:
    workflow_module = importlib.import_module("spectra_sherpa.sdk.workflow")
    workflow = workflow_module.workflow_spec(
        nodes=[
            {
                "node_id": "curve",
                "node_type": "data.synthetic_curve",
                "parameters": {
                    "curve_type": "gaussian",
                    "n_points": 32,
                    "max_concentration": 2.0,
                    "center": 0.4,
                    "width": 0.12,
                    "duration_seconds": 8.0,
                },
            }
        ],
        edges=[],
    )
    exported = workflow.as_dict()
    with tempfile.TemporaryDirectory(prefix="spectra-r1-workflow-") as raw_dir:
        path = Path(raw_dir) / "workflow.json"
        path.write_bytes(_canonical_json(exported))
        reopened = workflow_module.WorkflowSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))
    first = asyncio.run(_execute_saved_workflow(workflow))
    reproduced = asyncio.run(_execute_saved_workflow(reopened))
    if first != reproduced:
        raise RuntimeError("saved workflow reproduction digest differs")
    return {
        "workflow_digest": workflow.workflow_digest,
        "export_sha256": _digest_bytes(_canonical_json(exported)),
        "result_digest": first,
        "reproduced_result_digest": reproduced,
    }


def _array_digest(value: Any) -> str:
    import numpy as np

    return _digest_bytes(np.ascontiguousarray(np.asarray(value, dtype="<f8")).tobytes())


def _spc_science_digest(result: Any) -> str:
    import numpy as np

    digest = hashlib.sha256()
    for asset in result.assets:
        dataset = asset.dataset
        digest.update(asset.asset_id.encode())
        digest.update(b"\0")
        digest.update(np.asarray(dataset.X.shape, dtype="<i8").tobytes())
        digest.update(np.ascontiguousarray(np.asarray(dataset.X, dtype="<f8")).tobytes())
        digest.update(np.ascontiguousarray(np.asarray(dataset.feature_axis.values, dtype="<f8")).tobytes())
    return digest.hexdigest()


def _native_fixture_cases(repository_root: Path, materialized_root: Path) -> list[dict[str, Any]]:
    """Project checked conformance authorities into executable clean-room cases."""

    manifest_root = repository_root / "packages/spectra-sherpa/tests/fixtures/formats"
    manifest = json.loads((manifest_root / "manifest.json").read_text(encoding="utf-8"))
    chosen = {"csv-axis-column", "jcamp-plain", "numpy-float-matrix", "matlab-spectral"}
    cases: list[dict[str, Any]] = []
    for record in manifest["fixtures"]:
        if record["fixture_id"] not in chosen:
            continue
        source = manifest_root / record["path"]
        if record["encoding"] == "base64":
            destination = materialized_root / source.name.removesuffix(".b64")
            destination.write_bytes(base64.b64decode(source.read_bytes()))
            source = destination
        expected_assets = []
        for asset in record["expected_assets"]:
            expected_assets.append(
                {
                    "asset_id": asset["asset_id"],
                    "shape": asset["shape"],
                    "values_sha256": _array_digest(asset["values"]),
                    "axis_sha256": (
                        _array_digest(asset["feature_axis"]) if asset["feature_axis"] is not None else None
                    ),
                    "axis_units": asset["feature_axis_units"],
                }
            )
        cases.append(
            {
                "case_id": record["fixture_id"],
                "path": source,
                "source_sha256": record["sha256"],
                "format_id": record["format_id"],
                "variant": record["variant"],
                "assets": expected_assets,
            }
        )

    evidence_root = repository_root / "docs/evidence"
    spc = json.loads((evidence_root / "native-spc-reader-conformance.json").read_text(encoding="utf-8"))
    spc_record = next(record for record in spc["fixtures"] if record["path"].endswith("nir.spc"))
    cases.append(
        {
            "case_id": spc_record["fixture_id"],
            "path": repository_root / spc_record["path"],
            "source_sha256": spc_record["sha256"],
            "format_id": "spc",
            "variant": spc_record["variant"],
            "aggregate_science_sha256": spc_record["aggregate_science_sha256"],
            "asset_count": spc_record["asset_count"],
        }
    )

    opus = json.loads((evidence_root / "native-opus-reader-conformance.json").read_text(encoding="utf-8"))
    opus_record = opus["bundled_fixtures"][0]
    cases.append(
        {
            "case_id": opus_record["fixture_id"],
            "path": repository_root / opus["bundled_fixture_root"] / opus_record["filename"],
            "source_sha256": opus_record["sha256"],
            "format_id": "opus",
            "variant": "directory-block-v1",
            "assets": opus_record["assets"],
        }
    )

    omnic = json.loads((evidence_root / "native-omnic-reader-conformance.json").read_text(encoding="utf-8"))
    omnic_record = next(record for record in omnic["bundled_fixtures"] if record["filename"].endswith(".spa"))
    cases.append(
        {
            "case_id": "omnic-bundled-spa",
            "path": repository_root / omnic["bundled_fixture_root"] / omnic_record["filename"],
            "source_sha256": omnic_record["source_sha256"],
            "format_id": "omnic",
            "variant": omnic_record["variant"],
            "assets": [
                {
                    "asset_id": omnic_record["asset_id"],
                    "shape": omnic_record["shape"],
                    "values_sha256": omnic_record["values_sha256"],
                    "axis_sha256": omnic_record["axis_sha256"],
                    "axis_units": omnic_record["axis_units"],
                }
            ],
        }
    )

    wdf = json.loads((evidence_root / "native-wdf-reader-conformance.json").read_text(encoding="utf-8"))
    wdf_record = next(record for record in wdf["fixtures"] if record["filename"] == "sp.wdf")
    cases.append(
        {
            "case_id": "wdf-single-spectrum",
            "path": repository_root / "packages/spectra-sherpa/tests/fixtures/wdf" / wdf_record["filename"],
            "source_sha256": wdf_record["source_sha256"],
            "format_id": "wdf",
            "variant": wdf_record["variant"],
            "assets": [
                {
                    "asset_id": "spectra",
                    "shape": wdf_record["shape"],
                    "values_sha256": wdf_record["x_sha256"],
                    "axis_sha256": wdf_record["feature_axis_sha256"],
                    "axis_units": wdf_record["feature_units"],
                }
            ],
        }
    )
    return cases


def _native_ingestion_journey() -> dict[str, Any]:
    """Exercise every redistributable qualified parser without SCP."""

    ingestion = importlib.import_module("spectra_sherpa.io")
    repository_root = Path(os.environ["SPECTRA_PROFILE_REPOSITORY_ROOT"])
    checked: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="spectra-r1-native-fixtures-") as raw_dir:
        cases = _native_fixture_cases(repository_root, Path(raw_dir))
        for case in cases:
            path = Path(case["path"])
            if _digest_bytes(path.read_bytes()) != case["source_sha256"]:
                raise RuntimeError(f"native fixture source digest differs for {case['case_id']}")
            result = ingestion.ingest(path)
            if result.format_id != case["format_id"] or result.variant != case["variant"]:
                raise RuntimeError(f"native parser identity differs for {case['case_id']}")
            if "aggregate_science_sha256" in case:
                if (
                    len(result.assets) != case["asset_count"]
                    or _spc_science_digest(result) != case["aggregate_science_sha256"]
                ):
                    raise RuntimeError(f"native SPC science differs for {case['case_id']}")
            else:
                expected_assets = case["assets"]
                if [asset.asset_id for asset in result.assets] != [asset["asset_id"] for asset in expected_assets]:
                    raise RuntimeError(f"native asset identity differs for {case['case_id']}")
                for actual, expected in zip(result.assets, expected_assets, strict=True):
                    dataset = actual.dataset
                    if list(dataset.shape) != expected["shape"]:
                        raise RuntimeError(f"native asset shape differs for {case['case_id']}:{actual.asset_id}")
                    if _array_digest(dataset.X) != expected["values_sha256"]:
                        raise RuntimeError(f"native values differ for {case['case_id']}:{actual.asset_id}")
                    axis_values = getattr(dataset.feature_axis, "values", None)
                    if (
                        expected.get("axis_sha256") is not None
                        and _array_digest(axis_values) != expected["axis_sha256"]
                    ):
                        raise RuntimeError(f"native axis differs for {case['case_id']}:{actual.asset_id}")
                    if expected.get("axis_units") != getattr(dataset.feature_axis, "units", None):
                        raise RuntimeError(f"native axis units differ for {case['case_id']}:{actual.asset_id}")
            checked.append(
                {
                    "case_id": case["case_id"],
                    "format_id": result.format_id,
                    "variant": result.variant,
                    "asset_count": len(result.assets),
                }
            )
    if len(checked) != 8:
        raise RuntimeError(f"expected eight redistributable native parser cases, found {len(checked)}")
    return {
        "fixtures": checked,
        "external_qualified_not_redistributed": ["omnic-spg", "omnic-srs"],
    }


def _native_group_journey() -> dict[str, Any]:
    """Prove registered native group loading with exact ordering and shape."""

    loaders = importlib.import_module("spectra_sherpa.app.services.dag.nodes.data.loaders")
    with tempfile.TemporaryDirectory(prefix="spectra-r1-native-group-") as raw_dir:
        root = Path(raw_dir)
        for name, payload in {
            "sample_1.csv": "sample,1000,1100,1200\nA,1,2,3\n",
            "sample_2.csv": "sample,1000,1100,1200\nB,4,5,6\n",
        }.items():
            (root / name).write_text(payload, encoding="utf-8")
        grouped = asyncio.run(
            loaders.LoadGroupNode(
                "r1-group",
                {
                    "folder_path": str(root),
                    "pattern": "*.csv",
                    "recursive": False,
                    "sort_by": "filename",
                    "group_title": "R1 native group",
                },
            ).execute()
        )
    if grouped.shape != (2, 3):
        raise RuntimeError(f"native data.load_group returned the wrong shape: {grouped.shape}")
    if _array_digest(grouped.X) != _array_digest([[1, 2, 3], [4, 5, 6]]):
        raise RuntimeError("native data.load_group returned the wrong member order or values")
    return {"operation": "data.load_group", "shape": list(grouped.shape), "result_digest": _result_digest(grouped)}


def _canonical_prediction_journey() -> dict[str, Any]:
    """Fit and apply one native canonical PLS artifact through registered nodes."""

    import numpy as np

    dataset_module = importlib.import_module("spectra_sherpa.app.lib.sherpa_dataset")
    node_base = importlib.import_module("spectra_sherpa.app.services.dag.node_base")
    samples = np.linspace(0.0, 1.0, 18, dtype=np.float64)
    features = np.linspace(-1.0, 1.0, 12, dtype=np.float64)
    matrix = np.column_stack(
        [1.0 + samples * (index + 1) + 0.03 * np.sin((index + 1) * features[index]) for index in range(12)]
    )
    target = 0.7 + 1.2 * samples + 0.15 * samples**2
    dataset = dataset_module.SherpaDataset(X=matrix, target=target)
    fit = node_base.node_registry.create_node("model.fitted_pls", "r1-fit", {"n_components": 2})
    fitted = asyncio.run(fit.execute(input_data=dataset, y=target))
    fit_outputs = fitted.outputs if hasattr(fitted, "outputs") else fitted
    apply = node_base.node_registry.create_node("model.apply_fitted_pls", "r1-apply", {})
    applied = asyncio.run(apply.execute(input_data=dataset, fitted_state=fit_outputs["fitted_state"]))
    apply_outputs = applied.outputs if hasattr(applied, "outputs") else applied
    fit_predictions = np.asarray(fit_outputs["default"], dtype=np.float64)
    apply_predictions = np.asarray(apply_outputs["default"], dtype=np.float64)
    np.testing.assert_allclose(apply_predictions, fit_predictions, rtol=0.0, atol=1e-12)
    _reject_scp_outputs(fit_outputs, operation_id="model.fitted_pls")
    _reject_scp_outputs(apply_outputs, operation_id="model.apply_fitted_pls")
    return {
        "fit_operation": "model.fitted_pls",
        "apply_operation": "model.apply_fitted_pls",
        "prediction_shape": list(apply_predictions.shape),
        "prediction_digest": _result_digest(apply_predictions),
        "fit_apply_max_abs_difference": float(np.max(np.abs(fit_predictions - apply_predictions))),
    }


def _reject_scp_outputs(value: Any, *, operation_id: str) -> None:
    transport = importlib.import_module("spectra_sherpa.app.services.dag.transport")
    transport.reject_spectrochempy_transport(value, boundary=f"{operation_id} runtime-profile output")


def _scp_input_dataset(operation_id: str, matrix: Any) -> Any:
    if operation_id not in OPTIONAL_OPERATION_CASES:
        raise RuntimeError(f"unknown optional runtime-profile operation: {operation_id}")
    dataset_module = importlib.import_module("spectra_sherpa.app.lib.sherpa_dataset")
    return dataset_module.SherpaDataset(
        X=matrix,
        # The synthetic rows have a declared offset progression. EFA receives
        # that explicit order authority; optional dependency presence alone is
        # not permission to treat arbitrary sample order as evolution.
        is_time_series=operation_id in ORDERED_OPTIONAL_OPERATIONS,
    )


def _assert_optional_runtime_is_lazy() -> dict[str, Any]:
    loaded = sorted(name for name in sys.modules if _module_matches(name, "spectrochempy"))
    if loaded:
        raise RuntimeError(f"SpectroChemPy loaded before an optional operation executed: {loaded[:10]}")
    return {"spectrochempy_modules_loaded": loaded}


def _scp_journey() -> dict[str, Any]:
    """Execute all three real SCP-backed canonical operations in the R2 child."""
    import numpy as np

    node_base = importlib.import_module("spectra_sherpa.app.services.dag.node_base")
    axis = np.linspace(0.0, 2.0 * np.pi, 24, dtype=np.float64)
    offsets = np.linspace(0.0, 0.7, 12, dtype=np.float64)[:, None]
    matrix = 1.5 + np.sin(axis[None, :] + offsets) + 0.1 * np.cos(3.0 * axis[None, :])
    results: dict[str, Any] = {}
    live_optional = {item.node_type for item in node_base.node_registry.list_nodes() if item.requires_scp}
    if live_optional != set(OPTIONAL_OPERATION_CASES):
        raise RuntimeError("R2 executable cases differ from the live optional registry projection")
    for operation_id, parameters in sorted(OPTIONAL_OPERATION_CASES.items()):
        node = node_base.node_registry.create_node(operation_id, f"r2-{operation_id}", parameters)
        result = asyncio.run(node.execute(input_data=_scp_input_dataset(operation_id, matrix)))
        outputs = result.outputs if hasattr(result, "outputs") else result
        _reject_scp_outputs(outputs, operation_id=operation_id)
        primary = outputs["default"]
        array = np.asarray(primary.X if hasattr(primary, "X") else primary, dtype=np.float64)
        if array.ndim != 2 or not array.size or not np.isfinite(array).all():
            raise RuntimeError(f"{operation_id} returned an invalid canonical primary output")
        results[operation_id] = {"shape": list(array.shape), "result_digest": _result_digest(primary)}
    return {"operations": results}


def _install_network_guard() -> None:
    """Fail and record if the isolated scientific profiles attempt network I/O."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo

    def blocked_connect(instance: socket.socket, address: object) -> None:
        del instance
        _NETWORK_ATTEMPTS.append(repr(address))
        raise RuntimeError(f"runtime profile attempted network access: {address!r}")

    def blocked_connect_ex(instance: socket.socket, address: object) -> int:
        blocked_connect(instance, address)
        return 1

    def blocked_getaddrinfo(*args: object, **kwargs: object) -> list[object]:
        del kwargs
        _NETWORK_ATTEMPTS.append(f"dns:{args!r}")
        raise RuntimeError(f"runtime profile attempted DNS resolution: {args!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = blocked_getaddrinfo  # type: ignore[assignment]
    # Retain references for the process lifetime so debuggers can identify the
    # exact wrapped authority; the probe intentionally never restores access.
    _install_network_guard._originals = (  # type: ignore[attr-defined]
        original_connect,
        original_connect_ex,
        original_getaddrinfo,
    )


def _profile_isolation(*, expect_scp_ready: bool) -> dict[str, Any]:
    profile_home = Path(os.environ["SPECTRA_PROFILE_HOME"])
    scp_home = profile_home / ".spectrochempy"
    scp_spec = importlib.util.find_spec("spectrochempy")
    installed = {_canonical_name(row["name"]) for row in _distribution_inventory()}
    if expect_scp_ready:
        if "spectrochempy" not in installed or scp_spec is None:
            raise RuntimeError("R2 requires the SpectroChemPy distribution and import spec")
    else:
        if "spectrochempy" in installed or scp_spec is not None:
            raise RuntimeError("R1 must contain neither the SpectroChemPy distribution nor import spec")
        if any(_module_matches(name, "spectrochempy") for name in sys.modules):
            raise RuntimeError("R1 imported SpectroChemPy despite the clean native profile")
        if scp_home.exists():
            raise RuntimeError("R1 touched or created the SpectroChemPy home directory")
    if _NETWORK_ATTEMPTS:
        raise RuntimeError(f"runtime profile attempted network access: {_NETWORK_ATTEMPTS}")
    return {
        "spectrochempy_distribution": "installed" if "spectrochempy" in installed else "absent",
        "spectrochempy_import_spec": "available" if scp_spec is not None else "absent",
        "spectrochempy_home_created": scp_home.exists(),
        "network_attempts": list(_NETWORK_ATTEMPTS),
    }


def _module_matches(name: str, forbidden: str) -> bool:
    return name == forbidden or name.startswith(f"{forbidden}.")


def _profile_status(
    *,
    forbidden_installed: list[str],
    forbidden_imported: list[str],
    stages: list[Mapping[str, Any]],
) -> str:
    if forbidden_installed or forbidden_imported:
        return "failed"
    if any(stage["status"] != "passed" for stage in stages):
        return "blocked"
    return "passed"


def _probe(
    *,
    profile_id: str = PROFILE_ID,
    simulated_forbidden_module: str | None = None,
) -> dict[str, Any]:
    if simulated_forbidden_module:
        import types

        sys.modules[simulated_forbidden_module] = types.ModuleType(simulated_forbidden_module)

    _, forbidden_distributions, expect_scp_ready = _profile_settings(profile_id)
    _NETWORK_ATTEMPTS.clear()
    _install_network_guard()
    installed = _distribution_inventory()
    installed_names = {row["name"] for row in installed}
    stages = [
        _stage("sdk_import", _import_sdk),
        _stage("portable_surfaces", _import_portable_surfaces),
        _stage("canonical_registry", lambda: _import_registry(expect_scp_ready=expect_scp_ready)),
        _stage("optional_runtime_lazy_before_execution", _assert_optional_runtime_is_lazy),
        _stage("native_ingestion", _native_ingestion_journey),
        _stage("native_group", _native_group_journey),
        _stage("canonical_prediction", _canonical_prediction_journey),
        _stage("saved_workflow_execution", _workflow_journey),
    ]
    if expect_scp_ready:
        stages.append(_stage("scp_execution", _scp_journey))
    stages.append(_stage("profile_isolation", lambda: _profile_isolation(expect_scp_ready=expect_scp_ready)))
    imported_modules = sorted(sys.modules)
    forbidden_installed = sorted(forbidden_distributions & installed_names)
    forbidden_modules = tuple(name for name in FORBIDDEN_MODULES if not (expect_scp_ready and name == "spectrochempy"))
    forbidden_imported = sorted(
        forbidden
        for forbidden in forbidden_modules
        if any(_module_matches(module_name, forbidden) for module_name in imported_modules)
    )
    status = _profile_status(
        forbidden_installed=forbidden_installed,
        forbidden_imported=forbidden_imported,
        stages=stages,
    )
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_id": profile_id,
        "status": status,
        "source_revision": os.environ.get("SPECTRA_PROFILE_SOURCE_REVISION"),
        "platform": platform.platform(),
        "python_version": sys.version,
        "wheel_sha256": os.environ.get("SPECTRA_PROFILE_WHEEL_SHA256"),
        "poetry_lock_sha256": os.environ.get("SPECTRA_PROFILE_LOCK_SHA256"),
        "dependency_projection_sha256": os.environ.get("SPECTRA_PROFILE_PROJECTION_SHA256"),
        "harness_sha256": os.environ.get("SPECTRA_PROFILE_HARNESS_SHA256"),
        "installed_distributions": installed,
        "imported_modules": imported_modules,
        "forbidden_distributions_installed": forbidden_installed,
        "forbidden_modules_imported": forbidden_imported,
        "stages": stages,
    }


def _write_report(report: Mapping[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _stage_by_name(report: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    matches = [stage for stage in report.get("stages", []) if stage.get("name") == name]
    if len(matches) != 1:
        raise RuntimeError(f"profile {report.get('profile_id')} must contain exactly one {name!r} stage")
    if matches[0].get("status") != "passed":
        raise RuntimeError(f"profile {report.get('profile_id')} stage {name!r} did not pass")
    return matches[0]


def _compare_profile_reports(r1: Mapping[str, Any], r2: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the paired clean-room reports as one release boundary."""

    for expected_id, report in (("R1", r1), ("R2", r2)):
        if report.get("schema_version") != PROFILE_SCHEMA_VERSION:
            raise RuntimeError(f"{expected_id} report does not use {PROFILE_SCHEMA_VERSION}")
        if report.get("profile_id") != expected_id or report.get("status") != "passed":
            raise RuntimeError(f"{expected_id} report identity or status is invalid")
    r1_registry = _stage_by_name(r1, "canonical_registry")
    r2_registry = _stage_by_name(r2, "canonical_registry")
    for registry, report, includes_optional in ((r1_registry, r1, False), (r2_registry, r2, True)):
        if registry.get("node_count") != EXPECTED_NODE_COUNT:
            raise RuntimeError("paired profile registry node count differs from release authority")
        if registry.get("base_ready_count") != EXPECTED_BASE_OPERATION_COUNT:
            raise RuntimeError("paired profile base-ready count differs from release authority")
        if len(registry.get("scp_operations", [])) != EXPECTED_OPTIONAL_OPERATION_COUNT:
            raise RuntimeError("paired profile optional operation count differs from release authority")
        attestation = registry.get("runtime_requirement_attestation", {})
        if attestation.get("ready_operation_count") != registry.get("ready_count"):
            raise RuntimeError("paired profile runtime attestation does not cover every ready operation")
        node_identities = set(registry.get("node_identities", []))
        optional_operations = set(registry.get("scp_operations", []))
        expected_operations = node_identities if includes_optional else node_identities - optional_operations
        attested_operations = attestation.get("operations", {})
        if set(attested_operations) != expected_operations:
            raise RuntimeError("paired profile runtime attestation operation identities are not exact")
        installed_versions = {
            _canonical_name(str(row["name"])): str(row["version"]) for row in report.get("installed_distributions", [])
        }
        used_versions: dict[str, str] = {}
        for operation_id, requirements in attested_operations.items():
            for distribution, expected_version in requirements.items():
                canonical_distribution = _canonical_name(str(distribution))
                expected_version = str(expected_version)
                actual_version = installed_versions.get(canonical_distribution)
                if actual_version != expected_version:
                    raise RuntimeError(
                        "paired profile runtime attestation disagrees with installed distributions: "
                        f"{operation_id}:{canonical_distribution} expected {expected_version}, "
                        f"installed {actual_version or 'absent'}"
                    )
                previous = used_versions.setdefault(canonical_distribution, expected_version)
                if previous != expected_version:
                    raise RuntimeError(f"paired ready operations require conflicting {canonical_distribution} versions")
        if attestation.get("installed_versions") != dict(sorted(used_versions.items())):
            raise RuntimeError("paired profile runtime attestation installed-version projection is not exact")
    if r1_registry.get("registry_digest") != r2_registry.get("registry_digest"):
        raise RuntimeError("canonical registry digest changes when SpectroChemPy is installed")
    if r1_registry.get("node_identities") != r2_registry.get("node_identities"):
        raise RuntimeError("canonical node identities change when SpectroChemPy is installed")
    if r1_registry.get("execution_contract_digests") != r2_registry.get("execution_contract_digests"):
        raise RuntimeError("execution contract digests change when SpectroChemPy is installed")
    if r1.get("source_revision") != r2.get("source_revision"):
        raise RuntimeError("paired profile reports do not bind the same source revision")
    optional_operations = set(r1_registry.get("scp_operations", []))
    if set(r1_registry.get("unavailable_operations", [])) != optional_operations:
        raise RuntimeError("R1 unavailable operations differ from the live optional set")
    if (
        r1_registry.get("ready_count") != EXPECTED_BASE_OPERATION_COUNT
        or r1_registry.get("unavailable_count") != EXPECTED_OPTIONAL_OPERATION_COUNT
    ):
        raise RuntimeError("R1 readiness is not the exact 86-ready/3-unavailable profile")
    if r2_registry.get("ready_count") != EXPECTED_NODE_COUNT or r2_registry.get("unavailable_count") != 0:
        raise RuntimeError("R2 readiness is not the exact all-ready profile")
    r1_isolation = _stage_by_name(r1, "profile_isolation")
    r2_isolation = _stage_by_name(r2, "profile_isolation")
    if r1_isolation.get("spectrochempy_distribution") != "absent":
        raise RuntimeError("R1 report does not prove SpectroChemPy distribution absence")
    if r2_isolation.get("spectrochempy_distribution") != "installed":
        raise RuntimeError("R2 report does not prove SpectroChemPy distribution presence")
    if r1_isolation.get("network_attempts") or r2_isolation.get("network_attempts"):
        raise RuntimeError("paired runtime profiles attempted network access")
    scp_execution = _stage_by_name(r2, "scp_execution")
    if set(scp_execution.get("operations", {})) != optional_operations:
        raise RuntimeError("R2 did not execute exactly all retained optional operations")
    if any(stage.get("name") == "scp_execution" for stage in r1.get("stages", [])):
        raise RuntimeError("R1 must not contain an optional SpectroChemPy execution stage")
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "status": "passed",
        "registry_digest": r1_registry["registry_digest"],
        "node_count": EXPECTED_NODE_COUNT,
        "base_ready_count": EXPECTED_BASE_OPERATION_COUNT,
        "optional_operations": sorted(optional_operations),
    }


def _run_probe_command(args: argparse.Namespace) -> int:
    report = _probe(profile_id=args.profile, simulated_forbidden_module=args.simulate_forbidden_module)
    _write_report(report, args.output)
    print(json.dumps({"profile_id": args.profile, "status": report["status"], "output": str(args.output)}))
    return 0 if report["status"] == args.expect else 1


def _compare_command(args: argparse.Namespace) -> int:
    r1 = json.loads(args.r1.read_text(encoding="utf-8"))
    r2 = json.loads(args.r2.read_text(encoding="utf-8"))
    result = _compare_profile_reports(r1, r2)
    print(json.dumps(result, sort_keys=True))
    return 0


def _build_and_run(args: argparse.Namespace) -> int:
    package_root = Path(__file__).resolve().parents[1]
    repository_root = package_root.parents[1]
    source_revision = _source_revision(repository_root)
    lock_path = package_root / "poetry.lock"
    child_environment = _clean_child_environment()
    with tempfile.TemporaryDirectory(prefix="spectra-r1-build-") as raw_build:
        build_root = Path(raw_build)
        dist_dir = build_root / "dist"
        environment = args.environment or build_root / "venv"
        constraints_path = build_root / "constraints.txt"
        roots, lock_digest, projection_digest = _write_lock_projection(
            lock_path,
            constraints_path,
            profile_id=args.profile,
        )
        _run(
            [args.python, "-m", "build", "--wheel", "--outdir", str(dist_dir), str(package_root)],
            cwd=build_root,
            environment=child_environment,
        )
        wheels = sorted(dist_dir.glob("spectra_sherpa-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected one spectra-sherpa wheel, found {wheels}")
        wheel = wheels[0]
        wheel_digest = _digest_bytes(wheel.read_bytes())

        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = _venv_python(environment)
        _run(
            [str(python), "-m", "pip", "install", "--constraint", str(constraints_path), *roots],
            cwd=build_root,
            environment=child_environment,
        )
        _run(
            [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
            cwd=build_root,
            environment=child_environment,
        )
        probe_environment = dict(child_environment)
        probe_environment.update(
            {
                "SPECTRA_PROFILE_SOURCE_REVISION": source_revision,
                "SPECTRA_PROFILE_WHEEL_SHA256": wheel_digest,
                "SPECTRA_PROFILE_LOCK_SHA256": lock_digest,
                "SPECTRA_PROFILE_PROJECTION_SHA256": projection_digest,
                "SPECTRA_PROFILE_HARNESS_SHA256": _digest_bytes(Path(__file__).resolve().read_bytes()),
                "SPECTRA_PROFILE_REPOSITORY_ROOT": str(repository_root),
                "SPECTRA_PROFILE_HOME": str(build_root / "profile-home"),
                "HOME": str(build_root / "profile-home"),
                "XDG_CONFIG_HOME": str(build_root / "profile-home" / ".config"),
            }
        )
        Path(probe_environment["SPECTRA_PROFILE_HOME"]).mkdir(parents=True, exist_ok=True)
        command = [
            str(python),
            str(Path(__file__).resolve()),
            "probe",
            "--output",
            str(args.output.resolve()),
            "--expect",
            args.expect,
            "--profile",
            args.profile,
        ]
        return subprocess.run(command, cwd=build_root, env=probe_environment, check=False).returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Build the wheel and execute the fresh R1 profile")
    run_parser.add_argument("--python", default=sys.executable)
    run_parser.add_argument("--environment", type=Path)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--expect", choices=("passed", "blocked", "failed"), default="passed")
    run_parser.add_argument("--profile", choices=("R1", "R2"), default="R1")
    run_parser.set_defaults(handler=_build_and_run)

    probe_parser = subparsers.add_parser("probe", help="Run inside an already isolated R1 environment")
    probe_parser.add_argument("--output", type=Path, required=True)
    probe_parser.add_argument("--expect", choices=("passed", "blocked", "failed"), default="passed")
    probe_parser.add_argument("--profile", choices=("R1", "R2"), default="R1")
    probe_parser.add_argument("--simulate-forbidden-module", choices=FORBIDDEN_MODULES)
    probe_parser.set_defaults(handler=_run_probe_command)

    compare_parser = subparsers.add_parser("compare", help="Validate paired R1 and R2 clean-room reports")
    compare_parser.add_argument("--r1", type=Path, required=True)
    compare_parser.add_argument("--r2", type=Path, required=True)
    compare_parser.set_defaults(handler=_compare_command)
    return parser


def main() -> int:
    args = _parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
