"""Trusted application composition hooks, configured before DAG import.

No plugin implementation or reference tables ship in the public package.
"""

from collections.abc import Callable

_node_loader: Callable | None = None
_interpreter_factory: Callable | None = None
_sealed = False


def configure_workflow_extension(*, node_loader, interpreter_factory):
    global _node_loader, _interpreter_factory
    if _sealed or _node_loader is not None:
        raise RuntimeError("Workflow extension composition is already closed")
    _node_loader = node_loader
    _interpreter_factory = interpreter_factory


def load_workflow_extension(registry):
    global _sealed
    _sealed = True
    if _node_loader is not None:
        _node_loader(registry)


def build_peak_interpreter(user_id, project_id=None):
    if _interpreter_factory is None:
        return None
    return _interpreter_factory(user_id, project_id)
