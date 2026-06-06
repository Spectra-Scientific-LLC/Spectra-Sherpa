# Output Nodes

Output nodes make workflow results visible or exportable.

## Nodes

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Plot (`output.plot`) | Show spectra, scores, loadings, diagnostics, dendrograms, or metrics-derived plots. | `default: Any` | `visualization` | `plot_type`; `colorscale`; `x_axis`; `y_axis`. Many model outputs carry plot-ready payloads. |
| Contour Plot (`output.contour`) | Show a 2D heatmap or contour view of matrix-like spectral data. | `default: Any` | `visualization` | `colorscale`; `plot_type`; `reverse_x`; `transpose`. |
| Data Table (`output.data_table`) | Inspect numeric arrays, metrics, sample tables, or selected variables as rows and columns. | `default: Any` | `visualization` | `max_rows`; `transpose`; `show_index`. |
| Statistics (`stats.summary`) | Generate adaptive summaries for datasets, model outputs, or metrics. | `default: Any` | `statistics` | `compute_outliers`; `outlier_threshold`; `max_samples`. |
| Export (`output.export`) | Export workflow output to a named file format. | `default: Any` | `file_info` | `filename`; `format`. |

## Good Output Hygiene

For chemometrics, useful output includes the numbers and the context: sample IDs, target names, units, metric names, split design, and model parameters.

## Choosing the Right Output

- Use plots for pattern recognition: spectra, scores, loadings, residual diagnostics, dendrograms, and acceptance regions.
- Use tables for auditability: sample IDs, target values, predictions, selected variables, peak lists, and metric dictionaries.
- Use statistics summaries for quick health checks, not as a substitute for validation nodes.
- Use export only after confirming the output carries labels and units needed by the recipient.
