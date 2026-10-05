# Migrate to SpectraSherpa 0.6

> **0.6.0 release lifecycle.** Install 0.6.0 from PyPI only after the public
> index reports that exact version. Before the public tag exists, use only the
> exact monorepo commit named by the qualification record. After the tag exists
> but before PyPI reports 0.6.0, use the exact `spectra-sherpa-v0.6.0` source
> tag. Source version text alone is not publication evidence.

Version 0.6 makes the product boundary simpler: the default package contains
the native Workbench and Python SDK together, scientific execution is
canonical-DAG only, and optional SCP/HITRAN/NIST capabilities are explicit.
This is a breaking release. Read the checklist before upgrading a retained
environment.

## Before upgrading

1. Stop every running SpectraSherpa process.
2. Export current canonical projects that you need to exchange with another
   machine.
3. Back up the local data directory. Its default is `~/.spectra_sherpa`:

   ```bash
   cp -a "$HOME/.spectra_sherpa" "$HOME/.spectra_sherpa.pre-0.6-backup"
   ```

4. Record your existing environment for troubleshooting:

   ```bash
   python -m pip freeze > spectra-sherpa-pre-0.6-packages.txt
   ```

## Recommended: install into a fresh environment

A fresh environment makes removed compatibility packages and undeclared
dependencies impossible to hide. Before public publication, evaluators must
begin from the exact monorepo commit named by the qualification record, then
let Poetry create and populate the fresh environment:

```bash
cd packages/spectra-sherpa
python -m pip install poetry
poetry env use python3.11
poetry install
npm --prefix frontend ci          # requires Node.js 22
npm --prefix frontend run build
poetry run spectra-sherpa
```

The first start applies the current local database migrations. Verify both
surfaces from the same environment:

```bash
curl --fail http://127.0.0.1:8000/api/ready
poetry run python -m spectra_sherpa.examples.canonical_workflow
```

## In-place upgrade after publication

Perform an in-place upgrade only after PyPI reports 0.6.0 and the release map
records its exact artifact, and only when you have retained the backup above:

```bash
python -m pip install --upgrade "spectra-sherpa==0.6.0"
spectra-sherpa
```

If you need optional capability, name it during the upgrade—for example,
`spectra-sherpa[scp]` or `spectra-sherpa[hitran,nist]`. Do not install a
separate SDK package; importing `spectra_sherpa.sdk` is supported by the same
default product installation.

## Breaking changes to expect

- Retired prototype workflows, V1 capsules/materializers, and schema-1
  evidence are rejected rather than translated. Historical evidence remains
  inspectable with the frozen tooling at commit
  `34fb8d35acae33107b5ce73bf620e76cf2545100`.
- `SherpaDataset` has one current wire authority, version `3.0`, including
  intrinsic per-dimension scale, label, title, class, include, descriptive,
  source, history, and layout state. Versionless, `1.0`, and `2.0` dataset
  payloads and projects containing them are rejected rather than reconstructed.
  Re-import the original scientific source into 0.6; there is intentionally no
  artifact compatibility adapter.
- Arbitrary-estimator SDK cross-validation helpers and the SDK-local
  confirmation quarantine are removed. Use canonical workflow validation and
  managed confirmation authorities.
- `UPLOAD_ALLOWED`, `DATA_UPLOAD_ALLOWED`, and the retired Python import aliases
  have no effect. The free hosted trial accepts only exact server-issued Avatar
  and Corn starters; subscription cloud and Enterprise Hybrid own customer-data
  upload and import journeys.
- SCP, HITRAN, and NIST are independent optional capabilities. No missing
  capability invokes a substitute algorithm.
- Current PLS and PLS-DA use the cited Sherpa SIMPLS authority. Old fitted
  artifact serializer versions fail closed.
- `cv_folds` was retired from `classification.knn`, `classification.plsda`,
  and `classification.simca`. These legacy nodes are not auto-migrated because
  their former output ports contained hidden cross-validation diagnostics
  while the current ports contain calibration-fit diagnostics. Before
  upgrading, record their fit parameters, remove those nodes in the old
  version, then recreate them in 0.6 and connect an explicit held-out split or
  grouped fold plan. Startup and saved project admission fail closed if such a
  node remains, including nodes that relied on the old default and did not
  store `cv_folds`. New workflow versions and project archives carry the exact
  current validation-semantics authority; a missing or unknown authority is
  refused instead of guessed.

If current canonical data does not open after a migration, stop and restore
the backup instead of editing the SQLite database or archive by hand.
