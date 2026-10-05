# Instrument QC and maintenance evidence

This is **report-only monitoring of declared control tolerances** for canonical
PLS folder-watch applications. It never holds predictions, changes slope/bias,
corrects a model, or represents statistical process control or laboratory
certification. A failed control does not establish that the instrument caused
the failure. Physical instrument/material identity and submitted measurements
remain operator declarations.

## Operator sequence

1. In **Deploy → Folder Watches → QC / maintenance**, inspect the exact application
   and current evidence. No policy means `no_declared_qc_policy`, not a pass.
2. Declare a versioned laboratory policy using the application's retained artifact
   and plan digests. Specify instrument/configuration, reference method and units,
   control material identity/lot/expiry, assigned responses, positive absolute
   residual tolerances and control frequency. Choose these limits in the laboratory;
   software does not supply industrial acceptance thresholds.
3. Append a control observation with a unique ID, actual observation time, exact
   response results and source-evidence digest. These are the control's model
   response results in the policy's units, not raw spectral intensities. No
   replicate averaging is performed. The assigned response values and reference
   measurement basis are kept separately in the policy.
4. Inspect all reasons, not just the summary. A result equals the tolerance is
   within it; a control is overdue at exactly observation time plus its maximum
   age. Material expires at exactly its expiry timestamp. Missing, expired,
   overdue, changed model/configuration and failed controls remain distinct.
5. A new passing control does not erase a prior failure. Investigate it, then append
   a recovery acknowledgement naming that failed event and a later passing control.
   Failures remain latched across policy/lot changes until explicitly acknowledged.
6. Record maintenance with the resulting instrument/configuration and reason. To
   clear its revalidation requirement, collect new validation specimens after the
   event, compute a new dossier after maintenance was logged, obtain its current
   accepted decision, and append a linked revalidation record. Also record a new
   passing control for the current policy. Merely accepting an old dossier later
   cannot clear maintenance. A changed configuration requires a matching policy,
   dossier and control.
7. Export the complete history before deleting its owning watch. Each run separately
   retains its QC snapshot in `source_metadata.instrument_qc`, including evaluation
   time, policy, event identities, reasons and qualification decision authority.
   **Prediction History → QC at run start** displays it. Later observations/reviews
   do not rewrite prior run evidence.

The current interface accepts versioned JSON records so the scientist can review
all authority fields exactly. It does not reinterpret numerical inputs. Timestamps
must be ISO 8601 with an explicit timezone. Future events are refused. Both
observation and server recording times are retained; late submission does not
retroactively change a saved status. Event IDs cannot be reused. Concurrent writes
must refresh history before retrying; no unseen record is overwritten.

## Policy example

The numbers and digests below are **illustrative, not recommendations or evidence**.
Use real application/configuration digests and your approved laboratory limits.
Copy the response names/units from the fitted model; unknown units are refused.
All fields are visible and required unless explicitly nullable in the typed schema.

```json
{
  "schema_version": "spectrasherpa.instrument-qc-policy/1",
  "policy_name": "Example laboratory control policy",
  "policy_version": "1",
  "artifact_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "application_plan_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "instrument_id": "NIR-1",
  "acquisition_configuration_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "control_material_id": "laboratory-control",
  "control_material_lot": "lot-1",
  "control_material_expires_at": "2027-01-01T00:00:00Z",
  "reference_method": {
    "method_id": "laboratory-reference-method",
    "version": "1",
    "response_identity": {"names": ["concentration"], "units": ["mass%"]},
    "measurement_basis": "single_measurement",
    "measurements_per_label": 1,
    "precision": null
  },
  "assigned_values": [10],
  "absolute_residual_limits": [0.5],
  "maximum_control_age_seconds": 86400,
  "aggregation": "single_observation_no_aggregation",
  "recovery": "new_passing_control_and_explicit_acknowledgement",
  "action": "report_only"
}
```

The saved policy's digest is displayed in the exact-evidence panel. Record payloads
use it explicitly. Enter event type, unique ID and event time separately in the UI.

### Control payload

```json
{
  "policy_digest": "REPLACE_WITH_RETAINED_POLICY_SHA256",
  "control_material_id": "laboratory-control",
  "control_material_lot": "lot-1",
  "measured_values": [10.1],
  "source_evidence_digest": "REPLACE_WITH_CONTROL_SOURCE_SHA256",
  "reason": "Routine independent control observation"
}
```

### Maintenance payload

```json
{
  "instrument_id": "NIR-1",
  "acquisition_configuration_digest": "REPLACE_WITH_RESULTING_CONFIGURATION_SHA256",
  "reason": "Lamp replacement and acquisition configuration verification"
}
```

### Recovery payload

```json
{
  "policy_digest": "REPLACE_WITH_CURRENT_POLICY_SHA256",
  "failed_event_id": "failed-control-id",
  "passing_event_id": "later-passing-control-id",
  "reason": "Investigation and corrective action, with explicit failure disposition"
}
```

### Revalidation payload

```json
{
  "policy_digest": "REPLACE_WITH_CURRENT_POLICY_SHA256",
  "maintenance_event_id": "maintenance-id",
  "dossier_digest": "REPLACE_WITH_NEW_DOSSIER_SHA256",
  "accepted_decision_digest": "REPLACE_WITH_CURRENT_ACCEPTED_DECISION_SHA256",
  "validation_collection_started_at": "2026-09-29T10:00:00Z",
  "validation_collection_ended_at": "2026-09-29T11:00:00Z",
  "independent_new_validation_declared": true,
  "reason": "Post-maintenance intended-use review"
}
```

Collection times and independent sampling are declared, not physically verified by
software. The server binds them to the exact new cohort and verifies chronology,
model, reference method, instrument/configuration and current review decision.
A later pending or rejected decision supersedes earlier acceptance for future QC
snapshots. Reacceptance requires an explicit new revalidation link; old events
remain historical evidence.

## Developer invariants

- `QCPolicy`, `QCEvent` and `evaluate_qc` provide the portable calculation contract.
  Imported digests establish integrity, not authenticated laboratory authorship.
- API history is owner/watch scoped, append-only, and protected by both expected
  last-event digest and unique append sequence/event identity. Equal timestamp
  ties use append order, never arbitrary event-ID spelling.
- Every failure is evaluated under its original policy. Recovery identifies a
  later passing control under the acknowledged policy. Changing thresholds cannot
  silently turn an old failure into a pass.
- Current qualification decision authority is read at the evaluation cutoff using
  its precise server-issued timestamp, not a database timestamp rounded to seconds.
- Folder-watch snapshots mean **evidence known at batch start**. They do not promise
  monitoring throughout a long batch. Concurrent QC changes do not change the
  claimed execution generation, lease, file processing state, or prediction values.
- Historical snapshots include the evidence used. Current history and the full
  JSON export remain separate from those immutable evaluations.
- No policy or evidence is silently synthesized for an upgraded watch. Existing
  local watches continue to execute with an explicit missing-QC reason.
- Local SQLite migration/component tests do not qualify actual instruments,
  hardware clocks, Windows/macOS installations or a production database.

Required regression scenarios include stable/boundary controls, failed and overdue
controls together, missing/expired material authority, policy and lot changes,
maintenance/configuration changes, old validation accepted late, superseded review,
backdated/future input, timestamp ties, concurrent submissions, service restart,
run-history/export fidelity, owner isolation, and continued report-only inference.
