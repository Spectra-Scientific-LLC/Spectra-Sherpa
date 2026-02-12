"""
Node metadata validation helpers.

This module validates that node metadata declarations are structurally sound
and that all ``type_ref`` values resolve in the type registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Type

from .node_base import Node, node_registry


def _ensure_registry_loaded() -> None:
    """Load the singleton type registry on-demand when needed."""
    from app.types import type_registry

    if type_registry.is_loaded:
        return

    # Resolve ``app/types`` relative to this file:
    # app/services/dag/node_meta_validator.py -> app/types
    types_dir = Path(__file__).resolve().parents[2] / "types"
    type_registry.load(types_dir)


def validate_node_meta(node_class: Type[Node]) -> tuple[bool, List[str]]:
    """Validate metadata for a single node class.

    Args:
        node_class: Node subclass to validate.

    Returns:
        ``(is_valid, errors)`` where ``errors`` contains human-readable messages.
    """
    _ensure_registry_loaded()
    from app.types import type_registry

    errors: List[str] = []
    meta = node_class.get_metadata()

    if meta.input_ports:
        for port in meta.input_ports:
            try:
                type_registry.resolve(port.type_ref)
            except Exception as exc:
                errors.append(
                    f"{meta.node_type} input '{port.name}' has invalid type_ref "
                    f"{port.type_ref!r}: {exc}"
                )

    if meta.output_ports:
        for port in meta.output_ports:
            try:
                type_registry.resolve(port.type_ref)
            except Exception as exc:
                errors.append(
                    f"{meta.node_type} output '{port.name}' has invalid type_ref "
                    f"{port.type_ref!r}: {exc}"
                )

    if not isinstance(meta.diagnostics, list):
        errors.append(
            f"{meta.node_type} diagnostics must be a list, got {type(meta.diagnostics).__name__}"
        )

    return len(errors) == 0, errors


def validate_all_registered_node_meta() -> tuple[bool, List[str]]:
    """Validate metadata for all nodes currently registered in ``node_registry``."""
    errors: List[str] = []
    for node_meta in node_registry.list_nodes():
        try:
            node_class = node_registry.get_node_class(node_meta.node_type)
        except KeyError:
            errors.append(f"Node class missing for {node_meta.node_type}")
            continue
        ok, node_errors = validate_node_meta(node_class)
        if not ok:
            errors.extend(node_errors)
    return len(errors) == 0, errors


__all__ = ["validate_node_meta", "validate_all_registered_node_meta"]
