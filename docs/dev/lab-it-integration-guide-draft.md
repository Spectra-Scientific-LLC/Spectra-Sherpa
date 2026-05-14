# Draft Lab IT Integration Guide for Spectra Sherpa OSS

**Status:** Draft for partner discussion. Not a validated implementation manual.
**Audience:** Laboratory IT, LIMS / ELN / metadata-system owners, QA systems engineers, and integration partners.
**Primary use case:** Connect a local or hybrid Spectra Sherpa OSS deployment to an existing laboratory metadata system so workflow executions, model artifacts, and reproducibility records can be associated with lab-controlled project, sample, method, and record identifiers.
**Regulatory framing:** Spectra Sherpa can support an ISO/IEC 17025 quality system by producing technical-record evidence. The laboratory remains responsible for validation, SOPs, user training, record retention, access control, backups, and accreditation claims.

This guide is intentionally procedural. Treat it like a draft scientific method: start with assumptions, define materials, execute controlled steps, record observations, and decide whether the evidence is sufficient for the lab's quality system.

---

## 1. Assumptions

1. The lab partner will work from the public OSS repository:
   `https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa`
2. The private monorepo is not required for this integration. The proprietary Spectra Server package may add chain verification, retention automation, signed exports, and admin workflows later, but the first integration should prove the OSS hooks and metadata mapping.
3. The lab has an existing metadata authority, such as a LIMS, ELN, SDMS, Covalent-managed metadata service, or internal database.
4. The external metadata system remains the source of truth for sample identity, batch / lot identity, instrument identity, analyst identity, method identifiers, study identifiers, and controlled vocabulary.
5. Spectra Sherpa remains the source of truth for local workflow structure, workflow versions, execution runs, node parameters, generated model artifacts, and workflow export bundles.
6. Python 3.11 or 3.12 is available on the target workstation or server. Python 3.13+ should be treated as experimental for the scientific stack.
7. For chemometric examples and advanced file readers, the lab should install the optional SpectroChemPy extra with `spectra-sherpa[scp]`.
8. A single local deployment may use SQLite by default. Shared lab deployments should plan for a managed database, backup policy, and access-control model before production use.
9. The audit trail described here is based on the ISO-readiness plan. Some endpoint names, field names, and event coverage may still be draft and must be checked against the installed release.
10. `SHERPA_AUDIT_ENABLED=true` is assumed for validation and integration testing. When audit is disabled, audit emission is expected to be a no-op.
11. The initial OSS integration should focus on read/write metadata linkage and audit-event extraction. Tamper-evident hash-chain verification may require Spectra Server or a partner-maintained equivalent.
12. The lab will perform its own IQ/OQ/PQ or equivalent software validation before using the integrated system for regulated work.
13. The integration should avoid uploading proprietary lab data to public demos or external services unless the lab has explicitly approved that data path.
14. Network egress should remain deny-by-default unless the lab IT owner approves a specific destination, credential, and data category.
15. This draft does not cover electronic signatures, 21 CFR Part 11, measurement uncertainty, final report approval, or accreditation-body submission.

---

## 2. Objective

Connect Spectra Sherpa OSS to the lab's metadata system so that each analytical workflow run can be traced from:

1. lab project / study / batch context,
2. input files and sample identifiers,
3. Spectra Sherpa workflow and node parameters,
4. generated results and model artifacts,
5. audit events and reproducibility records,
6. exported evidence bundles for QA review.

The expected outcome is a working draft integration that lets lab IT answer:

- Which lab-controlled samples or files were used in this Spectra Sherpa run?
- Which workflow version and parameter set produced the result?
- Which operator or service account initiated the run?
- Which model artifacts were created or used?
- Can the lab retrieve a machine-readable record for the run?
- Can the lab repeat the workflow or export it for independent review?

---

## 3. Materials and prerequisites

| Item | Draft requirement |
|---|---|
| Spectra Sherpa OSS | Public GitHub checkout or PyPI package |
| Python | 3.11 or 3.12 |
| Optional spectral stack | `spectra-sherpa[scp]` for SpectroChemPy readers and examples |
| Lab metadata system | API, database view, file export, or message queue controlled by lab IT |
| Test dataset | Public data first; lab-approved non-sensitive data second |
| Test workflow | A shipped template or simple lab-created workflow |
| Test identities | One human analyst account and one service account |
| Validation notebook | Lab-controlled place to record commands, versions, screenshots, and observations |
| Backup location | Approved local or network storage for database, imported files, exports, and audit evidence |

