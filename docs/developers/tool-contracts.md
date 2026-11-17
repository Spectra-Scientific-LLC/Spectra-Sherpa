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
