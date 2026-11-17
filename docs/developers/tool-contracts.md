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
does not introduce registry freezing or transport alias collision checks.

Contract declarations describe inputs, outputs and effects. They do not contain
agent procedures or supplied skill content. OSS MCP transport and catalog
projection are separate implementation steps.
