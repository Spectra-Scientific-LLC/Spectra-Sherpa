# Tool contracts

`ToolDefinition` in `app/services/tools/schemas.py` owns tool interface metadata.
`ToolRegistry` owns registration under the existing `name`; Advisor names and
provider function-calling payloads keep their existing meaning.

The optional fields prepare explicit operation classification:

| Field | Meaning |
| --- | --- |
| `version` | Interface major.minor version, such as `1.0`; not the package version |
| `output_schema` | Declared JSON Schema for the handler result; declaration alone does not validate returned data |
| `mutation` | `read` inspects existing facts, `compute` performs computation, `write` changes durable application state |
| `disclosure` | Data classes a result may reveal: metadata, statistics, metrics, values, identifiers |
| `distribution` | Implementation distribution (`oss` or `pro`); not an entitlement grant |
| `mcp_name` | Proposed transport name; not a registered alias or automatic export |

Missing metadata means unclassified, not permitted. These declarations do not
authorize discovery, invocation, data disclosure or network access. Existing
scope, user and egress checks remain in force. A future transport must apply an
explicit operation allowlist and its own admission checks; it must not expose
the registry wholesale. Existing provider payloads omit these fields.

Registration rejects a duplicate `name` with `ValueError` before changing the
existing definition or handler. Callers must not rely on silent replacement.
Explicit unregistration remains available for lifecycle cleanup. This change
does not introduce registry freezing.

Contract declarations describe inputs, outputs and effects. They do not contain
agent procedures or supplied skill content. OSS MCP transport and catalog
admission is a separate implementation step.

## Explicit catalog projection

`project_tool_catalog(registry, tool_names)` describes only the named selection.
An empty selection returns no operations. Missing registrations, incomplete
classification, duplicate identities and duplicate projected names raise
`ValueError`; no partial catalog is returned. Definitions are revalidated and
copied so a consumer cannot alter registration by editing the returned catalog.
Results are sorted by projected name, independent of selection order.

This helper does not invoke handlers, enforce actor/project permissions or
determine which operations a transport may expose. Calling code must supply a
reviewed selection and separately enforce admission. `tool_id` preserves the
existing registry identity; `name` is the declared transport name. Projection
does not install an alias in the registry or alter provider payloads.

The first classified operation is `list_node_types`, version `1.0`. Its result
describes installed catalog node types, not nodes saved in a workflow. An
unmatched category yields an empty list. Labels are presentation text and
descriptions are truncated to 120 characters; neither is a stable identifier.
Its output schema resides on the registration, beside its input schema.

Existing `list_nodes` and `describe_nodes` registrations remain distinct from
`list_node_types` and `describe_node`. The former have different inputs and
result fields. No automatic rename or bulk classification is applied. Other
operations require interface review before selection, including their units,
population roles, retention guarantees and refusal behavior where applicable.

## Registered inspection credentials

`inspection_grants.py` owns the credential lifecycle; `InspectionGrant` owns
its persisted record. Issuance requires a trusted, authenticated Workbench
actor with current project read access. A client label is display text only.
The returned random bearer secret is shown once; storage retains only its
SHA-256 digest. The generated client ID and project ID are bound to that secret.
The caller owns the transaction and must commit issuance or revocation.

Authentication refreshes the grant, active principal and existing project
access authority. Revoked, expired and mismatched credentials receive the same
refusal. The default lifetime is one day, capped at 30 days. The initial
disclosure classes are metadata, statistics and metrics; values and identifiers
cannot be granted through this interface.

Authenticate each request in a fresh transaction. The returned identity is a
per-request result, not a reusable authorization cache. A transport must also
enforce the reviewed operation allowlist, disclosure policy, resource limits
and call logging. Already admitted work is not cancelled by this lifecycle
service. No issuance, revocation or approval operation belongs in the agent's
tool catalog. Workbench connection UI and transport admission are separate
integration steps.

## Local inspection connection control

The local bridge admits `list_node_types`, called directly through
its existing implementation. It returns an object with `items` and `next_offset`;
`offset` starts at zero and `limit` is 1–100 (default 25). This is installed public
node metadata, not project data. It does not invoke the tool registry dispatcher.
The two project readers below use their existing privacy policies and canonical
summaries. No skill content or execution is added.

In the local browser Workbench, Settings → Integrations manages connections for
the selected project. Creation requires acknowledgement that an external client
may send results to its AI provider. Each connection receives only the metadata
disclosure, a client ID and a one-time credential, expiring after the selected
period. The UI keeps the secret in memory and discards it on project/account
changes or unmount; it is never stored in browser storage. Lost credentials must
be revoked and replaced. Connection and call-history lists show the latest 100
records. The packaged desktop interface does not expose this control: its
existing desktop-session protection remains required.

Control requests use ordinary Workbench identity plus
`X-Spectra-Workbench: inspection`, with a configured or same-origin loopback browser Origin when present.
An inspection bearer cannot invoke connection control. This is browser CSRF
protection, not isolation against another local operating-system process: local
Workbench mode already grants implicit identity to loopback callers.