---

## 4. Proposed integration architecture

```text
Lab metadata system
  |
  | 1. Project / sample / file / method metadata
  v
Spectra Sherpa OSS connector layer
  |
  | 2. Data binding + metadata sidecar
  v
Spectra Sherpa project / experiment / workflow
  |
  | 3. Workflow execution
  v
ExecutionRun + ModelArtifact + AuditEvent records
  |
  | 4. Audit query / export / partner ETL
  v
Lab metadata system, QA archive, or evidence repository
```

### Recommended split of responsibility

| Responsibility | Lab metadata system | Spectra Sherpa OSS |
|---|---:|---:|
| Sample identifiers | Owner | Reference |
| Instrument identifiers | Owner | Reference |
| File receipt / chain of custody | Owner | Reference |
| Workflow graph | Reference | Owner |
| Node parameters | Reference after sync | Owner |
| Workflow execution result | Reference after sync | Owner |
| Model artifact metadata | Reference after sync | Owner |
| Audit-event creation | Reference after sync | Owner |
| Audit-chain verification | Optional / future | Optional / server-side future |
| ISO validation package | Owner | Evidence contributor |

---

## 5. Installation procedure

### 5.1 Install from PyPI for a workstation proof of concept

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install "spectra-sherpa[scp]"
spectra-sherpa
```

Open the local application after the server prints that it is listening on `http://127.0.0.1:8000`.

### 5.2 Install from source for connector development

```bash
git clone https://github.com/Spectra-Scientific-LLC/Spectra-Sherpa.git
cd Spectra-Sherpa
pip install poetry
poetry env use python3.12
poetry install --with dev --extras "scp"
poetry run spectra-sherpa
```

Only install Node.js and frontend dependencies if the connector requires user-interface changes.

### 5.3 Draft audit configuration

Create an environment file or service configuration equivalent to:

```bash
SHERPA_AUDIT_ENABLED=true
SHERPA_MODE=local
DATA_DIR=/approved/lab/path/spectra-sherpa-data
```

Field names may change. Record the exact environment variables used in the lab's installation qualification notes.

---

## 6. Metadata mapping procedure

Create a mapping table before writing connector code. The table should be approved by lab IT and QA before any production data is processed.

| Lab field | Example | Spectra Sherpa target | Required? | Notes |
|---|---|---|---:|---|
| `lab_project_id` | `STUDY-2026-0042` | Project external reference | Yes | Stable study or project identifier |
| `sample_id` | `SMP-000182` | Experiment file metadata or input-port descriptor | Yes | Must match lab source of truth |
| `sample_role` | `calibration`, `validation`, `unknown` | Dataset / workflow input context | Yes | Critical for chemometric interpretation |
| `instrument_id` | `FTIR-07` | File metadata context | Recommended | Lab-owned equipment record |
| `method_id` | `MTH-PLS-NIR-001` | Workflow metadata or workflow version context | Recommended | Lab method or SOP reference |
| `operator_id` | `j.smith` | Audit actor mapping | Yes | Human or service account |
| `source_file_uri` | `s3://...` or file path | Experiment file source path | Yes | Avoid storing credentials in the URI |
| `source_file_hash` | `sha256:...` | Input-port descriptor / file metadata | Yes | Compute before import when possible |
| `batch_id` | `LOT-4519` | Experiment metadata | Optional | Required if lab SOP depends on batch lineage |
| `lims_record_url` | internal URL | Metadata sidecar context | Optional | Do not expose outside lab network |

Acceptance criterion: given any Spectra Sherpa execution run, lab IT can identify the corresponding lab project, samples, files, operator, and method record without manual guesswork.

---

## 7. Connector implementation patterns

Choose the least invasive pattern that satisfies the lab's traceability needs.

### Pattern A: File-drop plus metadata sidecar

Use this when the lab metadata system can export files and JSON sidecars.

