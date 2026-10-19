# Projects, Datasets, and Runs

SpectraSherpa organizes work around projects.

## Project

A Project is the user workspace grouping datasets, workflows, Runs, reports,
and Models. **Dashboard > New Analysis** creates a project; **Analysis Starter**
inside Workflow adds a workflow template to the current project. Use one project
for one study, method-development effort, or demo evaluation. An Experiment is
an internal import/source container for files, specimens, metadata, and versions.
It can belong to a Project; it is not another name for the Project workspace.

## Dataset

A dataset is a named selection of data, views, target, and optional groups that
workflows consume. For spectra, the core shape is usually samples by spectral
variables. Metadata records the source, file list, units, and other context when available.

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
