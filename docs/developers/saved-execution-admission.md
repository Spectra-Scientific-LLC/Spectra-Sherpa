# Saved execution admission

`execute_saved_workflow(..., admission=...)` is an explicit, request-local Python
seam for a trusted application caller. It adds no HTTP parameter, registry tool,
MCP operation or remote dispatch capability. Ordinary Workbench and Batch paths
retain their existing behavior when no admission object is supplied.

The caller provides a fresh dedicated session and durable idempotency key. The
executor starts write serialization once, invokes `lock_authority` before taking
the workflow/review lock, and constructs the saved graph, selection and review
snapshot. The caller's authority locks must precede workflow locks; approval and
budget records follow them. Hooks must not commit or roll back the transaction.

Only exact experiment-file and explicitly selected collection sources can enter
this bounded path. The request captures source bytes into private temporary
storage, preserving basename, original relative identity, prepared metadata,
collection definition and dataset-view receipt. The closed resolver refuses
missing or conflicting bindings and never falls back to live storage. Registered
references need a complete referenced-member snapshot and are currently refused.
Limits are eight source nodes,128 unique files and64MiB raw bytes. These do not
replace the canonical parser's decoded-memory limits.

`SavedExecutionAdmission.admit` receives the frozen resolver and snapshots. It
**must canonically materialize and verify the source science before consuming
any approval**. A raw file hash alone is not target/selection/scientific
admission. This generic seam deliberately does not implement an application's
approval or entitlement policy. After successful admission, the executor flushes
its canonical `ExecutionRun`, invokes `bind_run`, and commits both the caller's
records and the run together. A precommit exception rolls back both.

Execution uses the same frozen resolver. `verify_current` runs before successful
or partial output retention; failures become scientific-access withdrawal and
withhold output. Source-copy cancellation drains the writer under a shield before
removing temporary storage. This path accepts only the canonical owned worker
pool or in-process execution, avoiding a legacy pool whose work could outlive
cancellation. Captured storage remains scoped to the execution call.

The application caller still owns durable request reconciliation, postcommit
crash/cancellation settlement and resource accounting. A committed run is not a
claim that a response reached its client. Do not release application capacity
while its computation remains alive.

Tests cover real canonical source loading after live bytes/metadata change,
exact collection/view capture, scope/budget refusal and cancellation draining.
Admission/run commit versus rollback, fresh-session refusal and output withdrawal
run on SQLite and optionally PostgreSQL via
`SPECTRA_ADMISSION_TEST_DATABASE_URL`. PostgreSQL tests use isolated temporary
schemas. These tests establish the generic seam, not any commercial approval,
budget, client or complete application journey.
