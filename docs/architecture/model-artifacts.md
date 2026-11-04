# Model Artifacts

!!! abstract "Summary"
    How trained models are saved, versioned, reviewed, and reapplied — the bridge from a good run to a reusable calibration.

Model artifacts persist trained models. They are the bridge between "this workflow run looked good" and "this calibration or classifier can be reviewed, versioned, reapplied, or handed to another system."

## What a Model Artifact Is

For a PLS calibration, the artifact should answer practical questions such as:

- What dataset and target was used?
- What preprocessing and parameters were applied?
- What spectral axis and feature count does the model expect?
- Which fitted arrays are needed to predict new spectra?
- What validation metrics justified saving it?
- Which run, user, project, and timestamp produced it?

## Stored Form

SpectraSherpa stores model artifacts as **readable metadata plus numeric state**.

The readable part is a manifest. The schematic below illustrates the kinds of
context it records; it is not the actual serializer schema or a valid artifact
to construct by hand:

```json
{
  "artifact_type": "pls_regression",
  "created_from_run": "run_2026_06_05_001",
  "target": {"name": "moisture", "units": "%"},
  "spectral_axis": {"units": "cm^-1", "n_features": 1557},
  "preprocessing": ["snv", "savgol_derivative"],
  "metrics": {"rmsep": 0.18, "r2": 0.94, "bias": -0.02},
  "arrays": ["x_mean.npy", "x_scale.npy", "coef.npy", "loadings.npy"]
}
```

The numeric state files hold values that should not be hand-edited: regression coefficients, loadings, scaling vectors, class centers, or other fitted arrays. Keeping this fitted state alongside a readable manifest makes the artifact both reviewable by humans and precise enough for later application.

```mermaid
flowchart LR
    R[Workflow run] --> M[Manifest JSON]
    R --> A[Array files]
    M --> C[Compatibility review]
    A --> P[Prediction/application]
    C --> P
```

## Why They Matter

A calibration or classifier is useful only if it can be reapplied to compatible spectra. The artifact should carry enough contract information to explain what the model expects, why it was saved, and what has to match at apply time.

## Project transfer source binding

Fresh executor publications record `producer_node_type` from the executing node.
For producing-run-only artifacts, project export checks that identity and the
artifact UID against the exact retained producing workflow. This provenance field does not select application
dispatch: `native_node_type` remains reserved for native fitted-state artifacts.
A current canvas is never substituted for a missing producing-run definition.

The training-source resolver requires one valid source operation in the retained
preprocessing history, regardless of where target attachment appears. Ambiguous
source operations are refused. Import remaps experiment and selected-file IDs
together, preserves their ordered subset, and verifies the restored scientific
bindings before admitting the source.

A transferred run is external evidence, not a newly executed local run. Its
original run/project/workflow identifiers and graph digest remain in the imported
workflow version's `external_source_run_provenance`; import does not invent a
local execution record. Fitted arrays, compatibility checks and recorded
validation scope remain separate from local application availability.

Reference restoration prepares member directories inside the newly owned
experiment before persisting verified bytes. The reference checksum and
scientific projection must still match; a filename is not sufficient.

Application distinguishes validated source-import provenance from numerical
preprocessing. Source-import records describe how the calibration data was read;
they do not import those calibration observations into a new prediction batch.
Feature, axis and unit checks still apply to incoming data, and actual
preprocessing must have supported replay. Unknown operations remain refused.

## Publication custody

Application-owned model files have a private ownership claim before publication.
That claim is not a saved model or evidence of a successful run. It remains if
execution fails or times out, and transfers to the completed model record in the
same database transaction that registers the artifact. Startup cleanup must not
discard a claimed file merely because it is old.

Detailed View's Run Trial results are temporary (the Inspector's Run Node can
retain a run and model). After temporary execution and file writers
have stopped, the owner records terminal cleanup intent, removes the temporary
model directory, and retains a compact revocation receipt. Interrupted cleanup
is retried at startup and every minute. Retained models and overlapping live
storage references prevent deletion. A failed claim grants no cleanup authority.

New publications have an execution-attempt identity and a five-minute lease,
renewed every thirty seconds while their owning execution task is alive. Expiry
permits **revocation**, not a claim that a transaction aborted. Recovery first
commits a database fence under the same owner lock used by model registration.
A held registration COMMIT must finish before this fence can be established.
Registration requires the matching execution receipt; a fenced or missing
owned claim refuses late registration before any persistence side effects.

Filesystem writes and cleanup also share one cross-process identity lock.
Cleanup durably records a separate storage fence before removing canonical
files and attributable `.staging-<uid>-…` scratch. This protects against a
writer thread surviving loss of its database connection. Interrupted cleanup
retries; the fence is not a claim that deletion finished. Imports allocate a new
identity rather than reusing a reserved identity. Referenced paths and recovery
backups remain protected. Never delete lock files or revocation markers manually.

**Known retention limit:** each reclaimed identity leaves its lock/fence files,
including after normal temporary-trial cleanup and account erasure. These small
files currently accumulate in one directory. Bounded fence compaction is a
follow-up; a missing database tombstone alone cannot authorize removal because
a disconnected or paused writer may still hold that identity. A safe compactor
must prove all writers for a retired ownership epoch are stopped and preserve
the same protection across recovery snapshots. Until that protocol is qualified,
retain the markers and include their inode usage in storage capacity monitoring.

