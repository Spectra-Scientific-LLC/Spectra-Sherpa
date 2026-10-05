# Module Map

Use this map to find the public layer that owns the task you are trying to do.
Dependencies point inward: interfaces and applications may call scientific
contracts, but scientific contracts do not import hosted policy or UI code.

| Module | Scientist-facing purpose | Public interface | Dependency boundary | Representative source | Representative test |
| --- | --- | --- | --- | --- | --- |
| Native I/O (`io`) | Read a supported file and expose every admitted scientific result. | `spectra_sherpa.io` and the format registry | Bounded readers may use data contracts; no SpectroChemPy reader or fallback. | `src/spectra_sherpa/io/registry.py` | `tests/test_native_ingestion_registry.py` |
| Dataset layer | Represent n-D arrays, axes, targets, masks, metadata, and provenance. | `spectra_sherpa.SherpaDataset` and SDK dataset exports | May depend on NumPy and typed data contracts; never on the Workbench or hosted services. | `src/spectra_sherpa/app/lib/sherpa_dataset.py` | `tests/test_sherpa_dataset.py` |
| DAG and nodes | Execute one typed scientific operation at a time. | Built-in node registry and `spectra_sherpa.sdk.Node` | Nodes consume declared ports and dataset contracts; arbitrary runtime plugins are not executed. | `src/spectra_sherpa/app/services/dag/node_base.py` | `tests/test_node_catalog_contract.py` |
| Templates | Provide readable starter analysis recipes. | Workflow-template catalog | Templates may reference only admitted node types and declared data roles. | `src/spectra_sherpa/data/templates/pca.yaml` | `tests/test_workflow_templates.py` |
| Python SDK (`sdk`) | Construct datasets, workflows, analyses, plots, reports, and offline verification from Python. | `spectra_sherpa.sdk` | Lazily composes public scientific modules; importing it must not initialize hosted machinery. | `src/spectra_sherpa/sdk/__init__.py` | `tests/test_sdk_imports.py` |
| Evidence | Verify results, fitted artifacts, packages, and reproductions. | Explicit `spectra_sherpa.sdk.canonical_*` and validation modules | May read canonical scientific records; never changes the result it verifies. | `src/spectra_sherpa/sdk/canonical_project.py` | `tests/test_canonical_project_package.py` |
| Workbench app | Provide the local visual interface and local API. | `spectra-sherpa` command and browser UI | Calls public scientific/application services; local mode does not require hosted policy. | `src/spectra_sherpa/app/main.py` | `tests/test_app_factory.py` |
| Provider contracts | Add optional acquisition or deployment capabilities. | Typed contracts under `spectra_sherpa.app.contracts` | Providers may add acquisition or policy but cannot replace canonical scientific execution. | `src/spectra_sherpa/app/contracts/ai_provider.py` | `tests/contracts/test_ai_provider_contract.py` |

## Typical paths

- To **analyze data**, start with the [Workbench](../onboarding/local-30-minutes.md)
  or [`spectra_sherpa.sdk`](../onboarding/python-canonical-workflows.md).
- To **add a file format**, extend the native I/O registry and qualify its
  bounded reader.
- To **add a scientific operation**, follow [Adding a Scientific Node](../developers/adding-a-node.md).
- To **review portability**, inspect the workflow, artifact, and evidence
  contracts rather than reconstructing them from UI state.
