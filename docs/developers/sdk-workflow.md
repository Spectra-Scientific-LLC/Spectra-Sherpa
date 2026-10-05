# Portable Workflow Contract

`spectra_sherpa.sdk.workflow` defines the small, open workflow representation
that can be inspected, exported, included in evidence, and sent to a managed
Runner. The version-1 DAG is the workflow inside an independently executable
capsule, but it is not a capsule by itself: dataset, split, validation,
environment, metric, and evidence identities are supplied by the
[Workflow Capsule Contract](workflow-capsule.md). It is also not a project
export, database snapshot, UI layout, Python script, or execution sandbox.

## Version 1

A version-1 payload contains exactly `schema_version`, `nodes`, and `edges`.
Each node has a unique `node_id`, a `node_type`, and JSON parameters. Every
edge names existing source and target nodes; omitted ports normalize to
`"default"`. The graph must be acyclic. Labels, canvas coordinates,
annotations, project IDs, and database IDs are deliberately absent, so
cosmetic editing cannot change workflow identity.

```python
import spectra_sherpa.sdk as ss

workflow = ss.workflow.workflow_spec(
    nodes=[
        {
            "node_id": "source",
            "node_type": "data.file_load",
            "parameters": {"experiment_id": 1, "file_id": 1, "stage": "raw"},
        },
        {
            "node_id": "model",
            "node_type": "model.fitted_pls",
            "parameters": {"n_components": 6, "scale": False},
        },
    ],
    edges=[{"from_node_id": "source", "to_node_id": "model"}],
)
envelope = workflow.as_dict()
assert ss.workflow.verify_workflow(envelope)
print(workflow.workflow_digest)
```

The SHA-256 digest names canonical JSON with sorted nodes and edges. It makes
an accidental or unrecorded parameter/connection change detectable; it does
not sign the workflow or establish who authored it.

## Current-schema rule

Unversioned and older workflow payloads are unsupported. The SDK does not
guess, rename, or migrate their scientific meaning. Recreate the workflow in
the current workbench and review the typed DAG before execution. Missing,
unknown, and deprecated schema versions fail closed.

Construction and verification re-admit the complete graph against the current
authoritative node registry. Unknown and retired node identities, undeclared
parameters, invalid typed ports, and incompatible edges fail closed before a
workflow digest is accepted. This proves current structural admission, not
execution safety: a managed Runner additionally applies its version-pinned
profile and rejects arbitrary code, plugins, containers, pickles, and shell
commands.

Managed admission derives its execution profile from the same current
canonical registry and execution contracts used by saved-workflow admission.
The canonical Runner executes that saved typed DAG in a supervised local
process; no frozen prototype allowlist bypasses the current registry.
No loader dispatches to a module, callable, plugin, URL, or container named by
capsule content.

## Execute the same graph locally

Current `WorkflowSpec` objects execute through the same `DAGExecutor` used by
the Workbench. External data must enter through explicit `deploy.input` nodes;
application-owned `data.*` sources require the Workbench capabilities that own
their database records.

```python
execution = ss.runtime.execute_workflow(
    workflow,
    deployment_inputs={"sample": dataset},
)
print(execution.results)
print(execution.diagnostics)
print(execution.dataset_content_digests)
```

For a complete executable example including save and reopen, see
[Canonical Workflows from Python](../onboarding/python-canonical-workflows.md).
The SDK does not interpret the graph through convenience-function formulas or
an arbitrary estimator protocol.
