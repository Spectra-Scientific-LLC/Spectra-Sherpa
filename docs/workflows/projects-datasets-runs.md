# Projects, Datasets, and Runs

SpectraSherpa organizes work around projects.

## Project

A project groups datasets, workflows, runs, reports, and model artifacts. Use one project for one study, method-development effort, or demo evaluation.

## Dataset

A dataset is the data object that workflows consume. For spectra, the core shape is usually samples by spectral variables. Metadata records the source, file list, units, and other context when available.

## Workflow

A workflow is a directed graph of nodes. Data nodes feed preprocessing nodes, model nodes, validation nodes, plots, tables, reports, and exports.

## Run

A run is one execution of a workflow. It captures the outputs and diagnostics produced by the nodes at that point in time.

## Model Artifact

Training nodes can persist fitted models. A model artifact keeps a readable compatibility record plus the numeric fitted state needed for later review and application. Before applying an artifact, confirm the spectral axis, preprocessing, feature count, target units, and validation context match the new data.
