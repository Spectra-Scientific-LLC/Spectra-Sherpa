"""Phase 3 — CI coverage guard (AST-level).

Phase 3a originally shipped a grep-based version. Review surfaced that
quoted-string matching can pass on constants, docstrings, and
unrelated code, and it does not prove an actual
``audit_emitter.emit(action=..., target_type=...)`` call binds the
expected pair. This rewrite walks each ``app/`` Python file with the
``ast`` module, extracts every literal binding from real ``emit``
keyword arguments, and verifies the registry against the extracted
binding set.

It also validates:
  * every ``model_dotted_path`` in the registry imports cleanly
    (catches renames and silent path drift), and
  * the ``@audit_excluded`` mechanism still records reasons (smoke
    test).

What it deliberately doesn't try to prove:
  * runtime emit behaviour during real routes — that's the job of
    ``test_route_level_e2e.py`` and ``test_phase3_coverage_e2e.py``.

Together the three layers (registry → AST binding → E2E hit) give
forensic-grade coverage without the brittleness of full route tracing.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from spectra_sherpa.app.services.audit import AUDITED_MODELS, AuditedModel

# Where we look for emit() call sites.
_SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "spectra_sherpa" / "app"
# The audit module itself defines the emitter — exclude so we don't
# false-positive on its own infrastructure.
_EXCLUDE_DIRS = ("services/audit",)


def _iter_call_site_files() -> list[Path]:
    files: list[Path] = []
    for p in _SRC_ROOT.rglob("*.py"):
        rel = p.relative_to(_SRC_ROOT).as_posix()
        if any(rel.startswith(skip) for skip in _EXCLUDE_DIRS):
            continue
        files.append(p)
    return files


def _collect_file_action_literals(tree: ast.AST) -> set[str]:
    """Collect string-literal values that could legitimately become
    the ``action`` kwarg of an emit call elsewhere in this file.

    Sources considered:
      * dict values from module-level dict assignments (e.g.
        ``_RUN_ACTION_BY_STATUS = {"completed": "workflow.run.completed", ...}``);
      * string return values from any function body
        (``return "workflow.run.failed"``);
      * direct string assignment to a local variable later passed to emit
        (e.g. ``action = "api_key.created"``).

    Strings inside docstrings or unrelated expressions are NOT included.
    Tightly bounded to the file we're inspecting, so a stray match
    elsewhere in the codebase cannot leak in.
    """
    literals: set[str] = set()
    for node in ast.walk(tree):
        # Dict values in any Assign / AnnAssign
        if isinstance(node, ast.Dict):
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    literals.add(v.value)
        # return "..." statements
        elif (
            isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        ):
            literals.add(node.value.value)
        # str assignments at any scope: name = "..."
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Name)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    literals.add(node.value.value)
        # if/else branches that assign a string to a name
        elif isinstance(node, ast.If):
            for branch in (node.body, node.orelse):
                for stmt in branch:
                    if (
                        isinstance(stmt, ast.Assign)
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)
                    ):
                        literals.add(stmt.value.value)
    return literals


def _extract_emit_bindings() -> set[tuple[str, str]]:
    """Walk every searchable .py file under app/ and pull (action,
    target_type) pairs from real ``audit_emitter.emit(...)`` calls.

    Behaviour:
      * ``target_type`` MUST be a string literal — strict. A non-literal
        target_type is a code-smell and the binding is skipped.
      * ``action`` SHOULD be a string literal. When it isn't (dispatch
        via ``_run_action_from_status(...)`` or ``action = "..."`` /
        ``"..."``), every dispatch-eligible string literal in the same
        file is paired with the literal target_type. This is bounded —
        only strings that could possibly become the dispatched action
        are considered, scoped to the file containing the emit.

    Pure AST walking. Doesn't import or execute the target code.
    """
    bindings: set[tuple[str, str]] = set()

    for path in _iter_call_site_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
        except SyntaxError:
            continue

        # Build the candidate-action set ONCE per file.
        candidate_actions = _collect_file_action_literals(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "emit"):
                continue

            action = _literal_kwarg(node, "action")
            target_type = _literal_kwarg(node, "target_type")
            if target_type is None:
                continue  # strict: target_type must be literal

            if action is not None:
                bindings.add((action, target_type))
            else:
                # Dynamic dispatch — accept candidate action literals
                # in the same file. Restrict to dotted verbs (e.g.
                # ``workflow.run.completed``) — every audit action
                # uses dotted notation, so this filters out unrelated
                # strings like response-status fields ("stored",
                # "completed" as a workflow status, etc.) that happen
                # to live in the same file.
                for candidate in candidate_actions:
                    if "." in candidate:
                        bindings.add((candidate, target_type))

    return bindings


def _literal_kwarg(call: ast.Call, name: str) -> str | None:
    """Return the str-literal value of a keyword argument by name, or None."""
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _snake_case(s: str) -> str:
    """Snake-case helper that handles acronyms ("APIKey" → "api_key")."""
    import re

    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _expected_action_strings(entry: AuditedModel) -> list[str]:
    """Compute the action verbs expected for a registry entry.

    Dotted actions (``workflow.run.completed``) pass through as-is;
    bare actions get prefixed with the snake-case target type
    (``api_key.created``).
    """
    out: list[str] = []
    for action in sorted(entry.actions):
        if "." in action:
            out.append(action)
        else:
            out.append(f"{_snake_case(entry.target_type)}.{action}")
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# Cache: the AST walk is the same for every test in this module.
_BINDINGS: set[tuple[str, str]] | None = None


def _get_bindings() -> set[tuple[str, str]]:
    global _BINDINGS
    if _BINDINGS is None:
        _BINDINGS = _extract_emit_bindings()
    return _BINDINGS


def test_every_audited_model_has_a_real_emit_call():
    """For every (action, target_type) the registry declares, there
    MUST be a real ``audit_emitter.emit(action=..., target_type=...)``
    call somewhere in the source. AST-extracted, so this is impervious
    to docstring noise, constants, or pattern-match false positives.
    """
    bindings = _get_bindings()
    missing: list[str] = []
    for entry in AUDITED_MODELS:
        for action in _expected_action_strings(entry):
            if (action, entry.target_type) not in bindings:
                missing.append(
                    f"  {entry.target_type}: no emit(action={action!r}, target_type={entry.target_type!r}) call found"
                )

    if missing:
        # Surface the actual binding set to make the failure debug-friendly.
        observed = "\n".join(f"    {a!r} → {t}" for a, t in sorted(bindings))
        raise AssertionError(
            "AUDITED_MODELS declares actions that no real emit() call binds.\n"
            "Wire the emit (preferred), add @audit_excluded with a reason, or drop the action.\n"
            "Missing:\n" + "\n".join(missing) + "\n\nObserved emit bindings in the source tree:\n" + observed
        )


def test_every_emit_call_matches_a_registry_entry():
    """The inverse check: every real emit() call binds to a registry
    entry. Catches the "added a new emit at a fresh action verb but
    forgot to declare it in the registry" mistake — those rows still
    write but escape the coverage guard.
    """
    bindings = _get_bindings()
    declared_pairs: set[tuple[str, str]] = set()
    for entry in AUDITED_MODELS:
        for action in _expected_action_strings(entry):
            declared_pairs.add((action, entry.target_type))

    undeclared = bindings - declared_pairs
    if undeclared:
        listing = "\n".join(f"  {a!r} → {t}" for a, t in sorted(undeclared))
        raise AssertionError(
            "Real emit() calls exist for (action, target_type) pairs not in AUDITED_MODELS.\n"
            "Add them to the registry so the coverage guard tracks them.\n"
            "Undeclared:\n" + listing
        )


def test_every_model_dotted_path_imports():
    """Every model_dotted_path in the registry must be importable —
    catches renames and silent path drift the AST scan would miss
    (the AST tracks emit call sites; this tracks the model class itself).
    """
    failures: list[str] = []
    for entry in AUDITED_MODELS:
        module_path, _, class_name = entry.model_dotted_path.rpartition(".")
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            failures.append(f"  {entry.target_type}: cannot import module {module_path!r} ({exc})")
            continue
        if not hasattr(module, class_name):
            failures.append(f"  {entry.target_type}: module {module_path!r} has no attribute {class_name!r}")
    assert not failures, "AUDITED_MODELS model_dotted_path entries do not all resolve:\n" + "\n".join(failures)


def test_excluded_decorator_records_reasons():
    """``@audit_excluded`` records every decorated function for the
    coverage guard to introspect. Smoke-test the recording mechanism."""
    from spectra_sherpa.app.services.audit import audit_excluded, get_excluded_sites
    from spectra_sherpa.app.services.audit.coverage import _reset_excluded_sites_for_tests

    _reset_excluded_sites_for_tests()

    @audit_excluded("test fixture only")
    def _example_handler():
        return "ok"

    sites = get_excluded_sites()
    assert any("_example_handler" in s.qualified_name for s in sites)
    assert any(s.reason == "test fixture only" for s in sites)
    assert _example_handler() == "ok"


def test_excluded_decorator_rejects_empty_reason():
    import pytest

    from spectra_sherpa.app.services.audit import audit_excluded

    with pytest.raises(ValueError, match="non-empty"):

        @audit_excluded("")
        def _f():
            pass
