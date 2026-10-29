# Projects, Datasets, and Runs

!!! abstract "Summary"
    How work is organized: a project holds datasets, workflows, and runs; a run is one executed workflow with everything recorded. Includes batch execution and how the pieces fit together.

SpectraSherpa organizes work around projects.

## Project

A Project is the user workspace grouping datasets, workflows, Runs, reports,
and Models. **Dashboard > New Analysis** creates a project; **Analysis Starter**
inside Workflow adds a workflow template to the current project. Use one project
for one study, method-development effort, or demo evaluation. An Experiment is
an internal import/source container for files, specimens, metadata, and versions.
It can belong to a Project; it is not another name for the Project workspace.

Dashboard Starter suggests **Data — Model — Purpose — Version**, for example
**Lavender FTIR — PCA — Exploration — v1** or **Corn — PLS — Regression — v1**.
For preprocessing or other starters without a named model, the model part is omitted.
You can edit it before choosing **Ready to Start**. The `v1` suffix is a naming
aid, not a scientific revision or a claim about saved results.

Starter opens the next relevant page without importing data or adding a template
automatically. On Import, review the suggested dataset and choose **Add to My
Dataset**. On Workflow, choose **Analysis Starter**, then the suggested template.
Where hosted Guidance is available and enabled, its task-specific buttons point
to these same controls; they do not perform the import or run an analysis.

## Dataset

A dataset is a named selection of data, views, target, and optional groups that
workflows consume. For spectra, the core shape is usually samples by spectral
variables. Metadata records the source, file list, units, and other context when available.

### Portfolio

A portfolio is a saved, named analysis selection within a source dataset. It
retains file/result selection, target and grouping choices, and reviewed sample
corrections where applicable, without replacing the source measurements. Use
**Save portfolio** in My Dataset and **Show** to restore one. Several portfolios
can support different studies of the same source; workflow sheets bind an exact
selection rather than whatever happens to be plotted now. See
[Build a portfolio](data-import.md#build-a-portfolio-in-my-dataset).

### Acquisition plan

[Multi-well](multi-well.md) records intended samples, mixtures, factors, wells,
acquisition order and matching rules for a dataset. A plan is not measured data:
review and publish a proposed measured-sample table separately before using
its metadata in analysis.

The **Data Portfolio** name appears above My Dataset, on the workflow sheet,
and in Analysis Starter while templates are offered. A saved portfolio carries
its selected source stage (raw, synthetic, or preprocessed), files, response,
and grouping. Choosing **Show** restores that definition; it does not silently
turn a synthetic or preprocessed selection into raw data.

## Workflow

A workflow is a directed graph of nodes. Data nodes feed preprocessing nodes, model nodes, validation nodes, plots, tables, reports, and exports.

Workbook tabs show interactive analysis workflows. Some calibration starters
also retain a `managed_candidate_authority` record: the exact baseline recipe
used by managed Harness search and admission. Previously this appeared as a
"Harness-only" tab even in Local OSS, although ordinary execution was blocked.
It is now excluded from workbook tabs and sheet ordering by its purpose. The
record remains available for managed operations and project preservation;
scientific calibration, preprocessing, and validation sheets remain usable.

## Run

A run is one execution of a workflow. Open **Runs** to review saved executions.
Results are the outputs and diagnostics produced by nodes within a run.

### Comparing scientific results

Compare aligns measures within their recorded evaluation role: calibration,
training cross-validation, or held-out validation. Evaluator node names do not
define the role. A paired difference requires matching sample identity,
response, units, and evaluation conditions; equal values or row counts are not
proof that two populations match.

**Recorded node measures** preserves producer-specific values separately,
including equal values from different nodes, without implying a paired ranking.
Older runs without retained typed sample IDs remain inspectable but cannot
establish a matching population from their display labels. Regression tables
retain original sample names in the actual evaluation order; names are separate
from the typed sample IDs used for scientific matching.

## Models and artifacts

Use **Models** for the user-facing collection of retained fitted models.
Artifact describes the underlying fitted-state record.

Training nodes can persist fitted models. A model artifact keeps a readable compatibility record plus the numeric fitted state needed for later review and application. Before applying an artifact, confirm the spectral axis, preprocessing, feature count, target units, and validation context match the new data.
## Batch execution

**Apply trained model** uses the fitted model and preprocessing without refitting
on the included dataset. Accuracy statistics require reference targets.
**Run workflow** executes the saved graph with the selected dataset; its split,
training, and evaluation nodes determine the statistics. The original canvas
and fitted models are unchanged. Review the selected combinations before starting.

Each batch combination is saved separately in Run History with a shared batch
identifier. Compare dataset-level statistics there; execution mode and cohort
labels describe the evidence, rather than restricting which runs can be compared.
## Availability lights

Green means the item is present, grey means absent or not checked, and red
indicates an operational problem. These lights describe basic availability,
not model quality, deployment qualification or completeness of scientific
provenance. Open the evidence record for its current detail and timestamp.
