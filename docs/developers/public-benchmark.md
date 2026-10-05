# Governed Public Reference Datasets

`src/spectra_sherpa/data/reference_datasets_v3.json` is the qualification contract
for public datasets used by examples and qualification. Each entry binds a
stable identity to its artifact or packaged source, content digest, attribution
and license reference, exact loader settings, target, spectral domain, physical
feature-axis semantics and value digest, supervised eligibility, and frozen
development/confirmation split. The installed OSS package carries this
manifest with the code that validates it. Axis values become part of the
canonical execution capability, so coordinate-dependent preprocessing cannot
run against an unbound or substituted grid.

The registry currently admits the packaged HITRAN-derived atmospheric FTIR
fixture and the upstream Eigenvector Corn M5 moisture fixture. They use the
same closed schema and `reference_datasets` loader. Corn is not a privileged
program branch and its raw bytes are not redistributed; a local operator must
obtain the upstream file whose archive and source-file digests are pinned in
the artifact registry. The packaged atmospheric fixture is verified from its shipped
bytes. When Corn bytes are locally available, the same materialization path
verifies its source, complete arrays, physical feature axis, partitions, and
target.

Both entries are **public reproducibility fixtures**, not unseen benchmarks.
Their public samples and frozen splits may prove deterministic workflow,
metric, Runner, quarantine, receipt, and export behavior. They cannot support
managed-Harness external performance claims or customer/production-method
claims. External quantitative claims still require a separately governed,
pre-registered blind study on protected data.

Use the registry API rather than parsing JSON or naming Corn directly:

```python
from spectra_sherpa.app.lib.reference_datasets import (
    get_reference_dataset,
    materialize_reference_dataset,
)

entry = get_reference_dataset("public-atmospheric-regression-v1")
dataset = materialize_reference_dataset(entry)
development_X, development_y = dataset.development
confirmation_X, confirmation_y = dataset.confirmation
```

For a non-redistributed Eigenvector entry, pass the local cache root as
`eigenvector_data_dir`. The loader does not introduce another downloader; it
uses the existing reference-data acquisition policy and fails closed when
required bytes are absent or do not match the registry.

See [Protected Benchmark Governance](protected-benchmark-governance.md) for
the non-disclosing registry, preregistration, status-promotion, and
data-absence contracts used by the separate protected-data track.
