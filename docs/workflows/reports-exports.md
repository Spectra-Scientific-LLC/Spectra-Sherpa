# Reports and Exports

Reports and exports are the bridge between an interactive workflow and a reusable scientific record.

## Reports

Reports summarize a workflow run: data source, preprocessing, model outputs, plots, metrics, and narrative when AI is available in the configured environment.

If AI narrative is unavailable, the scientific outputs should still remain visible. Treat the narrative as help for interpretation, not as the only record.

## Exports

Export surfaces are intended for:

- data tables
- model outputs
- plot payloads
- workflow snapshots
- Python or notebook-style reproductions where supported

When exporting calibration or classification results, preserve sample IDs, target names, units, and metric labels. A CSV without context is rarely enough for a chemometrics handoff.