```text
incoming/
  SMP-000182.spc
  SMP-000182.metadata.json
  SMP-000183.spc
  SMP-000183.metadata.json
```

The sidecar should include sample IDs, file hashes, method IDs, and source-system references. Spectra Sherpa imports the files and preserves sidecar metadata in project or experiment records.

Best for: fast proof of concept, low coupling, local workstations.

### Pattern B: Pull connector

Use this when Spectra Sherpa should request metadata from the lab system.

Draft flow:

1. User selects a lab project or sample set in Spectra Sherpa.
2. Connector calls the lab metadata API.
3. Connector receives file references, hashes, sample roles, and method context.
4. Connector creates or updates Spectra Sherpa project / experiment records.
5. User binds the imported data to a workflow template.

Best for: metadata systems with stable APIs and approved service accounts.

### Pattern C: Push connector

Use this when the lab metadata system orchestrates analysis.

Draft flow:

1. Lab metadata system creates an analysis request.
2. Request contains project ID, sample IDs, file locations, and target workflow template.
3. Spectra Sherpa imports the request and prepares a workflow.
4. Analyst reviews, executes, and exports results.
5. Spectra Sherpa sends execution-run and artifact references back to the lab system.

Best for: production LIMS / ELN workflows.

### Pattern D: Export-only integration

Use this when the lab wants Spectra Sherpa to stay fully local.

Draft flow:

1. Analyst runs Spectra Sherpa locally.
2. Analyst exports workflow, run record, audit events, and model artifacts.
3. Lab metadata system ingests the exported evidence bundle.

Best for: early validation, restricted networks, air-gapped labs.

---

## 8. Draft API and event expectations

Endpoint names are provisional. Verify against the installed build before implementation.

### 8.1 Audit events

Expected OSS event classes from the ISO-readiness plan:

| Event action | Meaning | Integration use |
|---|---|---|
| `workflow.run.started` | User initiated a workflow run | Start of technical record |
| `workflow.run.completed` | Workflow completed and results were persisted | Primary success record |
| `workflow.run.failed` | Workflow failed and failure record was persisted | Nonconforming or troubleshooting record |
| `workflow.run.partial` | Some nodes completed and some failed | Treat as review-required |
| `model_artifact.created` | Model artifact record was created | Link model to workflow, files, and method |
| `workflow.version.created` | Draft / future | Link parameter and graph changes to method history |
| `workflow.parameter.changed` | Draft / future | Link parameter change to analyst and reason |
| `audit.export` | Draft / server-side future | Evidence export meta-audit |

Draft local audit query:

```bash
curl "http://127.0.0.1:8000/api/v1/audit/events?target_type=ExecutionRun"
```

If the endpoint is not present in the installed OSS build, partners can use an approved database read, JSON export, or interim script during the proof of concept. Production use should prefer a supported API.

### 8.2 Workflow execution record

For each workflow execution, preserve at minimum:

| Field | Purpose |
|---|---|
| Workflow ID and version ID | Reconstruct the workflow definition |
| Workflow integrity hash | Detect graph or parameter drift |
| Parameter set | Identify the actual method settings |
| Input ports | Link each input to dataset, file, sample, and target hashes |
| Model artifact IDs | Link generated models to the run |
| Parent model artifact ID | Link prediction runs to the model used |
| Software version and git commit | Identify the executing build |
| Node registry hash | Detect plugin or node-catalog drift |
| Python runtime and lockfile hash | Reconstruct dependency environment |
| Operator / actor | Identify who initiated the run |
| Request ID | Correlate logs and audit events |

The current implementation may not populate every field automatically. Missing fields should be logged as validation gaps, not silently ignored.

---

## 9. Validation procedure for the partner proof of concept

### 9.1 Installation qualification

Record:

1. Operating system and version.
2. Python version.
3. Spectra Sherpa version or git commit.
4. Install command.
5. Optional extras installed.
6. Data directory path.
7. Audit configuration.
8. Database location and backup method.

Acceptance criterion: a second lab IT engineer can reproduce the same install from the recorded steps.

### 9.2 Operational qualification with public data