Hosted account-erasure plans also retain publication identities. Completion
joins any surviving file writer and fences its identity before reporting the
workspace erased; losing a database connection does not prove a writer stopped.
A failed filesystem durability barrier leaves recovery pending with its files
protected. Automatic crash reclamation is not yet qualified on Windows, whose
directory-durability primitive differs. Background recovery retains those files
and logs an operator recovery warning. Normal trial cleanup remains available:
the original execution closes further publication, joins all its file writers,
and removes only its own unreferenced files under the shared identity lock.
Its database revocation record remains, without a durable-reclamation timestamp.
Background recovery never infers this stopped-execution authority from a flag
or elapsed time. A failed explicit cleanup can be retried by that same stopped
execution; after process loss, offline reconciliation is required on Windows.

Historical claims without execution ownership remain protected: their age and
absent model rows cannot prove that deleting them is safe. Account erasure or
an explicitly reviewed offline reconciliation is required for those claims.

### Ownership migration and recovery qualification

Migration `r7s9t1u3v105` adds nullable ownership fields without assigning invented
owners to historical claims. Stop **all** old application and cleanup processes
before upgrading; mixed old/new workers are unsupported because old cleanup
does not preserve revocation receipts. Downgrade refuses while owned claims or
tombstones exist. Do not delete those rows to force a downgrade.

All writers and cleanup processes must mount the same model data root **and**
its sibling `.model-publication-locks` directory, using a filesystem with reliable
cross-process locking. Back up and restore the database, model storage, and
lock/fence directory as one consistent snapshot. A local concurrency test is
not qualification of a different network filesystem or a production restore.

`tests/test_publication_lease.py` covers admission, renewal, fencing, retry and
legacy preservation. `tests/test_publication_platforms.py` exercises the
unsupported-platform policy on every runner: preserve crash-left files, join
cancelled writers, refuse foreign attempts and retain overlapping custody.
`tests/test_publication_postgres.py` uses separate real
processes and disposable databases: held COMMIT (commit and abort), terminated
database connection with a surviving filesystem writer, and hard-killed writer
scratch. Run with `PUBLICATION_TEST_POSTGRES_URL` pointing at a disposable
PostgreSQL cluster and `REQUIRE_PUBLICATION_POSTGRES=1`; the Ubuntu PostgreSQL
CI lane requires these tests rather than treating skipped tests as evidence.

Publication rechecks the live owner under a short database lock; fitting does
not hold that lock. Cancellation waits for the actual file writer to stop before
releasing custody. File publication uses separate bounded thread capacity from
computation to avoid deadlock under concurrent runs. An uncertain claim commit
does not authorize writing files.

SDK callers that supply their own storage capability remain responsible for its
ownership and cleanup. These safeguards do not retroactively identify historical
orphan files or certify deletion of backups.

## Apply-Time Review

Before applying a model, confirm spectral axis, preprocessing, feature count, and units match the training data.

Training exclusions select the fitted cohort; they are not replayed as row
exclusions on new observations. Applying a curated PCA or PLS artifact processes
the new dataset's eligible rows, not the training dataset's row positions.

For example, a PLS model trained on absorbance spectra from 4000-650 cm^-1 should not be applied blindly to transmittance spectra, truncated axes, different resolution, or spectra preprocessed outside the saved workflow contract.


## Portable manual checkpoint selection

The closed campaign evidence reader accepts three distinct selection origins:
`spectra-canonical-campaign-evidence/6` retains the recorded automatic or direct
scientist selection, and `/7` retains `spectra-scientist-reviewed-selection/1`.
Their fields and interpretation are unchanged. Evidence `/8` carries the new
`spectra-manual-checkpoint-selection/1` origin for an explicitly chosen manual
parameter-grid study checkpoint. A reader that does not support `/8` must refuse
it; changing its version to `/6` or `/7` does not make it compatible.

The manual selection record has exactly these fields: `schema_version`,
`selection_claim`, `winner_candidate_id`, `selected_graph_digest`,
`selected_result_digest`, `manual_choice_digest`, `checkpoint_digest`, and
`settlement_digest`. Its claim is
`scientist_selected_final_development_checkpoint`. The candidate, graph and
result name a successful member of the complete, ordered development ledger;
its successful candidates must retain the same population and split identity.
The three authority digests refer to the actual immutable manual choice,
checkpoint, and original batch settlement. They are distinct identities, not
aliases for an automatic winner or a managed reviewed decision. No reason code,
managed approval receipt or direct `scientist_selection` is inferred.

At managed export, the source, tenant/project, complete development ledger,
choice, checkpoint, successful refit terminal and artifact are re-admitted
before a package can be signed. The existing terminal-captured local model
record remains unchanged: its campaign derivation binds the original settlement
and declared candidate ordinal. Publisher input identifies
`manual-checkpoint-selection:<manual_choice_digest>`. Package, signature,
download, CLI inspection and import then use the normal Campaign Review path.
Neither the portable digest nor a publisher signature grants scientific
correctness, new execution or independent-validation authority. A CV-only
conclusion remains development evidence; importing it does not access held-out
data or fit another model.

## Historical inspection catalogs

The public package includes exact, digest-pinned contract catalogs so older
retained records remain inspectable. The filename
`contract_predecessors_staging_20261029.json` identifies the profile captured
before automatic PLS selection; it contains contract data, not account data or
credentials. Its historical name and bytes are retained intentionally. It is
a read-only inspection authority, not a saved-model application alias or
permission to replay an older fit with current code.
`contract_predecessors_baseline_warning.json` does the same for the profile
captured before penalized-baseline non-convergence became a recorded warning.
