"""Shared helpers for Python code generation in node export.

Provides building-block functions used by ``generate_python()`` methods
across node families.  Extracted from ``preprocessing.py`` so that spec
nodes and hand-written overrides share the same primitives.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .node_base import _format_value

# Re-export so callers can ``from .export_helpers import format_value``
format_value = _format_value


def header_line(label: str, node_id: str, indent: str) -> str:
    """Standard section comment: ``# --- {label} ({node_id}) ---``."""
    return f"{indent}# --- {label} ({node_id}) ---"


def extract_data_lines(input_expr: str, indent: str) -> list[str]:
    """Standard numpy extraction from an input expression.

    Returns::

        _data = np.array({input_expr}.data, dtype=np.float64)
    """
    return [f"{indent}_data = np.array({input_expr}.data, dtype=np.float64)"]


def wrap_result_lines(
    node_id: str,
    data_expr: str,
    input_expr: str,
    indent: str,
    use_scp: bool,
) -> list[str]:
    """Generate result-wrapping code lines for Python export.

    SCP mode:  ``scp.NDDataset(data) + coordinate copy``
    numpy mode: ``_Result(data, x=...)``
    """
    if use_scp:
        return [
            f"{indent}results['{node_id}'] = scp.NDDataset({data_expr})",
            f"{indent}if hasattr({input_expr}, 'x') and {input_expr}.x is not None:",
            f"{indent}    results['{node_id}'].x = {input_expr}.x.copy()",
        ]
    return [
        f"{indent}results['{node_id}'] = _Result(" f"{data_expr}, x=getattr({input_expr}, 'x', None))",
    ]


def format_kwargs(
    params: Dict[str, Any],
    param_map: Optional[Dict[str, str]] = None,
) -> str:
    """Format *params* as a keyword-argument string: ``k1=v1, k2=v2``.

    *param_map* optionally renames keys (node param name → kwarg name).
    """
    parts: list[str] = []
    pm = param_map or {}
    for name, value in params.items():
        kwarg_name = pm.get(name, name)
        parts.append(f"{kwarg_name}={_format_value(value)}")
    return ", ".join(parts)
