"""Model lifecycle policy has one use/manage vocabulary."""

from __future__ import annotations

import ast
from pathlib import Path

from spectra_sherpa.app.contracts.demo_capabilities import (
    MODEL_CAPABILITIES,
    MODEL_MANAGE,
    MODEL_USE,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa"
RETIRED_MODEL_CAPABILITIES = frozenset(
    {"artifact_batch_run", "model_apply", "model_compare", "model_delete", "model_import", "model_update"}
)


def _guard_capabilities_in(tree: ast.AST) -> set[str]:
    imported_constants = {"MODEL_MANAGE": MODEL_MANAGE, "MODEL_USE": MODEL_USE}
    capabilities: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not isinstance(function, ast.Name) or function.id not in {"demo_guard", "check_demo_capability"}:
            continue
        if not node.args:
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            capabilities.add(argument.value)
        elif isinstance(argument, ast.Name) and argument.id in imported_constants:
            capabilities.add(imported_constants[argument.id])
    return capabilities


def _guard_capabilities(path: Path) -> set[str]:
    return _guard_capabilities_in(ast.parse(path.read_text(encoding="utf-8")))


def _function_guard_capabilities(path: Path, function_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    )
    return _guard_capabilities_in(function)


def test_model_routes_use_only_use_and_manage_capabilities() -> None:
    routes = PACKAGE_ROOT / "app" / "api" / "v1" / "routes"
    capabilities = _guard_capabilities(routes / "models.py") | _guard_capabilities(routes / "runs.py")

    assert MODEL_CAPABILITIES <= capabilities
    assert capabilities.isdisjoint(RETIRED_MODEL_CAPABILITIES)


def test_retired_model_capabilities_are_absent_from_runtime_policy() -> None:
    runtime = PACKAGE_ROOT / "app"
    guarded_capabilities: set[str] = set()
    for path in runtime.rglob("*.py"):
        guarded_capabilities.update(_guard_capabilities(path))

    assert guarded_capabilities.isdisjoint(RETIRED_MODEL_CAPABILITIES)


def test_model_import_keeps_management_and_upload_guards() -> None:
    models_route = PACKAGE_ROOT / "app" / "api" / "v1" / "routes" / "models.py"

    assert _function_guard_capabilities(models_route, "import_canonical_full_refit") == {
        MODEL_MANAGE,
        "data_upload",
    }
