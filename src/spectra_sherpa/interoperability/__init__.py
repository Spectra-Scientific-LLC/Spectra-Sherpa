"""Explicit opt-in interoperability boundaries.

This package intentionally exports nothing.  Import a named adapter directly
so optional third-party runtimes remain lazy and structurally inspectable.
"""

__all__: tuple[str, ...] = ()