1. Start Spectra Sherpa.
2. Load a bundled public dataset or public template.
3. Execute a simple workflow.
4. Save or export the workflow.
5. Retrieve execution-run metadata.
6. Retrieve or inspect audit events.
7. Confirm that workflow ID, workflow version, parameters, software version, and result status are present.

Acceptance criterion: public-data run produces a retrievable technical record without manual database repair.

### 9.3 Operational qualification with lab-approved test data

1. Export a non-sensitive sample set from the lab metadata system.
2. Include file hashes and sample identifiers.
3. Import or bind the data into Spectra Sherpa.
4. Execute the selected workflow.
5. Confirm that lab sample IDs and file hashes are visible in the Spectra Sherpa record or companion metadata export.
6. Export the evidence bundle.
7. Reconcile the bundle against the lab metadata system.

Acceptance criterion: every lab sample in the workflow run can be traced back to the source metadata record.

### 9.4 Negative testing

Run at least these failure cases:

| Test | Expected result |
|---|---|
| Missing metadata sidecar | Import blocked or warning recorded |
| File hash mismatch | Import blocked or run marked invalid |
| Unknown sample ID | Import blocked or mapped to quarantine project |
| Audit disabled accidentally | Validation fails before regulated use |
| Workflow execution failure | `workflow.run.failed` or equivalent record exists |
| Partial workflow result | Result is clearly marked review-required |
| Metadata API unavailable | Connector fails closed or queues request per SOP |

---

## 10. Security and data-governance checklist

1. Use service accounts with least privilege for metadata-system access.
2. Do not store LIMS, ELN, database, or cloud-storage credentials inside workflow node parameters.
3. Keep network egress disabled unless a specific connector endpoint is approved.
4. Use TLS for any shared deployment or metadata-system connection.
5. Store imported data, local database files, model artifacts, and exports on approved storage.
6. Back up the data directory and database on a schedule approved by lab IT.
7. Define who may export evidence bundles.
8. Define who may delete local files outside Spectra Sherpa. Audit trails cannot compensate for unmanaged filesystem deletion.
9. Review AGPL-3.0 obligations before distributing modified OSS builds or offering a modified build as a network service.
10. Keep a change log for connector code, environment variables, and mapping-table revisions.

---

## 11. Suggested handoff package from lab IT to QA

At the end of the proof of concept, lab IT should provide:

1. Installation qualification notes.
2. Metadata mapping table.
3. Connector architecture diagram.
4. Source-system API contract or file-sidecar schema.
5. Test dataset description.
6. Public-data workflow run evidence.
7. Lab-test-data workflow run evidence.
8. Audit-event export or database extract.
9. Known gaps against the minimum reproducibility record.
10. Security review notes.
11. Backup and restore notes.
12. Recommendation: proceed, revise, or stop.

---

## 12. Known draft gaps

These items should be resolved before production regulated use:

1. Confirm exact OSS audit query endpoint and response schema.
2. Confirm which workflow version and parameter-change events are implemented in the installed release.
3. Confirm whether `workflow.run.partial` is a supported permanent event or a temporary implementation detail.
4. Confirm how input-port file hashes, target hashes, and preprocessing fitted-state hashes are populated.
5. Confirm whether the lab needs tamper-evident chain verification in OSS, Spectra Server, or the lab metadata system.
6. Confirm retention and archive responsibility for local SQLite deployments.
7. Confirm whether shared lab deployment requires external authentication and role mapping.
8. Confirm how model deletion, model replacement, and model retirement are recorded.
9. Confirm whether the lab needs electronic signatures; this draft assumes no.
10. Confirm whether final reports require lab approval workflow outside Spectra Sherpa; this draft assumes yes.

---

## 13. Minimal success definition

The draft integration is successful when a lab IT partner can independently:

1. Install Spectra Sherpa OSS.
2. Load public data and execute a template workflow.
3. Load lab-approved test data with metadata.
4. Execute a workflow and generate results.
5. Save or export the workflow.
6. Retrieve run metadata and audit evidence.
7. Reconcile the Spectra Sherpa run back to lab-controlled sample and method records.
8. Produce a short validation memo listing what evidence exists and what remains outside Spectra Sherpa.

This is not ISO/IEC 17025 certification. It is a controlled technical proof that Spectra Sherpa OSS can participate in the lab's validated information-management workflow.
