"""Node serialization contract fixtures.

Shared fixture layer consumed by both backend pytest contract tests and the
frontend vitest contract suite.  Purpose:

1. **Pin the serialized shape** of every node type we care about so that
   subtle changes (e.g. a new top-level key, a nested dict reshuffle,
   renamed axis fields) are caught immediately in backend CI.
2. **Provide a single source of truth** for frontend store tests.  The
   vitest tests used to ship with hand-written mock shapes that silently
   drifted from reality; now they import the same JSON fixtures backend
   regenerates, so "tests pass" implies "shape matches real backend".

Regenerate all fixtures with::

    python -m tests.fixtures.node_serialization.generate

The generator is idempotent and deterministic (volatile fields like UUIDs
and timestamps are replaced with stable placeholders before writing).
"""
