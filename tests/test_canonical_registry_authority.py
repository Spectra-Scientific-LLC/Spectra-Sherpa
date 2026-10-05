"""Regression gates for the single canonical node-registry authority."""

from __future__ import annotations

import ast
from pathlib import Path

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.services.dag.node_base import NodeMetadata, node_registry

_REPOSITORY = Path(__file__).resolve().parents[3]
_SOURCE_ROOTS = (
    _REPOSITORY / "packages/spectra-sherpa/src",
    _REPOSITORY / "packages/spectra-server/src",
)


def _python_sources() -> list[Path]:
    return [path for root in _SOURCE_ROOTS for path in root.rglob("*.py")]


def test_retired_contract_authorities_cannot_return() -> None:
    retired_files = (
        "first_party" + "_profile.py",
        "first_party" + "_parameter_rules.py",
        "provisional" + "_execution_contract.py",
    )
    assert not [path for root in _SOURCE_ROOTS for name in retired_files for path in root.rglob(name)]

    retired_symbols = (
        "NodeContract" + "Summary",
        "NodeContract" + "Status",
        "FIRST_PARTY_PLS" + "_PROFILE_V1",
        "requires_execution" + "_contract",
        "resolved_contract" + "_summary",
    )
    offenders: dict[str, str] = {}
    for path in _python_sources():
        source_text = path.read_text(encoding="utf-8")
        for symbol in retired_symbols:
            if symbol in source_text:
                offenders[str(path.relative_to(_REPOSITORY))] = symbol
    assert offenders == {}
    assert "contract_summary" not in NodeMetadata.__dataclass_fields__


def test_production_source_has_no_second_operation_to_contract_map() -> None:
    """Reject another literal profile or contract table of node identities."""

    operation_ids = {metadata.node_type for metadata in node_registry.list_nodes()}
    offenders: list[str] = []
    for path in _python_sources():
        source_text = path.read_text(encoding="utf-8")
        present_ids = {operation_id for operation_id in operation_ids if operation_id in source_text}
        if len(present_ids) < 2 or not any(term in source_text.lower() for term in ("contract", "managed", "profile")):
            continue
        tree = ast.parse(source_text, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None:
                continue
            keys = {
                item.value
                for item in ast.walk(value)
                if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value in operation_ids
            }
            # Frozen historical presentation prose is not a live execution
            # contract map. Keep this exception exact and limited to strings.
            if (
                path.relative_to(_REPOSITORY).as_posix()
                == "packages/spectra-server/src/spectrasherpa_server/harness_canonical_llm_proposal.py"
                and isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_V3_TO_V8_OPERATION_DESCRIPTIONS"
            ):
                assert isinstance(value, ast.Dict)
                assert len(value.keys) == 2
                assert all(
                    isinstance(item, ast.Constant) and isinstance(item.value, str)
                    for item in [*value.keys, *value.values]
                )
                continue
            source = ast.get_source_segment(source_text, node) or ""
            if len(keys) >= 2 and any(term in source.lower() for term in ("contract", "managed", "profile")):
                offenders.append(f"{path.relative_to(_REPOSITORY)}:{node.lineno}:{sorted(keys)}")
    assert offenders == []


def test_each_managed_operation_is_owned_by_exactly_one_registered_contract() -> None:
    owners: dict[str, int] = {}
    for metadata in node_registry.list_nodes():
        contract = metadata.resolved_execution_contract()
        if contract is None:
            continue
        operation_id = str(contract.payload["operation_id"])
        owners[operation_id] = owners.get(operation_id, 0) + 1
        assert operation_id == metadata.node_type
    assert owners
    assert set(owners.values()) == {1}
