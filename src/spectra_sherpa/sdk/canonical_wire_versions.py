"""Current-only canonical wire-version authority.

These identifiers are shared by the OSS verifier and the managed runtime.
They intentionally live in the OSS package so managed code cannot define a
different meaning for evidence that the free verifier must independently read.

Historical versions are not aliases and are not translated.  Readers fail
closed unless a payload uses the one current identifier exported here.
"""

CANONICAL_RUNNER_PROTOCOL_VERSION = "spectra-canonical-runner/5"
CANONICAL_WORKER_RESULT_VERSION = "spectra-canonical-worker-result/6"
CANONICAL_WORKFLOW_CAPSULE_VERSION = "spectra-canonical-workflow-capsule/6"


__all__ = [
    "CANONICAL_RUNNER_PROTOCOL_VERSION",
    "CANONICAL_WORKER_RESULT_VERSION",
    "CANONICAL_WORKFLOW_CAPSULE_VERSION",
]
