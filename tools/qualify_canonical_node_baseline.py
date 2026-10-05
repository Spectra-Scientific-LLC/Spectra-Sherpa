#!/usr/bin/env python3
"""Build and execute the exact-tree, paired-platform canonical-node qualification."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MANIFEST_SCHEMA = "spectra-canonical-node-qualification-manifest/2"
_RECEIPT_SCHEMA = "spectra-canonical-node-platform-receipt/1"
_PAIR_SCHEMA = "spectra-canonical-node-paired-qualification/1"
_PRODUCT_PROJECTION_SCHEMA = "spectra-canonical-node-qualified-product-projection/1"
_ALLOWED_PREQUALIFICATION_FINDINGS = frozenset({"evidence_qualification_gap"})
_NATIVE_CLEAN_ROOM_FILE = "packages/spectra-sherpa/tests/test_native_opus_qualification.py"
_RETAINED_RECEIPTS = {
    "Darwin": "docs/evidence/canonical-node-qualification-macos.json",
    "Linux": "docs/evidence/canonical-node-qualification-ubuntu.json",
}
_RETAINED_PAIR = "docs/evidence/canonical-node-paired-qualification.json"
_RETAINED_PRODUCT_PROJECTION = "docs/evidence/canonical-node-qualified-product-projection.json"
_QUALIFIED_PRODUCT_PATHS = (
    "packages/spectra-sherpa/src",
    "packages/spectra-sherpa/data",
    "packages/spectra-sherpa/pyproject.toml",
    "packages/spectra-sherpa/poetry.lock",
)
_QUALIFIED_PRODUCT_EXCLUSIONS = (
    "packages/spectra-sherpa/src/spectra_sherpa/static/**",
    "packages/spectra-sherpa/src/spectra_sherpa/sdk/__init__.py",
    "packages/spectra-sherpa/src/spectra_sherpa/sdk/canonical_public_fixture.py",
)


class QualificationError(RuntimeError):
    """The qualification authority is incomplete, stale, or failed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), f"{path} must contain one JSON object")
    return payload


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_test_file(selector: str) -> str | None:
    """Return the source file for a repo-local pytest path or node selector."""

    file_path = selector.split("::", 1)[0]
    if not file_path.startswith("packages/spectra-sherpa/tests/") or not file_path.endswith(".py"):
        return None
    return file_path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _evidence_paths(repository_root: Path) -> dict[str, Path]:
    evidence = repository_root / "docs/evidence"
    return {
        "assessments": evidence / "canonical-node-readiness-assessments.json",
        "audit": evidence / "canonical-node-readiness-audit.json",
        "census": evidence / "m4-node-contract-census.json",
        "project_map": evidence / "canonical-node-project-repair-map.json",
        "near_duplicates": evidence / "canonical-node-near-duplicate-families.json",
    }


