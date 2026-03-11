"""
Code generation and lifecycle management for custom algorithm nodes.

Each CustomAlgo record maps to:
1. A plugin ``.py`` file on disk (auto-generated from user code)
2. A registered ``node_type`` in the DAG node registry

This module handles:
- Slug validation
- Code syntax checking
- Code safety validation (AST-based, see ``validate_code_safety``)
- Plugin file generation (deterministic template)
- Atomic file writes (write to ``.tmp``, then ``os.replace``)
- Registry reload (unregister old → import new)
- Three-phase commit with compensation for CRUD operations

Security model — custom algo code execution
-------------------------------------------
Custom algorithm code is **user-supplied Python** that runs inside the
Sherpa server process with the same privileges as the server itself.
We apply a best-effort AST safety check (``validate_code_safety``) that
blocks the most common escape vectors:

* ``import`` / ``from … import`` — all imports are blocked; the helpers
  ``np``, ``coerce_to_sherpa``, ``to_numpy_2d``, ``build_dataset_like``,
  and ``add_processing_step`` are pre-imported in the generated wrapper.
* Dangerous built-in calls: ``exec``, ``eval``, ``__import__``,
  ``compile``, ``open``, ``breakpoint``, ``input``, ``memoryview``.
* Access to dunder attributes that expose the class hierarchy or builtins
  (``__builtins__``, ``__globals__``, ``__subclasses__``, etc.).
* ``global`` / ``nonlocal`` scope declarations.

**This is a defence-in-depth measure, not a full sandbox.**  A determined
attacker with write access to the database can craft code that bypasses
AST-level checks (e.g. through string-based attribute lookups).  Treat
custom algo execution as equivalent to granting shell access to the user
who created the algo.

Deployment recommendations
~~~~~~~~~~~~~~~~~~~~~~~~~~
* In multi-user (enterprise/hybrid) deployments, restrict who can create
  or edit custom algos at the application-level RBAC layer.
* Consider running the DAG worker pool in a subprocess or container with
  reduced OS-level privileges (seccomp, namespaces) for stronger isolation.
* Audit the plugin directory (``~/.spectra_sherpa/plugins/custom_algos/``)
  regularly; each ``.py`` file there represents code that will be imported.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from spectra_sherpa._paths import get_default_data_dir

if TYPE_CHECKING:
    from spectra_sherpa.app.models.custom_algo import CustomAlgo

logger = logging.getLogger(__name__)

_SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def validate_slug(slug: str) -> str:
    """Validate and normalize a slug.

    Must be a valid Python identifier: lowercase letter start,
    then lowercase letters/digits/underscores, max 64 chars.

    Returns the validated slug.
    Raises ValueError if invalid.
    """
    slug = slug.strip().lower()
    if not _SLUG_PATTERN.match(slug):
        raise ValueError(f"Invalid slug {slug!r}: must match [a-z][a-z0-9_]{{0,63}}")
    return slug


def validate_code_syntax(code: str) -> None:
    """Check that user code is valid Python syntax.

    Raises SyntaxError with line info on failure.
    """
    compile(code, "<custom_algo>", "exec")


# Names that must never appear as bare calls in user code.
_BLOCKED_CALLS: frozenset[str] = frozenset(
    {
        "exec",
        "eval",
        "__import__",
        "compile",
        "open",
        "breakpoint",
        "input",
        "memoryview",
    }
)

# Dunder attribute names that could reach the class hierarchy / builtins.
_BLOCKED_ATTRS: frozenset[str] = frozenset(
    {
        "__class__",
        "__bases__",
        "__subclasses__",
        "__globals__",
        "__builtins__",
        "__code__",
        "__closure__",
        "__dict__",
        "__import__",
    }
)


def validate_code_safety(code: str) -> None:
    """Walk the AST and reject constructs that could escape the sandbox.

    Blocks:
    - ``import`` / ``from … import`` statements
    - Calls to dangerous built-ins (exec, eval, open, …)
    - Access to dunder attributes that expose the class hierarchy or builtins
    - ``global`` / ``nonlocal`` declarations (scope escape)

    Raises ``ValueError`` with a descriptive message on the first violation.
    Call this *after* ``validate_code_syntax`` so that the tree is well-formed.
    """
    try:
        tree = ast.parse(code, "<custom_algo>", "exec")
    except SyntaxError:
        # Syntax errors are reported by validate_code_syntax; skip here.
        return

    for node in ast.walk(tree):
        # Disallow all import statements
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError(
                "import statements are not allowed in custom algo code. "
                "NumPy (np) and SherpaDataset helpers are pre-imported for you."
            )

        # Disallow global / nonlocal (scope-escape)
        if isinstance(node, ast.Global):
            raise ValueError("'global' declarations are not allowed in custom algo code.")
        if isinstance(node, ast.Nonlocal):
            raise ValueError("'nonlocal' declarations are not allowed in custom algo code.")

        # Disallow calls to dangerous built-ins
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in _BLOCKED_CALLS:
                raise ValueError(
                    f"'{name}' is not allowed in custom algo code."
                )

        # Disallow access to dangerous dunder attributes
        if isinstance(node, ast.Attribute) and node.attr in _BLOCKED_ATTRS:
            raise ValueError(
                f"Access to '{node.attr}' is not allowed in custom algo code."
            )


def get_plugin_dir() -> Path:
    """Return the custom algos plugin directory, creating it if needed."""
    d = get_default_data_dir() / "plugins" / "custom_algos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_plugin_path(algo: CustomAlgo) -> Path:
    """Return the on-disk path for a custom algo's plugin file."""
    return get_plugin_dir() / f"ualgo_{algo.project_id}_{algo.slug}.py"