`POST /api/v1/inspection/{project_id}/{client_id}/call` requires the inspection
bearer independently of implicit Workbench identity. The service authenticates
against fresh database state before reading and again before returning results,
so revocation or loss of project access during a read prevents disclosure.
It never accepts a project identity inside operation arguments. Nonlocal hosts
and nonlocal product modes are refused.

Requests are capped at 8 KiB with a five-second body deadline. Inspection
has four per-process worker slots, a five-second admission/read
budget, a 4,096-node catalog ceiling and a 64 KiB response ceiling. A timed-out
worker retains its slot until it exits. The HTTP operation has an additional
20-second deadline. These limits do not authorize costly statistics or workflow
execution. Failed authenticated admissions and successful reads retain local
project call outcomes without credentials, arguments or response contents;
unauthenticated requests cannot claim a project log identity. This history is
ordinary local storage, not tamper-evident commercial evidence. Cancellation,
the outer HTTP deadline and database failures may leave no outcome record; it
is not an exhaustive request audit. Deleting its
project also deletes its connection and call history.

## Project dataset and workflow summaries

`describe_dataset` accepts only an existing `dataset_id` registered in this
Workbench process for the credential's owner and project. It calls the existing
canonical tier-0 descriptor: shape, axis/context metadata and descriptive text.
It does not return raw values or sample labels, compute statistics, or interpret
scientific suitability. Unbound and other-project handles are refused. Registry
owner/project checks and the 16 MiB retained-object ceiling run before snapshot
copying. Process-local handles do not survive a Workbench restart; the ordinary
Workbench must register the dataset again.

`inspect_workflow` accepts only a `workflow_id` belonging to the same owner and
project. It returns the canonical saved-workflow summary: ID/name, node and edge
counts, and distinct node types. The summary is a live read, not an immutable revision snapshot.
Counts describe the saved graph, not an executed
population or model quality. Reads select only summary columns, with ceilings of
500 nodes and 1,000 edges. Parameters, full topology, results, exports and
execution are outside this operation.

Both readers require explicit project-summary consent when creating a new
connection. The checkbox is off by default. Existing credentials remain
catalog-only after upgrade; revoke and replace them to grant broader access.
Consent is persisted and checked before and after each read.

Both readers also require the connection's metadata disclosure and the existing
global egress switch plus metadata-to-LLM-context permission. Workflow inspection
also requires workflows-to-LLM-context permission. Connection consent does not
override these settings. Missing fine-grained overrides use existing user defaults;
policy lookup failures refuse disclosure. Current identity, project membership,
object binding and privacy policy are checked again before returning results.
A privacy change during a read therefore prevents disclosure. Tool discovery
lists the supported interfaces, not a guarantee that the current privacy policy
allows each call. Clients cannot request a higher tier or full graph, supply a
project override, or dispatch arbitrary tool names.

## Optional MCP stdio adapter (v0.7.0 development)

Install `spectra-sherpa[mcp]` in the same environment as Workbench. The base
installation does not include the MCP SDK. Start the local browser Workbench,
select a project, and create an inspection connection in Settings → Integrations.
Configure a stdio client to run:

```text
spectra-sherpa mcp --workbench-url http://127.0.0.1:8000 --project-id PROJECT_ID --client-id CLIENT_ID
```

Provide the one-time credential in the child process environment as
`SPECTRA_INSPECTION_CREDENTIAL`. Keep it out of command arguments and version
control. A different environment variable name can be selected with
`--credential-env`; the adapter does not load `.env` files. The URL must use an
HTTP loopback IP (`127.0.0.1` or `::1`), with the actual Workbench port. Proxies,
redirects, remote hosts, URL credentials and arbitrary API paths are refused.

The adapter advertises `list_node_types`, `describe_dataset` and
`inspect_workflow`. Input and output meanings come from reviewed tool contracts
and bounded bridge argument models. The node catalog response wraps the
existing array as `items` plus `next_offset`; project readers return their
existing summary objects. Input lines are
limited to 16 KiB before JSON-RPC parsing; bridge requests and responses retain
the limits above. Normal startup messages do not enter protocol stdout.

A handshake's client name grants no authority. Tool listing checks the live
Workbench credential; each call repeats admission in Workbench. Existing
connections survive Workbench restart, while revocation remains effective after
restart. The adapter advertises no prompts, resources, supplied skills or write
tools. No workflow creation or execution instructions are supplied by this
interface.

Compatibility must be reported by executed client/version and artifact. The
qualification harness `scripts/qualify_mcp_install.py` exercises the MCP Python
SDK against an installed wheel and records startup, stdio reads, write refusal,
and restart/revocation results. It does not establish compatibility with other
AI applications or evaluate an AI model's scientific reasoning. Public CI runs
this probe on Ubuntu for PRs and on Linux, Windows and macOS for manual, weekly
and main-branch qualification. Desktop packaging remains outside this probe.
