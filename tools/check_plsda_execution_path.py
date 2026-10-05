#!/usr/bin/env python3
"""Fail closed on a second PLS-DA fit or validation implementation.

PLS-DA fitting is owned by the registered node and validation is owned by the
shared fold executor.  This AST gate covers production and qualification tools
so a dataset-specific script cannot bypass either authority.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from pathlib import Path
from typing import Iterable

_ROOT = Path(__file__).resolve().parents[3]
_SELF = Path(__file__).resolve()
_SYMBOL_ALLOWLIST = {
    "_native_plsda_fit": {
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_nodes.py",
    },
    "PLSDANode": {
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/__init__.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_nodes.py",
    },
    "apply_plsda_fitted_state": {
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/application_nodes.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_nodes.py",
    },
    "predict_fitted_classification": {
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/fold_graph_executor.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_nodes.py",
    },
    "PLSRegression": set(),
    "fit_simpls": {
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_nodes.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/fitted_pls_node.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/pls_core.py",
    },
    "fit_simpls_exact": {
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/pls_core.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/selection/cars_node.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/selection/ipls_node.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/selection/mcuve_node.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/selection/nested_cv_node.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/selection/stability_node.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/transfer/pds_node.py",
    },
    "SherpaPLSDAArtifact": {
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/canonical_model_bridge.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_nodes.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_state.py",
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/load_apply_node.py",
    },
}
_DIRECT_LIFECYCLE_METHODS = {
    "fit_fitted_state",
    "apply_fitted_state",
    "predict_fitted_labels",
    "predict_fitted_classification",
}
_LIFECYCLE_CALLSITE_ALLOWLIST = {
    # Model-aware prediction dispatches only admitted regression producers and never fits.
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/predict_regression_node.py": (
        ("apply_fitted_state", 73, 26),
    ),
    # Saved artifacts delegate application to the same canonical node, never refit.
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/saved_native_model.py": (
        ("apply_fitted_state", 152, 30),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/fitted_regression_nodes.py": (
        ("fit_fitted_state", 98, 16),
        ("apply_fitted_state", 119, 22),
        ("fit_fitted_state", 128, 16),
        ("apply_fitted_state", 130, 22),
        ("apply_fitted_state", 224, 32),
    ),
    # Phase 8 discovers and replaces every registered fitted-state method with
    # a denial before its application-only DAG is executed.  These references
    # are guards, not lifecycle invocations.
    "packages/spectra-sherpa/tools/avatar_omnic_phase8_application.py": (
        ("fit_fitted_state", 351, 31),
        ("fit_fitted_state", 352, 32),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/fold_graph_executor.py": (
        ("fit_fitted_state", 88, 24),
        ("fit_fitted_state", 113, 24),
        ("fit_fitted_state", 847, 42),
        ("apply_fitted_state", 848, 43),
        ("apply_fitted_state", 865, 28),
        ("apply_fitted_state", 866, 27),
        ("fit_fitted_state", 934, 42),
        ("apply_fitted_state", 935, 43),
        ("apply_fitted_state", 952, 28),
        ("apply_fitted_state", 953, 27),
        ("fit_fitted_state", 965, 42),
        ("predict_fitted_labels", 967, 20),
        ("apply_fitted_state", 969, 25),
        ("fit_fitted_state", 1104, 42),
        ("apply_fitted_state", 1105, 43),
        ("apply_fitted_state", 1119, 28),
        ("apply_fitted_state", 1120, 27),
        ("fit_fitted_state", 1150, 42),
        ("predict_fitted_classification", 1153, 39),
        ("predict_fitted_classification", 1158, 20),
        ("predict_fitted_labels", 1160, 26),
        ("apply_fitted_state", 1160, 78),
        ("fit_fitted_state", 1737, 36),
        ("apply_fitted_state", 1738, 38),
        ("fit_fitted_state", 1757, 36),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/application_nodes.py": (
        ("apply_fitted_state", 31, 0),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_state.py": (
        ("apply_fitted_state", 435, 4),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/apply_fitted_pls_node.py": (
        ("apply_fitted_state", 193, 22),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/fitted_pls_node.py": (
        ("apply_fitted_state", 639, 22),
    ),
    (
        "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/preprocessing/"
        "apply_fitted_preprocessing_nodes.py"
    ): (
        ("apply_fitted_state", 109, 17),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/preprocessing/apply_fitted_scale_node.py": (
        ("apply_fitted_state", 114, 17),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/preprocessing/emsc_node.py": (
        ("fit_fitted_state", 526, 16),
        ("apply_fitted_state", 527, 17),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/preprocessing/msc_node.py": (
        ("fit_fitted_state", 422, 16),
        ("apply_fitted_state", 423, 17),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/preprocessing/osc_node.py": (
        ("fit_fitted_state", 588, 16),
        ("apply_fitted_state", 589, 17),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/preprocessing/scale_node.py": (
        ("fit_fitted_state", 283, 16),
        ("apply_fitted_state", 284, 17),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/selection/cars_node.py": (
        ("fit_fitted_state", 617, 12),
        ("apply_fitted_state", 618, 17),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/selection/ipls_node.py": (
        ("fit_fitted_state", 526, 12),
        ("apply_fitted_state", 527, 15),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/selection/mcuve_node.py": (
        ("fit_fitted_state", 402, 12),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/selection/spa_node.py": (
        ("fit_fitted_state", 475, 12),
        ("apply_fitted_state", 476, 15),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/selection/stability_node.py": (
        ("fit_fitted_state", 380, 12),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/transfer/apply_node.py": (
        ("apply_fitted_state", 96, 17),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/transfer/ds_node.py": (
        ("fit_fitted_state", 168, 16),
        ("apply_fitted_state", 169, 38),
        ("apply_fitted_state", 174, 34),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/transfer/pds_node.py": (
        ("fit_fitted_state", 297, 16),
        ("apply_fitted_state", 298, 38),
        ("apply_fitted_state", 303, 34),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/transfer/sws_node.py": (
        ("fit_fitted_state", 174, 16),
        ("apply_fitted_state", 175, 38),
        ("apply_fitted_state", 179, 34),
    ),
    # The duplication scanner names lifecycle methods only to classify
    # structural siblings. These two literal inventory labels never dispatch,
    # fit, or apply a scientific operation.
    "packages/spectra-sherpa/tools/detect_node_duplication.py": (
        ("apply_fitted_state", 44, 4),
        ("fit_fitted_state", 45, 4),
    ),
    # Canonical reproduction applies an immutable imported artifact through a
    # second path; it does not fit or validate a candidate.
    "packages/spectra-sherpa/src/spectra_sherpa/sdk/canonical_reproduction.py": (
        ("apply_fitted_state", 377, 34),
        ("predict_fitted_labels", 385, 51),
    ),
}
_BRIDGE_CONVERSION_CALLSITE_ALLOWLIST = {
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/canonical_model_bridge.py": (
        ("SherpaPLSDAArtifact.from_fitted_state", 278, 17),
        ("native.to_fitted_state", 281, 36),
        ("native.to_artifact", 284, 37),
        ("SherpaPLSDAArtifact.from_artifact", 506, 17),
        ("native.to_fitted_state", 507, 38),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_nodes.py": (
        ("core['artifact'].to_fitted_state", 199, 24),
        ("SherpaPLSDAArtifact.from_fitted_state", 221, 15),
        ("core['artifact'].to_fitted_state", 611, 32),
        ("core['artifact'].to_fitted_state", 642, 15),
        ("SherpaPLSDAArtifact.from_fitted_state", 661, 19),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/classification/plsda_state.py": (
        ("self.to_artifact", 379, 27),
        ("cls.from_artifact", 403, 15),
        ("SherpaPLSDAArtifact.from_fitted_state", 414, 15),
        ("SherpaPLSDAArtifact.from_fitted_state", 424, 11),
    ),
    "packages/spectra-sherpa/src/spectra_sherpa/app/services/dag/nodes/modeling/load_apply_node.py": (
        ("extract_cls.from_artifact", 179, 14),
        ("extract.to_fitted_state", 400, 8),
    ),
}


def _attribute_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute_name(node.value)
        return f"{prefix}.{node.attr}" if prefix is not None else None
    return None


def _bridge_conversion_calls(tree: ast.AST) -> list[tuple[str, int, int]]:
    observed: list[tuple[str, int, int]] = []
    for item in ast.walk(tree):
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "SherpaPLSDAArtifact":
            observed.append(("SherpaPLSDAArtifact.__init__", item.lineno, item.col_offset))
        elif (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr in {"from_fitted_state", "from_artifact", "to_fitted_state", "to_artifact"}
        ):
            qualified = _attribute_name(item.func)
            if qualified is None and isinstance(item.func.value, ast.Subscript):
                owner = ast.unparse(item.func.value)
                qualified = f"{owner}.{item.func.attr}"
            observed.append((qualified or f"<dynamic>.{item.func.attr}", item.lineno, item.col_offset))
    return observed


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _static_string(node: ast.AST) -> str | None:
    """Resolve a small, bounded set of literal-only string expressions."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        if left is not None and right is not None and len(left) + len(right) <= 256:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts = [_static_string(value) for value in node.values]
        if all(part is not None for part in parts):
            result = "".join(part for part in parts if part is not None)
            return result if len(result) <= 256 else None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], (ast.List, ast.Tuple))
    ):
        separator = _static_string(node.func.value)
        parts = [_static_string(item) for item in node.args[0].elts]
        if separator is not None and all(part is not None for part in parts):
            result = separator.join(part for part in parts if part is not None)
            return result if len(result) <= 256 else None
    return None


