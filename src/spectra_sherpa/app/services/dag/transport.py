"""Fail-closed scientific object transport boundaries.

SpectroChemPy remains an optional implementation detail for exactly three
algorithms. Its runtime objects must never cross an SDK, DAG, executor, worker,
or API boundary. Detection is structural so checking the boundary never imports
the optional distribution.
"""

from __future__ import annotations

import gc
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from types import FunctionType, MethodType, ModuleType
from typing import Any

import numpy as np


def is_spectrochempy_runtime_object(value: Any) -> bool:
    """Return whether *value* is implemented by SpectroChemPy.

    Walking the MRO catches subclasses without importing the optional runtime.
    Module identity is required rather than a class-name heuristic, avoiding
    accidental rejection of an unrelated user-defined scientific container.
    """

    try:
        if isinstance(value, ModuleType):
            return str(value.__name__).startswith("spectrochempy")
        if isinstance(value, (type, FunctionType, MethodType)):
            return str(value.__module__).startswith("spectrochempy")
        return any(str(base.__module__).startswith("spectrochempy") for base in type(value).__mro__)
    except (AttributeError, TypeError):
        return False


def reject_spectrochempy_transport(value: Any, *, boundary: str) -> None:
    """Reject an SCP runtime object anywhere in one transport value tree."""

    seen: set[int] = set()

    def visit(current: Any, path: str) -> None:
        if is_spectrochempy_runtime_object(current):
            raise TypeError(
                f"SpectroChemPy runtime object {type(current).__name__} reached {boundary} at {path}; "
                "DAG transport must use SherpaDataset or canonical data-only state"
            )

        # Runtime code/type/module objects are identities, not scientific data
        # containers. SCP-owned instances of these kinds were rejected above;
        # do not traverse their interpreter-global referent graphs.
        if isinstance(current, (type, FunctionType, MethodType, ModuleType)):
            return
        if isinstance(current, (str, bytes, bytearray, memoryview, int, float, complex, bool)) or current is None:
            return
        identity = id(current)
        if identity in seen:
            return
        seen.add(identity)

        if isinstance(current, Mapping):
            for key, item in current.items():
                visit(key, f"{path}.<key>")
                visit(item, f"{path}[{key!r}]")
        if isinstance(current, (list, tuple, set, frozenset)):
            for index, item in enumerate(current):
                visit(item, f"{path}[{index}]")
        if isinstance(current, np.ndarray):
            if current.dtype.hasobject:
                for index, item in enumerate(current.flat):
                    visit(item, f"{path}.flat[{index}]")
        if isinstance(current, np.void):
            if current.dtype.hasobject:
                for name in current.dtype.names or ():
                    visit(current[name], f"{path}[{name!r}]")
        if is_dataclass(current) and not isinstance(current, type):
            for field in fields(current):
                visit(getattr(current, field.name), f"{path}.{field.name}")
        if hasattr(current, "__dict__") or any("__slots__" in base.__dict__ for base in type(current).__mro__):
            if hasattr(current, "__dict__"):
                for name, item in vars(current).items():
                    visit(item, f"{path}.{name}")
            visited_slots: set[str] = set()
            for base in type(current).__mro__:
                declared = base.__dict__.get("__slots__", ())
                if isinstance(declared, str):
                    declared = (declared,)
                for declared_name in declared:
                    if declared_name in {"__dict__", "__weakref__"}:
                        continue
                    slot_name = declared_name
                    if declared_name.startswith("__") and not declared_name.endswith("__"):
                        slot_name = f"_{base.__name__.lstrip('_')}{declared_name}"
                    if slot_name in visited_slots:
                        continue
                    visited_slots.add(slot_name)
                    try:
                        item = getattr(current, slot_name)
                    except (AttributeError, TypeError):
                        continue
                    visit(item, f"{path}.{slot_name}")

        # Semantic contents, instance attributes/slots, and C-level referents
        # are cumulative authorities. Container subclasses can own state in
        # more than one of them; returning after the first would allow an SCP
        # object to hide in the others. Executable/type/module objects were
        # deliberately excluded above, and ``seen`` keeps the combined walk
        # cycle-safe.
        if gc.is_tracked(current):
            for index, item in enumerate(gc.get_referents(current)):
                visit(item, f"{path}.<referent[{index}]>")

    visit(value, "$")


def require_raw_matrix_container(value: Any, *, input_name: str) -> Any:
    """Admit only explicit built-in/NumPy matrix containers.

    Foreign duck arrays can implement ``__array__`` while carrying axes,
    targets, masks, or units. Silently coercing one would discard scientific
    identity, so callers must adapt such objects explicitly outside the DAG.
    """

    import numpy as np

    reject_spectrochempy_transport(value, boundary=f"{input_name} raw-matrix admission")
    if not isinstance(value, (np.ndarray, list, tuple)):
        raise TypeError(
            f"{input_name} must be a SherpaDataset or an explicit numpy/list/tuple matrix; "
            f"received {type(value).__name__}"
        )
    return value
