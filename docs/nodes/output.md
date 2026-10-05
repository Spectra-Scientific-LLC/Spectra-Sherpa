# Output Nodes

Output nodes make workflow results visible or exportable.

## Nodes

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Plot (`output.plot`) | Show spectra, scores, loadings, diagnostics, dendrograms, or metrics-derived plots. | `default: Any` | `visualization` | `plot_type`; `colorscale`; `x_axis`; `y_axis`. Many model outputs carry plot-ready payloads. |
| Contour Plot (`output.contour`) | Show a 2D heatmap or contour view of matrix-like spectral data. | `default: Any` | `visualization` | `colorscale`; `plot_type`; `reverse_x`; `transpose`. |
| Data Table (`output.data_table`) | Inspect numeric arrays, metrics, sample tables, or selected variables as rows and columns. | `default: Any` | `visualization` | `max_rows`; `transpose`; `show_index`. |
| Statistics (`stats.summary`) | Generate deterministic descriptive summaries for datasets and typed scientific results. Inferential decisions remain in dedicated diagnostic nodes. | `default: Any` | `statistics: StatisticsSummary` | `max_samples`. |
| Prepare Export (`output.export`) | Prepare exact, verified bytes for a scientist-controlled download or generated-script materialization. | `data: Array2D/1.0` | `artifact: ExportArtifact/1.0` | Safe basename `filename`; closed `format` (`csv`, `json`, or `jdx`). |

## Good Output Hygiene

All plot, table, statistics, and export surfaces are governed by the
[Scientific Result Surface Contract](../developers/scientific-result-surface-contract.md).
It defines the required authority, population and transformation disclosures,
lifecycle behavior, refusal states, and acceptance cases. A successful render
or download alone does not establish scientific fidelity.

For chemometrics, useful output includes the numbers and the context: sample IDs, target names, units, metric names, split design, and model parameters.

## Choosing the Right Output

- Use plots for pattern recognition: spectra, scores, loadings, residual diagnostics, dendrograms, and acceptance regions.
- Use tables for auditability: sample IDs, target values, predictions, selected variables, peak lists, and metric dictionaries.
- Use statistics summaries for quick health checks, not as a substitute for validation nodes.
- Use export only after confirming the dataset carries the sample and feature
  labels, units, and role needed by the recipient. CSV and JSON preserve the
  complete two-dimensional dataset. JCAMP-DX is admitted only for one spectrum
  with a measured numeric feature axis and declared units; the node refuses to
  invent a wavelength axis, spectral units, or a multi-spectrum JCAMP dialect.
- The DAG node prepares a closed artifact containing the filename, format,
  media type, exact content, byte length, source digest, and content digest. It
  never chooses or writes a filesystem path. The workbench download and the
  generated-script host independently verify that contract before handing the
  exact bytes to their host. The generated-script materializer additionally
  refuses to overwrite an existing destination.

## Saved model handoff

A reusable fitted model must appear in Runs → Artifacts with its source run and
be available to local Deploy after execution. Cohort-only clustering remains
inspectable but does not predict new observations. See the [canonical artifact
acceptance contract](../developers/scientific-result-surface-contract.md#canonical-node-artifact-acceptance).