def _names(node: ast.AST) -> Iterable[tuple[str, int, int]]:
    for item in ast.walk(node):
        if isinstance(item, ast.ImportFrom):
            for alias in item.names:
                yield alias.name.rsplit(".", 1)[-1], item.lineno, item.col_offset
        elif isinstance(item, ast.Import):
            for alias in item.names:
                yield alias.name.rsplit(".", 1)[-1], item.lineno, item.col_offset
        elif isinstance(item, ast.Name):
            yield item.id, item.lineno, item.col_offset
        elif isinstance(item, ast.Attribute):
            yield item.attr, item.lineno, item.col_offset
        elif isinstance(item, ast.Constant) and isinstance(item.value, str):
            yield item.value, item.lineno, item.col_offset
        elif isinstance(item, (ast.BinOp, ast.Call, ast.JoinedStr)):
            value = _static_string(item)
            if value is not None:
                yield value, item.lineno, item.col_offset


def scan_python_path(path: Path, *, root: Path = _ROOT) -> list[str]:
    """Return exact violations for one Python source file."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return [f"{path}: cannot parse: {exc}"]
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = path.name
    violations: list[str] = []
    seen: set[tuple[str, int, int]] = set()
    observed_lifecycle_calls: list[tuple[str, int, int]] = []
    for name, line, column in _names(tree):
        key = (name, line, column)
        if name in _DIRECT_LIFECYCLE_METHODS:
            observed_lifecycle_calls.append(key)
        if key in seen:
            continue
        seen.add(key)
        allowed = _SYMBOL_ALLOWLIST.get(name)
        if allowed is not None and relative not in allowed:
            violations.append(f"{relative}:{line}: forbidden PLS-DA authority reference {name}")
    expected = Counter(_LIFECYCLE_CALLSITE_ALLOWLIST.get(relative, ()))
    observed = Counter(observed_lifecycle_calls)
    for name, line, column in (observed - expected).elements():
        violations.append(
            f"{relative}:{line}:{column}: fitted-node lifecycle callsite is outside the closed inventory {name}"
        )
    for name, line, column in (expected - observed).elements():
        violations.append(
            f"{relative}:{line}:{column}: fitted-node lifecycle inventory entry is stale or missing {name}"
        )
    bridge_observed = Counter(
        _bridge_conversion_calls(tree) if relative in _SYMBOL_ALLOWLIST["SherpaPLSDAArtifact"] else ()
    )
    bridge_expected = Counter(_BRIDGE_CONVERSION_CALLSITE_ALLOWLIST.get(relative, ()))
    for name, line, column in (bridge_observed - bridge_expected).elements():
        violations.append(
            f"{relative}:{line}:{column}: PLS-DA bridge conversion is outside the closed inventory {name}"
        )
    for name, line, column in (bridge_expected - bridge_observed).elements():
        violations.append(
            f"{relative}:{line}:{column}: PLS-DA bridge conversion inventory entry is stale or missing {name}"
        )
    return violations


def scan_repository(root: Path = _ROOT) -> list[str]:
    paths = (
        sorted((root / "packages" / "spectra-sherpa" / "src").rglob("*.py"))
        + sorted((root / "packages" / "spectra-sherpa" / "tools").rglob("*.py"))
        + sorted((root / "packages" / "spectra-server" / "src").rglob("*.py"))
        + sorted((root / "tools").rglob("*.py"))
    )
    scanned = {path.resolve().relative_to(root.resolve()).as_posix() for path in paths if path.resolve() != _SELF}
    violations = [
        violation for path in paths if path.resolve() != _SELF for violation in scan_python_path(path, root=root)
    ]
    for relative in sorted(set(_LIFECYCLE_CALLSITE_ALLOWLIST) - scanned):
        violations.append(f"{relative}: fitted-node lifecycle inventory file is missing")
    for relative in sorted(set(_BRIDGE_CONVERSION_CALLSITE_ALLOWLIST) - scanned):
        violations.append(f"{relative}: PLS-DA bridge conversion inventory file is missing")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate the current repository")
    parser.parse_args()
    violations = scan_repository()
    if violations:
        print("\n".join(violations))
        return 1
    print("PLS-DA execution path: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
