# Glossary

These terms describe contracts a scientist can observe in SpectraSherpa. Each
definition links to the next practical place to use it.

| Term | Meaning and example |
| --- | --- |
| **Admitted** | Accepted after the relevant structure, bounds, and identity checks pass. Example: a `.spa` file is admitted only by its qualified native reader. See [Data Import](../workflows/data-import.md). |
| **Authority** | The single declared source allowed to decide a fact. Example: the node registry, rather than UI text, is the authority for a node's parameters. See [Workflow Execution](../architecture/workflows.md). |
| **Canonical** | The one supported representation or computation used by every product path. Example: Workbench and SDK execute the same canonical node. |
| **Closed contract** | A versioned record with a fixed set of allowed fields and explicit refusal of unknown fields. Example: a model artifact refuses an undeclared serializer. See [Model Artifacts](../architecture/model-artifacts.md). |
| **Content identity** | A digest derived from the scientific content, independent of an editable display name. Example: renaming a dataset does not change its content identity. |
| **Custody** | Who or what is permitted to hold data or fitted state, and for how long. Example: a trial workspace has temporary custody of an admitted reference. |
| **Dataset** | An n-dimensional numeric array plus axes, labels, masks, targets, metadata, and provenance. Example: 80 NIR spectra by 700 wavelengths with a moisture target. See [SherpaDataset](../architecture/sherpa-dataset.md). |
| **Digest-bound** | Linked to exact bytes or a normalized record by a cryptographic digest. Example: a registered reference grant is bound to the selected file's SHA-256. |
| **Evidence** | A reviewable record showing that a claim was checked. Example: a split plan records which groups were held out. |
| **Fitted state** | Learned model parameters needed for later application. Example: PCA loadings and centering values form fitted state. See [Model Artifacts](../architecture/model-artifacts.md). |
| **Group** | A set of rows that must stay together during validation. Example: all technical replicates from one specimen form a group. |
| **Held-out group** | A complete group assigned to evaluation and absent from training. Example: batch C is held out as a unit. See [Validation and Model Application](../chemometrics/validation-application.md). |
| **Implementation identity** | A digest of the code and contract that implement a scientific operation. Example: changing a PCA computation changes its implementation identity and reopens qualification. |
| **Projection** | A bounded, purpose-specific view of a larger object. Example: an analysis compatibility profile projects data role, target type, and group fields without copying the whole dataset. |
| **Provenance** | Append-only history of where data came from and what operations changed it. Example: clipping a spectrum records its bounds and shape change. |
| **Qualification** | Evidence that an implementation satisfies its declared scientific and software contract. Example: a node is qualified against an independent numerical oracle and its refusal cases. |
| **Sample mask** | A boolean choice of rows included in an analysis without deleting the excluded rows. Example: an outlier can be masked, reviewed, and restored. |
| **Scientific sufficiency** | Whether the data are adequate for the intended scientific claim. Example: structural compatibility with SIMCA does not prove enough replicates exist for residual limits. |
| **Structural compatibility** | Whether data expose the roles a template requires. Example: PLS regression needs a continuous target; this check does not promise good calibration. See [Datasets and Providers](../workflows/datasets-and-providers.md). |
| **Source identity** | The exact originating file or governed source record. Example: a curve hover can retain its `.spa` filename while the collection has a different title. |
| **Starter** | A readable, qualified workflow template that still requires the scientist to confirm data and intent. Example: the PCA starter connects loading, centering, PCA, plots, and outlier diagnostics. |
| **Target** | The response or class a supervised analysis predicts. Example: moisture is continuous; botanical group is categorical. |
| **Template** | A versioned starter DAG with declared data roles and qualification status. See [Templates](../workflow-templates/index.md). |
| **Workflow** | A directed graph of typed nodes, parameters, and connections that records an analysis recipe. See [Workflow Execution](../architecture/workflows.md). |

