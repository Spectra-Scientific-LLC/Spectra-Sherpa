# Choose Your SpectraSherpa Path

SpectraSherpa has one scientific language: a typed canonical DAG. Choose the
way you want to work; do not choose a different scientific implementation.

## Desktop download

For an application installer without a separate Python setup, see
[Desktop Downloads and Installation](../support/local_install.md). Availability
is determined by signed desktop assets on the selected release; a source tag
alone does not establish installer availability.

## Local Workbench or Python

Use this path for a laptop, workstation, notebook, or script. The default
installation includes both the visual Workbench and the supported Python SDK:

> **0.6.0 release lifecycle.** Install 0.6.0 from PyPI only after the public
> index reports that exact version. Before the public tag exists, use only the
> exact monorepo commit named by the qualification record. After the tag exists
> but before PyPI reports 0.6.0, use the exact `spectra-sherpa-v0.6.0` source
> tag. Source version text alone is not publication evidence.

After the public index reports 0.6.0:

```bash
python -m pip install "spectra-sherpa==0.6.0"
spectra-sherpa
```

For a pre-publication qualification candidate, the commands below begin inside
the exact checkout named by the qualification record:

```bash
cd packages/spectra-sherpa
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

## Hosted Team Optimization

Use the hosted product when a team needs shared projects, governed
optimization campaigns, durable audit records, or managed evidence export.
The managed service executes the same canonical node contracts as the local
product. A scientist does not assemble a hosted deployment from pip extras or
choose an internal runtime profile.

The 0.6 hosted trial is available for evaluation with its server-issued
starters. Use the published trial link for demo access; contact Spectra
Scientific for Pro, Organization, or customer-data evaluation access.
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
