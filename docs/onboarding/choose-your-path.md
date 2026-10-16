# Choose Your SpectraSherpa Path

SpectraSherpa has one scientific language: a typed canonical DAG — every
analysis step is a node with declared inputs, parameters, and outputs, and the
same node definitions drive the visual Workbench and the Python SDK. Choose the
way you want to work; you are never choosing a different scientific
implementation.

## Desktop download

For an application installer without a separate Python setup, see
[Desktop Downloads and Installation](../support/local_install.md). Availability
is determined by signed desktop assets on the selected release; a source tag
alone does not establish installer availability.

## Local Workbench or Python

Use this path for a laptop, workstation, notebook, or script. The default
installation includes both the visual Workbench and the supported Python SDK:

> **Release availability.** Check the public index for the version you intend
> to install. A source version or tag alone does not establish PyPI or desktop
> availability. For source qualification, use the exact reviewed revision;
> after publication, use the corresponding public source tag.

To install the latest published package:

```bash
python -m pip install spectra-sherpa
spectra-sherpa
```

For a source build, use the exact reviewed Spectra-Sherpa checkout and run
these commands at its repository root:

```bash
python -m pip install poetry
poetry env use python3.11
poetry install
npm --prefix frontend ci          # requires Node.js 22
npm --prefix frontend run build
poetry run spectra-sherpa
```

Open the URL printed by the command, normally `http://127.0.0.1:8000`. In the
same environment, run the canonical Python quickstart:

```bash
poetry run python -m spectra_sherpa.examples.canonical_workflow
```

Add optional capabilities only when your analysis needs them:

```bash
poetry install --extras "scp"                 # EFA, MCR-ALS, and SIMPLISMA only
poetry install --extras "hitran"              # live HITRAN acquisition
poetry install --extras "nist"                # live NIST acquisition
poetry install --extras "scp hitran nist"
```

The native Workbench remains complete without these extras. Previously
acquired, content-addressed reference data can be used without the network
client that acquired it. Evidence verification is part of every installation;
it is not an optional extra.

## Hosted Demo and Pro

SpectraSherpa OSS runs locally. Demo and Pro are hosted offerings; enterprise
is an internal runtime mode. Hosted Optimize campaigns are subject to service
availability and account policy. For the local manual comparison route, see
[Optimize a Saved Result](../workflows/optimize-saved-result.md#manual-comparison-in-local-oss).

Use Demo and Pro for hosted optimization under their account policies. Governed
audit verification and evidence-pack export require separate Team, Enterprise,
or OEM entitlements; they are not Demo or Pro features. The managed service
executes the same canonical node contracts as the local product. A scientist
does not assemble a hosted deployment from pip extras or choose an internal
runtime profile.

The 0.6 hosted trial is available for evaluation with its server-issued
starters. Use the published trial link for demo access; contact Spectra
Scientific for Pro or customer-data evaluation access.
Downloaded canonical projects remain inspectable and reproducible in the local
Workbench when their declared capabilities are available.

## Hybrid

Use Hybrid when spectra and instrument data must remain on a controlled local
edge while identity, policy, and coordination are managed centrally. The edge
executes the canonical DAG; the control plane does not become a second
scientific executor. Hybrid is a provisioned deployment topology, not a public
pip extra. Its clients, enrollment UI, and transport are in a separate private
package; installing this OSS package does not enable Hybrid.

## What stays the same

Across all three paths:

- node type, parameters, ports, and implementation identity come from the one
  canonical registry;
- missing optional capabilities fail before scientific execution and name the
  exact remedy;
- project and evidence readers do not silently reinterpret retired formats;
  and
- integrity, publisher authentication, validation reproduction, and
  application reproduction remain four distinct statements.
