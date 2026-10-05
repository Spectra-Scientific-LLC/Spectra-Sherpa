# Canonical Workflows from Python

The default `spectra-sherpa` installation contains both the visual Workbench
and the Python API. They use the same typed node registry and `DAGExecutor`;
the Python API is not a second implementation of the science.

## First result in one command

After installing SpectraSherpa, run the shipped example:

```bash
python -m spectra_sherpa.examples.canonical_workflow
```

It creates a labeled FTIR-like dataset, builds `deploy.input →
preprocess.normalize → output.plot`, executes the graph, saves the exact
content-addressed workflow, reopens it, and writes the renderer-neutral plot
payload. Inspect:

```bash
cat spectra-sherpa-quickstart/run-summary.json
```

The summary names the workflow digest, input content digest, completed nodes,
diagnostic nodes, and plot trace count. `canonical-workflow.json` is the
portable analysis recipe. It is intentionally not called a project: a
Workbench project also contains datasets, saved runs, model artifacts, and
reports.

The example source is installed at
`spectra_sherpa.examples.canonical_workflow`. Its essential construction is:

```python
import spectra_sherpa.sdk as ss
from spectra_sherpa.sdk.deployment import DEPLOYMENT_INPUT_SCHEMA

workflow = ss.workflow.workflow_spec(
    nodes=[
        {
            "node_id": "spectra",
            "node_type": "deploy.input",
            "parameters": {
                "stream_name": "quickstart-spectra",
                "schema_version": DEPLOYMENT_INPUT_SCHEMA,
            },
        },
        {
            "node_id": "normalize",
            "node_type": "preprocess.normalize",
            "parameters": {"method": "snv"},
        },
        {
            "node_id": "plot",
            "node_type": "output.plot",
            "parameters": {"plot_type": "spectra", "colorscale": "Viridis"},
        },
    ],
    edges=[
        {"from_node_id": "spectra", "to_node_id": "normalize"},
        {"from_node_id": "normalize", "to_node_id": "plot"},
    ],
)
execution = ss.runtime.execute_workflow(
    workflow,
    deployment_inputs={"quickstart-spectra": dataset},
)
plot_spec = execution.output("plot", "visualization")
ss.plot.show(plot_spec)
print(workflow.workflow_digest)
print(execution.dataset_content_digests)
print(execution.diagnostics)
```

## Save and reopen the same recipe

`WorkflowSpec.as_dict()` includes the digest. `WorkflowSpec.from_dict()`
recomputes it and re-admits every node, parameter, port, and edge against the
current registry:

```python
import json

with open("workflow.json", "w", encoding="utf-8") as stream:
    json.dump(workflow.as_dict(), stream, indent=2, sort_keys=True)

with open("workflow.json", encoding="utf-8") as stream:
    reopened = ss.workflow.WorkflowSpec.from_dict(json.load(stream))

assert reopened.workflow_digest == workflow.workflow_digest
```

To save the complete scientist workspace, open `spectra-sherpa`, create a
project, add or import the same typed workflow, run it, and use **Project →
Export**. Re-importing that `.sherpa` file restores the Workbench project;
workflow JSON alone does not claim to restore data or run history.

## iPLS without a second implementation

The concise notebook interface constructs and runs a canonical
`selection.ipls` DAG. Reference values are an explicit target matrix from the
same admitted dataset; they are never guessed or fabricated.

```bash
python -m spectra_sherpa.examples.ipls_selection
```

Or from a notebook:

```python
result = ss.selection.ipls(
    dataset,
    y,
    n_intervals=10,
    max_components=5,
    cv_folds=5,
)
print(result.summary())
```

The reported interval RMSECV is calibration-set selection evidence, not an
unbiased performance estimate. Use fold-local or nested validation before a
predictive-performance claim.

## Native PCA path

Run the shipped PCA example from the default installation:

```bash
python -m spectra_sherpa.examples.native_pca
```

The example calls `ss.explore.pca`, which executes the current `model.pca`
node through Sherpa's native exact full-SVD authority and returns scores,
loadings, explained variance, diagnostics, the DAG digest, and the emitted
model artifact identity.

## Campaign Review Package: inspect, reproduce, compare

A completed managed optimization campaign produces one signed, data-free
**Campaign Review Package**. Deployment publisher custody automatically binds
the fixed application, execution source identity, and publisher statement,
then makes the final package available from the campaign. The unsigned inner
application is not the scientist-facing deliverable:

```bash
export SPECTRA_SHERPA_TOKEN='...'
spectra-sherpa campaign-review download \
  CAMPAIGN_ID managed-result.sherpa \
  --api-url https://your-spectra-host.example/api/v1
```

Independently supply the published public fixture and reproduce both the
validation result and fitted-model application:

```bash
spectra-sherpa campaign-review inspect managed-result.sherpa

spectra-sherpa campaign-review reproduce \
  managed-result.sherpa public-dataset.npz \
  --custody-id PUBLIC_CUSTODY_ID \
  --publisher-trust-anchors publisher-trust-anchors.json \
  --report reproduction-report.json
```

Read the four outcomes separately:

- `integrity_verified`: package digests are internally consistent.
- `publisher_authenticated`: the named publisher signed this content root.
- `validation_reproduced`: OSS recomputation matches the exported validation.
- `application_reproduced`: applying the imported optimized model matches the
  independently reproduced application result.

Publisher authentication does not prove scientific correctness; reproduction
does not prove who published the package. The report keeps those statements
separate on purpose.

The same package can be admitted, inspected, compared, and copied without a
running Workbench or server:

```python
import spectra_sherpa.sdk as ss

decision_chain = ss.campaign_review.inspect_campaign_review_package(
    "managed-result.sherpa",
    publisher_trust_anchors=ss.project.load_bounded_json_object(
        "publisher-trust-anchors.json"
    ),
)
print(decision_chain.as_dict())

managed = ss.campaign_review.CampaignReviewPackage.from_archive(
    ss.campaign_review.load_review_package_bytes("managed-result.sherpa")
).application
identity = ss.project.inspect_project(managed)
print(identity.outcomes.as_dict())

ss.project.reexport(managed, "verified-copy.sherpa")
comparison = ss.project.compare_projects(
    managed,
    "locally-reproduced.sherpa",
)
print(comparison.archive_bytes_identical)
print(comparison.scientific_identity_match)
print(comparison.differing_identities)
```

`archive_bytes_identical` asks whether the two project archives are exactly
the same bytes. `scientific_identity_match` compares the bound campaign,
candidate, DAG, execution, artifact, application, and confirmation identities;
it deliberately ignores presentation-only differences such as project name.
Neither result is a substitute for the four verification outcomes above.

## Optional capabilities and actionable failures

The default installation includes the Workbench, canonical native DAG, Python
API, and supported Plotly renderer. Jupyter remains owned by your notebook
environment; SpectraSherpa does not install or manage it.

> **0.6.0 release lifecycle.** Install 0.6.0 from PyPI only after the public
> index reports that exact version. Before the public tag exists, use only the
> exact monorepo commit named by the qualification record. After the tag exists
> but before PyPI reports 0.6.0, use the exact `spectra-sherpa-v0.6.0` source
> tag. Source version text alone is not publication evidence.

| What you tried | Required action |
|---|---|
| A SpectroChemPy-backed node such as EFA, MCR-ALS, or SIMPLISMA | After 0.6 publication: `pip install 'spectra-sherpa[scp]==0.6.0'` |
| NIST WebBook acquisition | After 0.6 publication: `pip install 'spectra-sherpa[nist]==0.6.0'` |
| HITRAN acquisition or synthesis | After 0.6 publication: `pip install 'spectra-sherpa[hitran]==0.6.0'`, then configure the required HITRAN credentials |
| An application-owned dataset source from Python | Bind arrays with `deploy.input`, or run the application-owned source in the Workbench |
| An imported fitted-artifact application from Python | Load the Campaign Review Package and provide its read-only artifact adapter through `ExecutionRuntime` |

These checks fail before scientific execution. Missing optional software or a
missing runtime capability is never replaced by fabricated data, an in-process
fallback, or a different algorithm.

## Apply a cloud-optimized solution to a local watched folder

1. From the completed cloud campaign, download the **signed Campaign Review
   Package** and **publisher verification keys** from the trusted cloud site.
   The latter contains public keys only; it is not a license or a private key.
2. In local OSS, choose **Project → Import** and select the `.sherpa` package.
   If prompted, select the independently obtained public-key JSON and confirm
   its source. It authenticates this import only. Managed deployments continue
   to use their operator-configured publisher trust.
3. Choose **Configure folder watch**, or open **Deploy → New Watch**. Select the
   imported campaign solution, incoming folder, file pattern and (for multi-asset
   files) exact asset ID. Enable the watch after reviewing its settings.
4. Inspect **Prediction History** for each file's prediction or explicit error.
   The saved run retains the exact artifact, application plan, parameters and
   incoming-file evidence. Restarting the worker keeps the same binding.

The local application uses the exported fitted preprocessing and model. It does
not retrain, require the original training dataset, or call the cloud for
inference. This path uses the shared local engine in pip and desktop editions.
If a required numerical dependency is unavailable, the model picker explains
which certified runtime must be installed.

Incoming data must retain the fitted feature order, values and units. Sherpa
portable CSV preserves this metadata; an ordinary CSV with numeric headings may
not include units. Incompatible, empty or nonfinite inputs produce per-file
errors rather than silently converted predictions. Correct the source and submit
it under a new filename; an already attempted filename is retained in watch
history to prevent repeated processing.