def make_node_type(project_id: int, slug: str) -> str:
    """Build the canonical node_type string."""
    return f"ualgo.{project_id}.{slug}"


def generate_plugin_source(algo: CustomAlgo) -> str:
    """Generate a complete ``@register_node`` plugin module as a string."""
    if algo.mode == "loader":
        return algo.code.rstrip() + "\n"

    # Indent user code by 8 spaces (inside the execute method body)
    user_lines = algo.code.rstrip().split("\n")
    indented_code = "\n".join("        " + line for line in user_lines)

    # Class name: CamelCase from slug
    class_name = "CustomAlgo_" + algo.slug

    # Escape strings for template
    name_escaped = algo.name.replace("\\", "\\\\").replace('"', '\\"')
    desc_escaped = (algo.description or "").replace("\\", "\\\\").replace('"', '\\"')

    if algo.mode == "advanced":
        execute_body = _generate_advanced_execute(indented_code, algo)
    else:
        execute_body = _generate_simple_execute(indented_code, algo)

    source = f'''\
"""Auto-generated custom algo: {name_escaped}. Edit via Sherpa UI."""

import numpy as np

from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodePolicy,
    NodeResult,
    PortMetadata,
    register_node,
)
from spectra_sherpa.app.services.dag.io_contracts import (
    build_dataset_like,
    coerce_to_sherpa,
    to_numpy_2d,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step


@register_node
class {class_name}(Node):
    metadata = NodeMetadata(
        node_type="{algo.node_type}",
        category="custom_algo",
        label="{name_escaped}",
        description="{desc_escaped}",
        parameters=[],
        input_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Input Data",
            ),
        ],
        output_ports=[
            PortMetadata(
                name="default",
                type_ref="spectrasherpa://types/SpectralDataset/1.0",
                required=True,
                label="Output Data",
            ),
        ],
        diagnostics=["output_shape", "output_min", "output_max", "output_mean", "output_std"],
        policy=NodePolicy(offload_to_pool=False),
    )

{execute_body}

    def supports_python_export(self):
        return True

    def generate_python(self, inputs, indent="    ", use_scp=True):
        inp = next(iter(inputs.values())) if inputs else "input_data"
        lines = [
            f"{{indent}}# --- Custom Algo: {name_escaped} ({{self.node_id}}) ---",
            f"{{indent}}data = np.array({{inp}}.data, dtype=np.float64)",
            f"{{indent}}x = getattr({{inp}}, 'x', np.arange(data.shape[-1]))",
        ]
        # Inline user code
{_generate_python_export_lines(user_lines)}
        lines.append(f"{{indent}}results['{{self.node_id}}'] = result")
        return lines
'''
    return source


def validate_loader_plugin_source(code: str, *, project_id: int, slug: str) -> dict[str, str]:
    """Validate a raw loader module stored as a project-scoped custom algo."""
    expected_node_type = make_node_type(project_id, slug)

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SyntaxError(exc.msg, ("<custom_loader>", exc.lineno, exc.offset, exc.text)) from exc

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        has_register = any(
            (isinstance(d, ast.Name) and d.id == "register_node")
            or (isinstance(d, ast.Attribute) and d.attr == "register_node")
            for d in node.decorator_list
        )
        if not has_register:
            continue

        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "metadata" for target in item.targets):
                continue

            if not isinstance(item.value, ast.Call):
                raise ValueError("metadata must be assigned from a NodeMetadata(...) call")

            metadata: dict[str, str] = {}
            for kw in item.value.keywords:
                if kw.arg in {"node_type", "category", "label", "description"} and isinstance(kw.value, ast.Constant):
                    value = kw.value.value
                    if isinstance(value, str):
                        metadata[kw.arg] = value

            node_type = metadata.get("node_type")
            if node_type != expected_node_type:
                raise ValueError(
                    f"Loader node_type must be '{expected_node_type}' for this project/slug (got {node_type!r})"
                )

            if metadata.get("category") != "custom_algo":
                raise ValueError("Loader plugins must use category='custom_algo' so they stay project-scoped")

            return metadata

    raise ValueError("No @register_node class with a metadata NodeMetadata(...) assignment was found")