def build_manifest(repository_root: Path) -> dict[str, Any]:
    """Project the checked four-star authorities into one executable manifest."""

    paths = _evidence_paths(repository_root)
    source = {name: _load(path) for name, path in paths.items()}
    audit = source["audit"]
    census = source["census"]
    project_map = source["project_map"]
    near_duplicates = source["near_duplicates"]
    _require(
        audit.get("aggregates", {}).get("total_nodes") == len(census["nodes"]) > 0,
        "readiness audit must cover the current registry",
    )
    _require(census.get("registry_digest") == audit.get("registry_digest"), "audit/census registry drift")
    _require(project_map.get("registry_digest") == audit.get("registry_digest"), "audit/project-map registry drift")
    _require(
        near_duplicates.get("classification_counts", {}).get("verification_critical") == 0,
        "verification-critical duplicate logic remains",
    )

    consumers = {row["consumer_id"]: row for row in project_map["consumers"]}
    map_nodes = {row["node_type"]: row for row in project_map["nodes"]}
    nodes: list[dict[str, Any]] = []
    all_test_selectors: set[str] = set()
    for row in audit["nodes"]:
        node_type = row["node_type"]
        _require(row["stars"] == 4, f"{node_type} is not at the four-star qualification baseline")
        findings = set(row["fault_patterns"])
        _require(
            findings <= _ALLOWED_PREQUALIFICATION_FINDINGS,
            f"{node_type} retains non-qualification findings: {sorted(findings)}",
        )
        candidates: list[dict[str, Any]] = []
        for binding in map_nodes[node_type]["consumer_bindings"]:
            if binding.get("binding_status") != "existing_execution":
                continue
            consumer = consumers[binding["consumer_id"]]
            if consumer.get("evidence_test_id") and consumer.get("evidence_test_path"):
                candidates.append(consumer)
        _require(candidates, f"{node_type} has no exact executable consumer proof")
        consumer = sorted(
            candidates,
            key=lambda item: (
                not item["evidence_test_path"].startswith("packages/spectra-sherpa/tests/"),
                item["consumer_id"],
            ),
        )[0]

        test_selectors = {reference for reference in row["evidence_refs"] if _evidence_test_file(reference) is not None}
        test_selectors.add(consumer["evidence_test_path"])
        _require(test_selectors, f"{node_type} has no executable evidence selectors")
        evidence_files: list[dict[str, str]] = []
        seen_files: set[str] = set()
        for selector in sorted(test_selectors):
            relative = _evidence_test_file(selector)
            _require(relative is not None, f"{node_type} has an invalid evidence selector: {selector}")
            all_test_selectors.add(selector)
            if relative in seen_files:
                continue
            absolute = repository_root / relative
            _require(absolute.is_file(), f"{node_type} evidence file is missing: {relative}")
            evidence_files.append({"path": relative, "sha256": _file_digest(absolute)})
            seen_files.add(relative)
        nodes.append(
            {
                "node_type": node_type,
                "prequalification_stars": 4,
                "consumer_id": consumer["consumer_id"],
                "consumer_test_id": consumer["evidence_test_id"],
                "evidence_files": evidence_files,
            }
        )

    _require([row["node_type"] for row in nodes] == sorted(row["node_type"] for row in nodes), "nodes unsorted")
    clean_room_selectors = sorted(
        selector for selector in all_test_selectors if _evidence_test_file(selector) == _NATIVE_CLEAN_ROOM_FILE
    )
    general_selectors = sorted(set(all_test_selectors) - set(clean_room_selectors))
    _require(clean_room_selectors, "native OPUS clean-room qualification is missing")
    _require(general_selectors, "general canonical-node qualification is missing")
    manifest: dict[str, Any] = {
        "schema_version": _MANIFEST_SCHEMA,
        "qualification_scope": "all-active-canonical-nodes",
        "node_count": len(nodes),
        "registry_digest": audit["registry_digest"],
        "readiness_report_digest": audit["report_digest"],
        "project_map_digest": project_map["map_digest"],
        "near_duplicate_evidence_sha256": _file_digest(paths["near_duplicates"]),
        "source_artifacts": {
            name: {"path": path.relative_to(repository_root).as_posix(), "sha256": _file_digest(path)}
            for name, path in sorted(paths.items())
        },
        "test_batches": [
            {
                "batch_id": "native-opus-clean-room",
                "purpose": "Prove native OPUS ingestion before any optional SpectroChemPy module is imported.",
                "selectors": clean_room_selectors,
            },
            {
                "batch_id": "canonical-node-evidence",
                "purpose": "Execute every remaining node oracle, consumer, performance, and conformance proof.",
                "selectors": general_selectors,
            },
        ],
        "nodes": nodes,
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest


def _validate_manifest(
    repository_root: Path,
    manifest: dict[str, Any],
    *,
    allow_retained_pair: bool = False,
) -> None:
    _require(manifest.get("schema_version") == _MANIFEST_SCHEMA, "unexpected qualification manifest schema")
    stated = manifest.get("manifest_digest")
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    _require(stated == _digest(unsigned), "qualification manifest digest is invalid")
    readiness_audit = _load(_evidence_paths(repository_root)["audit"])
    if (
        allow_retained_pair
        and isinstance(readiness_audit.get("paired_qualification"), dict)
        and (repository_root / _RETAINED_PAIR).is_file()
    ):
        validate_retained_pair(repository_root, manifest)
        return
    _require(manifest == build_manifest(repository_root), "qualification manifest is stale")


def _git(repository_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        capture_output=True,
        check=False,
        text=True,
    )
    _require(result.returncode == 0, result.stdout + result.stderr)
    return result.stdout.strip()


def _test_case_identity(case: ET.Element) -> str:
    classname = case.attrib.get("classname", "").strip()
    name = case.attrib.get("name", "").strip()
    _require(bool(classname and name), "JUnit contains an unidentified test case")
    return f"{classname}::{name}"


def _parse_junit(path: Path) -> tuple[list[str], int, int, int]:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    passed = sorted(
        _test_case_identity(case)
        for case in cases
        if case.find("failure") is None and case.find("error") is None and case.find("skipped") is None
    )
    _require(len(passed) == len(set(passed)), "JUnit contains duplicate test identities")
    return passed, failures, errors, skipped


def _scientific_runtime() -> dict[str, str]:
    distributions = ("numpy", "scipy", "scikit-learn", "spectrochempy", "h5py", "pandas")
    versions: dict[str, str] = {}
    for distribution in distributions:
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise QualificationError(f"required scientific runtime is missing: {distribution}") from exc
    return versions


def run_qualification(
    repository_root: Path,
    manifest_path: Path,
    receipt_path: Path,
    source_revision: str,
) -> dict[str, Any]:
    """Run every evidence file and emit a data-free exact-tree platform receipt."""

    manifest = _load(manifest_path)
    _validate_manifest(repository_root, manifest)
    head = _git(repository_root, "rev-parse", "HEAD")
    _require(source_revision == head and len(source_revision) == 40, "qualification source revision differs from HEAD")
    _require(
        not _git(repository_root, "status", "--porcelain", "--untracked-files=all"),
        "qualification requires a clean worktree",
    )
    source_tree = _git(repository_root, "rev-parse", "HEAD^{tree}")

    all_passed: list[str] = []
    batch_receipts: list[dict[str, Any]] = []
    total_failures = 0
    total_errors = 0
    total_skipped = 0
    with tempfile.TemporaryDirectory(prefix="canonical-node-qualification-") as temporary:
        for batch in manifest["test_batches"]:
            junit = Path(temporary) / f"{batch['batch_id']}.xml"
            command = [
                sys.executable,
                "-m",
                "pytest",
                *batch["selectors"],
                "-q",
                "--no-cov",
                f"--junitxml={junit}",
            ]
            result = subprocess.run(command, cwd=repository_root, check=False)
            _require(result.returncode == 0, f"canonical-node qualification batch failed: {batch['batch_id']}")
            passed, failures, errors, skipped = _parse_junit(junit)
            _require(failures == 0 and errors == 0, f"{batch['batch_id']} contains failed or errored tests")
            _require(skipped == 0, f"{batch['batch_id']} contains skipped evidence tests")
            all_passed.extend(passed)
            total_failures += failures
            total_errors += errors
            total_skipped += skipped
            batch_receipts.append(
                {
                    "batch_id": batch["batch_id"],
                    "passed": len(passed),
                    "passed_test_ids_sha256": _digest(passed),
                }
            )

    _require(len(all_passed) == len(set(all_passed)), "qualification batches contain duplicate test identities")
    passed = sorted(all_passed)
    failures = total_failures
    errors = total_errors
    skipped = total_skipped
    _require(bool(passed), "qualification executed no tests")
    receipt: dict[str, Any] = {
        "schema_version": _RECEIPT_SCHEMA,
        "source_revision": source_revision,
        "source_tree": source_tree,
        "manifest_digest": manifest["manifest_digest"],
        "registry_digest": manifest["registry_digest"],
        "project_map_digest": manifest["project_map_digest"],
        "node_count": manifest["node_count"],
        "qualified_node_types": [row["node_type"] for row in manifest["nodes"]],
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "scientific_runtime": _scientific_runtime(),
        "tests": {
            "batches": batch_receipts,
            "passed": len(passed),
            "failed": failures,
            "errors": errors,
            "skipped": skipped,
            "passed_test_ids_sha256": _digest(passed),
        },
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt["receipt_digest"] = _digest(receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _validate_receipt(receipt: dict[str, Any]) -> None:
    _require(receipt.get("schema_version") == _RECEIPT_SCHEMA, "unexpected platform receipt schema")
    stated = receipt.get("receipt_digest")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    _require(stated == _digest(unsigned), "platform receipt digest is invalid")
    _require(
        type(receipt.get("node_count")) is int and receipt["node_count"] > 0, "platform receipt has invalid node count"
    )
    nodes = receipt.get("qualified_node_types", [])
    _require(len(nodes) == len(set(nodes)) == receipt["node_count"], "platform receipt node inventory is incomplete")
    _require(receipt.get("tests", {}).get("failed") == 0, "platform receipt contains failed tests")
    _require(receipt.get("tests", {}).get("errors") == 0, "platform receipt contains errored tests")
    _require(receipt.get("tests", {}).get("skipped") == 0, "platform receipt contains skipped tests")
    batches = receipt.get("tests", {}).get("batches")
    _require(isinstance(batches, list) and len(batches) == 2, "platform receipt has incomplete test batches")
    _require(
        [batch.get("batch_id") for batch in batches] == ["native-opus-clean-room", "canonical-node-evidence"],
        "platform receipt test batches are not the governed pair",
    )
    _require(
        sum(batch.get("passed", -1) for batch in batches) == receipt["tests"]["passed"],
        "platform receipt test batch counts disagree",
    )


def _build_pair(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one pair after validating two platform receipts."""

    for receipt in receipts:
        _validate_receipt(receipt)
    systems = {receipt["platform"]["system"] for receipt in receipts}
    _require(systems == {"Darwin", "Linux"}, "paired qualification requires Darwin and Linux receipts")
    matching_fields = (
        "source_revision",
        "source_tree",
        "manifest_digest",
        "registry_digest",
        "project_map_digest",
        "node_count",
        "qualified_node_types",
        "scientific_runtime",
    )
    for field in matching_fields:
        _require(receipts[0][field] == receipts[1][field], f"paired receipts disagree on {field}")
    _require(
        receipts[0]["tests"]["passed_test_ids_sha256"] == receipts[1]["tests"]["passed_test_ids_sha256"],
        "paired platforms executed different test identities",
    )
    _require(receipts[0]["tests"]["batches"] == receipts[1]["tests"]["batches"], "paired test batches disagree")
    pair: dict[str, Any] = {
        "schema_version": _PAIR_SCHEMA,
        "source_revision": receipts[0]["source_revision"],
        "source_tree": receipts[0]["source_tree"],
        "manifest_digest": receipts[0]["manifest_digest"],
        "registry_digest": receipts[0]["registry_digest"],
        "project_map_digest": receipts[0]["project_map_digest"],
        "node_count": receipts[0]["node_count"],
        "qualified_node_types": receipts[0]["qualified_node_types"],
        "passed_test_count": receipts[0]["tests"]["passed"],
        "passed_test_ids_sha256": receipts[0]["tests"]["passed_test_ids_sha256"],
        "test_batches": receipts[0]["tests"]["batches"],
        "platform_receipts": {receipt["platform"]["system"]: receipt["receipt_digest"] for receipt in receipts},
    }
    pair["pair_digest"] = _digest(pair)
    return pair


def verify_pair(mac_path: Path, ubuntu_path: Path, output_path: Path) -> dict[str, Any]:
    """Require identical test and node authority from one Darwin and one Linux run."""

    pair = _build_pair([_load(mac_path), _load(ubuntu_path)])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(pair, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return pair


def _git_blob(repository_root: Path, revision: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative_path}"],
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    _require(
        result.returncode == 0,
        f"qualified source artifact is unavailable: {revision}:{relative_path}",
    )
    return result.stdout


def _git_commit_available(repository_root: Path, revision: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _current_product_projection(repository_root: Path, pair: dict[str, Any]) -> dict[str, Any]:
    """Digest tracked node-science files without depending on Git history depth.

    The compiled Workbench, SDK discovery initializer, and campaign fixture
    adapter are release-product surfaces, but none implements node science.
    They have independent frontend, package-content, import-boundary,
    installation-profile, and signed-reproduction gates; including them here
    would falsely invalidate all numerical node qualifications after a UI
    rebuild, tab-completion change, or campaign-package projection change.
    """

    pathspecs = _qualified_product_pathspecs()

    _require(
        not _git(repository_root, "status", "--porcelain", "--untracked-files=all", "--", *pathspecs),
        "qualified product paths contain tracked or untracked worktree changes",
    )
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", *pathspecs],
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    _require(result.returncode == 0, result.stderr.decode("utf-8", errors="replace"))
    relative_paths = sorted(path.decode("utf-8") for path in result.stdout.split(b"\0") if path)
    _require(bool(relative_paths), "qualified product projection contains no tracked files")
    entries = []
    for relative_path in relative_paths:
        path = repository_root / relative_path
        _require(path.is_file(), f"qualified product file is missing: {relative_path}")
        entries.append({"path": relative_path, "sha256": _file_digest(path)})
    return {
        "schema_version": _PRODUCT_PROJECTION_SCHEMA,
        "source_revision": pair["source_revision"],
        "source_tree": pair["source_tree"],
        "pair_digest": pair["pair_digest"],
        "tracked_roots": list(_QUALIFIED_PRODUCT_PATHS),
        "excluded_non_node_surfaces": list(_QUALIFIED_PRODUCT_EXCLUSIONS),
        "file_count": len(entries),
        "product_digest": _digest(entries),
    }


def _qualified_product_pathspecs() -> tuple[str, ...]:
    return (*_QUALIFIED_PRODUCT_PATHS, *(f":(exclude){path}" for path in _QUALIFIED_PRODUCT_EXCLUSIONS))


def _validate_historical_authority(
    repository_root: Path,
    manifest: dict[str, Any],
    pair: dict[str, Any],
) -> None:
    """Use full Git history when available as an additional provenance proof."""

    revision = pair["source_revision"]
    _git(repository_root, "merge-base", "--is-ancestor", revision, "HEAD")
    _require(
        _git(repository_root, "rev-parse", f"{revision}^{{tree}}") == pair["source_tree"],
        "paired qualification source tree is invalid",
    )
    historical_manifest = json.loads(
        _git_blob(repository_root, revision, "docs/evidence/canonical-node-qualification-manifest.json")
    )
    _require(historical_manifest == manifest, "checked manifest differs from the qualified source revision")

    historical_files: dict[str, str] = {}
    for artifact in manifest["source_artifacts"].values():
        historical_files[artifact["path"]] = artifact["sha256"]
    for node in manifest["nodes"]:
        for artifact in node["evidence_files"]:
            historical_files[artifact["path"]] = artifact["sha256"]
    for relative_path, expected_sha256 in sorted(historical_files.items()):
        actual_sha256 = hashlib.sha256(_git_blob(repository_root, revision, relative_path)).hexdigest()
        _require(actual_sha256 == expected_sha256, f"qualified source digest is invalid: {relative_path}")

    _git(repository_root, "diff", "--quiet", revision, "--", *_qualified_product_pathspecs())


def build_retained_product_projection(repository_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the shallow-checkout authority only from a full qualified history."""

    receipt_paths = {system: repository_root / relative_path for system, relative_path in _RETAINED_RECEIPTS.items()}
    pair = _build_pair([_load(receipt_paths["Darwin"]), _load(receipt_paths["Linux"])])
    _require(pair["manifest_digest"] == manifest["manifest_digest"], "paired qualification binds another manifest")
    _require(
        _git_commit_available(repository_root, pair["source_revision"]),
        "qualified source commit is required to build the retained product projection",
    )
    _validate_historical_authority(repository_root, manifest, pair)
    return _current_product_projection(repository_root, pair)


def validate_retained_pair(repository_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate checked receipts and prove current node science still matches them."""

    receipt_paths = {system: repository_root / relative_path for system, relative_path in _RETAINED_RECEIPTS.items()}
    for system, path in receipt_paths.items():
        _require(path.is_file(), f"retained {system} qualification receipt is missing")
    pair_path = repository_root / _RETAINED_PAIR
    _require(pair_path.is_file(), "retained paired qualification receipt is missing")
    projection_path = repository_root / _RETAINED_PRODUCT_PROJECTION
    _require(projection_path.is_file(), "retained qualified-product projection is missing")

    expected = _build_pair([_load(receipt_paths["Darwin"]), _load(receipt_paths["Linux"])])
    pair = _load(pair_path)
    _require(pair == expected, "retained paired qualification does not reproduce its platform receipts")
    _require(pair["manifest_digest"] == manifest["manifest_digest"], "paired qualification binds another manifest")

    projection = _load(projection_path)
    _require(
        projection == _current_product_projection(repository_root, pair),
        "current node product differs from the retained qualified projection",
    )
    evidence_files: dict[str, str] = {}
    for node in manifest["nodes"]:
        for artifact in node["evidence_files"]:
            evidence_files[artifact["path"]] = artifact["sha256"]
    for relative_path, expected_sha256 in sorted(evidence_files.items()):
        path = repository_root / relative_path
        _require(path.is_file(), f"qualified evidence file is missing: {relative_path}")
        _require(_file_digest(path) == expected_sha256, f"qualified evidence file changed: {relative_path}")

    if _git_commit_available(repository_root, pair["source_revision"]):
        _validate_historical_authority(repository_root, manifest, pair)
    return pair


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--output", type=Path, required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--manifest", type=Path, required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--manifest", type=Path, required=True)
    run_parser.add_argument("--receipt", type=Path, required=True)
    run_parser.add_argument("--source-revision", required=True)
    pair_parser = subparsers.add_parser("verify-pair")
    pair_parser.add_argument("--mac", type=Path, required=True)
    pair_parser.add_argument("--ubuntu", type=Path, required=True)
    pair_parser.add_argument("--output", type=Path, required=True)
    projection_parser = subparsers.add_parser("build-product-projection")
    projection_parser.add_argument("--manifest", type=Path, required=True)
    projection_parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    repository_root = _repository_root()

    if arguments.command == "build":
        payload = build_manifest(repository_root)
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif arguments.command == "check":
        _validate_manifest(repository_root, _load(arguments.manifest), allow_retained_pair=True)
    elif arguments.command == "run":
        run_qualification(
            repository_root,
            arguments.manifest,
            arguments.receipt,
            arguments.source_revision,
        )
    elif arguments.command == "verify-pair":
        verify_pair(arguments.mac, arguments.ubuntu, arguments.output)
    else:
        projection = build_retained_product_projection(repository_root, _load(arguments.manifest))
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(projection, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except QualificationError as exc:
        raise SystemExit(f"canonical-node qualification failed: {exc}") from exc
