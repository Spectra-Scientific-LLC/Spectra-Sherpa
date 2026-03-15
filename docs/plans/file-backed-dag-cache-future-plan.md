# File-Backed DAG Cache Future Plan

## Status

Deferred future work.

The current product priority remains:

1. sample management and representative partitioning
2. variable selection and selection provenance
3. artifact applicability and leakage-safe workflow semantics

The recent three-phase selection push materially advances those priorities. A file-backed DAG cache should follow them, not displace them.

## Why This Exists

The current execution layer still has three real pain points:

- unchanged nodes can be recomputed unnecessarily
- large intermediate arrays can create avoidable IPC serialization and memory pressure
- partially completed runs can leave behind orphaned transient outputs

Those problems are related, but they should not be solved with a rushed storage rewrite. Execution caching is infrastructure. Selection, leakage safety, and artifact correctness are scientific product requirements. The scientific layer comes first.

## Product Position

SpectraSherpa should not adopt a file-backed DAG cache as a generic optimization project. It should adopt it as a scientific execution contract:

- intermediate workflow states must be reproducible
- cache identity must respect data semantics, not just array shape
- persisted intermediates must not weaken provenance or deployment safety
- transient cache state and durable model artifacts must remain distinct

## What The Future Design Should Achieve

### 1. Deterministic intermediate reuse

Unchanged nodes should be skipped safely when:

- node parameters are unchanged
- upstream dataset identity is unchanged
- relevant axis and target semantics are unchanged
- the node implementation and schema contract are unchanged

### 2. Low-overhead worker handoff

Heavy arrays should not be pushed repeatedly through process-pool IPC when a stable handle can be passed instead.

### 3. Crash-safe transient persistence

Intermediate results should be written atomically into a run-scoped cache area with explicit cleanup rules.

### 4. Clean separation of lifecycles

The DAG cache is ephemeral. Model artifacts are durable. A future design must keep those lifecycles separate and only promote durable artifacts after successful workflow completion.

## What We Should Not Do

- Do not make raw `pickle` blobs the default long-term storage contract for scientific intermediates.
- Do not key the cache only on node parameters and array shapes.
- Do not collapse transient cache files and durable saved models into the same abstraction.
- Do not let cache introduction outrun applicability checks, provenance, or axis-aware validation.
- Do not treat this as a "single low-complexity fix." It is an execution-contract change.

## Recommended Rollout

### Phase A: Handle boundary first

Introduce a result-handle abstraction for large worker inputs and outputs.

Goals:

- reduce IPC payload size
- avoid changing full DAG cache semantics immediately
- prove out run-scoped storage, atomic writes, and cleanup behavior

### Phase B: Manifest-based intermediate storage

Persist heavy datasets as manifest plus array files, not opaque monolithic blobs.

Goals:

- preserve inspectability
- support future memory mapping
- keep axis, target, and provenance identity explicit

### Phase C: Deterministic node reuse

Add true file-backed memoization for selected node families once cache identity is trustworthy.

Goals:

- skip recomputation for safe cases
- version cache entries by node implementation and schema
- make invalidation explicit rather than heuristic

### Phase D: Artifact promotion flow

Stage model outputs in transient execution storage and promote them to durable model storage only after the workflow completes successfully.

Goals:

- eliminate orphaned durable artifacts from failed runs
- keep deployment artifacts distinct from cached intermediates

## Readiness Gates

This work should start only when the following are stable:

- sample selection contracts
- feature-selection contracts
- model artifact applicability metadata
- fit-time versus apply-time semantics for selection and preprocessing

If those contracts are still moving, the cache key cannot be scientifically trustworthy.

## Success Criteria

A future file-backed DAG cache is successful only if it improves all three of these at once:

- UX: faster reruns, fewer memory failures, cleaner recovery from failed jobs
- DX: explicit handles, predictable invalidation, debuggable manifests
- science: no silent reuse across incompatible data, axes, or workflow semantics

## Immediate Recommendation

Do not pivot the roadmap toward cache architecture now.

Finish hardening:

1. sample partition semantics and downstream target handling
2. variable-selection contracts and export behavior
3. artifact applicability checks for selected wavelengths

Then implement the cache project as a staged execution-layer modernization rather than an all-at-once rewrite.
