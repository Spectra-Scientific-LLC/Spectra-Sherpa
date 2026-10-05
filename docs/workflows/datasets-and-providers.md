# Datasets and Providers

SpectraSherpa keeps the scientific dataset independent of the route by which
its source arrived. Once loaded, the same dataset supports
inspection, masking, workflows, provenance, and export.

## Ways data can enter

| Source route | Who obtains or creates the bytes? | What Sherpa checks |
| --- | --- | --- |
| Local user data | The scientist selects files already on the workstation. | Every supported file is checked by its native reader; unsupported members refuse while independently valid selections may still load. |
| Pro cloud upload | The customer selects data they are authorized to process. | The deployment controls storage and retention; the reader checks the file format and structure. |
| Built-in redistributable example | SpectraSherpa packages or provisions data only with recorded permission to distribute it. | The example files and expected measurements are both verified. |
| User-acquired reference (such as the Eigenvector teaching catalog) | The scientist obtains the file directly from the provider. | Sherpa checks the selected local file; it does not retrieve, proxy, or redistribute these provider archives. |
| Verified reference file | The scientist selects a provider-obtained file. | Sherpa checks that this is the reviewed file version and contains the expected measurements. A matching filename alone is insufficient. |
| Synthetic dataset | The scientist requests a declared mathematical or reference-based generator. | Parameters, source citations, random seeds, and generated content identity enter provenance. |

File verification does not grant permission to use or redistribute data. Users remain responsible for having the right to
process files they submit.

## Loading a reviewed teaching dataset

1. Open the provider catalog and obtain the supported file from the provider.
2. In Sherpa, select that file from your computer. A familiar filename alone
   does not establish that it is the reviewed dataset.
3. Confirm the dataset name, spectra, axis, sample count, and available targets
   in the preview. For registered references, Sherpa checks both the reviewed
   file identity and the expected scientific contents.
4. Bind the target and any validation groups before choosing an analysis.

Provider rules differ. The user-acquired Eigenvector archive path is distinct
from optional NIST reference retrieval or HITRAN/HAPI synthesis. Use the relevant
provider configuration and permissions; a file checksum proves identity, not
permission to redistribute it. Demo allows only its documented reference-file
exception, while local OSS and Pro accept ordinary supported customer files.

## Targets and validation groups

A target may arrive in the same table as the predictors or in a separate CSV
sample table. A separate table is joined by stable sample identity, not assumed
row order. Continuous targets enable regression; categorical targets enable
classification. A validation group identifies rows—such as technical
replicates from one specimen or measurements from one batch—that must remain
together during a split.

Changing a bound target or group changes the dataset's analysis settings and
immediately recomputes compatibility. The underlying spectra do not have to be
re-imported.

## Compatibility is computed, not assigned

Datasets are not permanently associated with models. SpectraSherpa compares the
loaded dataset's data role, target type, and available group fields with a
template's declared requirements. The result is **structural compatibility**:
it can say “needs a numeric target” or “needs class labels” before a workflow is
created.

Compatibility is not scientific sufficiency. Sample count, class balance,
fold feasibility, residual moments, instrument applicability, and fitness for
the scientist's claim are checked by the relevant node or validation protocol.
A structurally compatible choice can still refuse when those stronger checks
fail.

## Exports and external references

Ordinary local or paid-user data can travel through the export policy allowed
by that deployment. For reference data that cannot be included, a workflow or
project export records where the original file came from and how to verify it
rather than including the measurements. On another
machine, the scientist selects or maps the independently obtained file; Sherpa
verifies it before reopening the analysis. Technical export records retain the
file size and SHA-256 checksum for exact-file checks.

See [Data Import](data-import.md) for the UI procedure and [SherpaDataset](../architecture/sherpa-dataset.md)
for the in-memory scientific contract.