def _generate_simple_execute(indented_code: str, algo: CustomAlgo) -> str:
    """Generate execute() body for simple (numpy) mode."""
    return f"""\
    async def execute(self, input_data, **kwargs):
        input_ds = coerce_to_sherpa(input_data)
        data = to_numpy_2d(input_ds)
        x = input_ds.feature_axis.values if input_ds.feature_axis else np.arange(data.shape[-1])

        # === USER CODE ===
{indented_code}
        # === END USER CODE ===

        result_ds = build_dataset_like(np.atleast_2d(result), input_ds)
        add_processing_step(result_ds, "{algo.node_type}", {{}}, node_id=self.node_id)
        out = np.asarray(result_ds.data, dtype=np.float64)
        return NodeResult(
            outputs={{"default": result_ds}},
            diagnostics={{
                "output_shape": list(out.shape),
                "output_min": float(np.nanmin(out)),
                "output_max": float(np.nanmax(out)),
                "output_mean": float(np.nanmean(out)),
                "output_std": float(np.nanstd(out)),
            }},
        )"""


def _generate_advanced_execute(indented_code: str, algo: CustomAlgo) -> str:
    """Generate execute() body for advanced (SherpaDataset) mode."""
    return f"""\
    async def execute(self, input_data, **kwargs):
        input_ds = coerce_to_sherpa(input_data)

        # === USER CODE (receives 'input_ds' as SherpaDataset) ===
{indented_code}
        # === END USER CODE ===

        result_ds = coerce_to_sherpa(result)
        add_processing_step(result_ds, "{algo.node_type}", {{}}, node_id=self.node_id)
        out = np.asarray(result_ds.data, dtype=np.float64)
        return NodeResult(
            outputs={{"default": result_ds}},
            diagnostics={{
                "output_shape": list(out.shape),
                "output_min": float(np.nanmin(out)),
                "output_max": float(np.nanmax(out)),
                "output_mean": float(np.nanmean(out)),
                "output_std": float(np.nanstd(out)),
            }},
        )"""


def _generate_python_export_lines(user_lines: list[str]) -> str:
    """Generate the inline user code lines for generate_python().

    User code may contain braces (e.g. ``result = {"a": 1}``) which must
    be doubled to survive the f-string interpolation in the generated
    ``generate_python()`` method.
    """
    parts = []
    for line in user_lines:
        escaped = line.replace("\\", "\\\\").replace('"', '\\"')
        # Double braces so they survive the f-string in the generated code
        escaped = escaped.replace("{", "{{").replace("}", "}}")
        parts.append(f'        lines.append(f"{{indent}}{escaped}")')
    return "\n".join(parts)


def write_plugin_file(algo: CustomAlgo) -> Path:
    """Atomic write: write to ``.tmp``, then ``os.replace()``.

    Safety check runs before any file I/O — loader plugins use their own
    ``validate_loader_plugin_source`` path, so only validate non-loader code here.

    Returns the final plugin file path.
    """
    if algo.mode != "loader":
        validate_code_safety(algo.code)
    source = generate_plugin_source(algo)
    final_path = get_plugin_path(algo)
    tmp_path = final_path.with_suffix(".py.tmp")
    try:
        tmp_path.write_text(source, encoding="utf-8")
        os.replace(tmp_path, final_path)
        logger.info("Wrote plugin file: %s", final_path)
        return final_path
    except Exception:
        # Clean up temp file on failure
        tmp_path.unlink(missing_ok=True)
        raise


def remove_plugin_file(algo: CustomAlgo) -> None:
    """Remove plugin file if it exists. No error if missing."""
    path = get_plugin_path(algo)
    path.unlink(missing_ok=True)
    logger.info("Removed plugin file: %s", path)


def reload_into_registry(algo: CustomAlgo) -> None:
    """Unregister old node_type (if present), write file, import via reload_plugin_by_path()."""
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.services.plugin_loader import reload_plugin_by_path

    # Unregister old version (best-effort, may not exist yet)
    try:
        node_registry.unregister(algo.node_type)
    except ValueError:
        pass  # Built-in type — should never happen for ualgo.*

    # Write the plugin file
    plugin_path = write_plugin_file(algo)

    # Import into the current process
    if not reload_plugin_by_path(plugin_path):
        raise RuntimeError(f"Failed to load plugin file: {plugin_path}")


def unregister_and_remove(algo: CustomAlgo) -> None:
    """Unregister from node registry and remove plugin file."""
    from spectra_sherpa.app.services.dag.node_base import node_registry

    try:
        node_registry.unregister(algo.node_type)
    except ValueError:
        pass

    remove_plugin_file(algo)
