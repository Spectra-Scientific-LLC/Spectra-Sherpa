# Reports and Exports

Reports and exports are the bridge between an interactive workflow and a reusable scientific record.

The application follows one computation lifecycle: **Workflows** define and
execute the complete computation; **Runs** preserve its records; **Optimize**
searches for better computations; **Deploy** applies a fitted workflow to new
data; **Report** presents what a saved run already produced. Report is not a
second model-fitting or validation engine. Pages may perform basic descriptive
arithmetic on complete retained populations, including means, ratios and sample
standard deviations; they must not calculate these from truncated previews.

!!! note "Junior-user note"
    A report is strongest when it answers: what data entered, what operations
    ran, what population was evaluated, what the metrics mean, and what remains
    uncertain. Read the saved workflow and run identity before treating a
    narrative paragraph as a conclusion.

## Reports

Reports summarize a workflow run: data source, preprocessing, model outputs, plots, metrics, and narrative when AI is available in the configured environment.

If AI narrative is unavailable, the scientific outputs should still remain visible. Treat the narrative as help for interpretation, not as the only record.

### Short summary (default)

Shared units appear once in Result / context: the input spectral axis (such as
wavelength in nm), spectral intensity when recorded, and each response Y unit
(also used by predictions). Matching response units are omitted from population
tables and row-list notes. Mixed or missing units retain explicit population
labels. Spectral units come from retained source metadata, not assumed defaults;
this source declaration does not override units changed by preprocessing.

The Report page defaults to **Short summary**, a deterministic,
non-AI view available without a subscription. It selects retained key results:

Both report lengths have a one-line description in the same location. The
summary excludes nested provenance, target-authority and annotation records;
their repeated unit fields are retained in Detailed report and full evidence,
not presented as separate scientific results.

- Population and method context: samples, variables, components, targets and units.
- Regression: R², RMSE/RMSEC/RMSECV/RMSEP, Q², bias and other retained error diagnostics, with their recorded scope.
- PCA/decomposition: explained variance and component count; MCR-ALS fit, iterations and convergence when retained.
- Classification: accuracy, balanced accuracy, macro F1 and retained class-specific performance, preserving training/CV/test labels.
- Clustering and library matching: cluster count/silhouette or best match/HQI when present; similarity alone is not identification certainty.

The summary does not recompute missing model/validation metrics, infer external validation,
pool repeat populations or rank incompatible runs. Run failures and retained
evidence limitations remain visible. Numeric result tables round non-integer
metrics to four significant figures; counts remain exact.

Canonical regression nodes compute per-target statistics during workflow
execution. Reports display those retained statistics with separate calibration,
cross-validation and evaluation rows: sample count, reference range and standard
deviation, R², RMSE, bias (prediction minus reference), bias-corrected SEP,
slope and intercept. Sample-level comparison rows do not become repeated target
headings. Missing canonical statistics in older runs require a workflow rerun;
opening or exporting a report never backfills them.

Reference mean is summarized from the complete retained comparison population.
The opening context distinguishes fitted latent components from cross-validation
folds: explained X/Y variance entry `[k]` is the incremental fraction explained
by component k, not a fold score. Saved requested/effective component counts and
recorded CV settings are shown without inferring CV-based component selection.

Enable **Include complete target lists and node plots** to include all
retained reference/prediction rows separately for each population, in either
report mode. The 20-row saved-history preview is explicitly labeled and never
used as the full population. Lists are limited to 5,000 rows per population;
larger lists are refused explicitly, not silently truncated. Comparison labels
may be population row positions rather than original specimen IDs. These lists
are excluded from the optional AI narrative payload.

The same option includes available saved-run plot types, organized into sections
by node, in both Short summary and Detailed report. Each figure has its own title;
node headings are visually distinct in HTML/PDF and hierarchical in Markdown.
The report uses the same scientific presentation definitions as Quick Plot and
Runs, including available input/preprocessed comparisons, scores, loadings,
explained variance and regression plots. It uses default displayed component
axes, not every possible component-pair permutation. Display sampling disclosures
from those views remain attached to the figures.

Plots are embedded locally without rerunning the workflow or using today's
canvas. Missing outputs, unsupported views and rendering failures appear under
the affected node. Capture reads at most 32 MiB of retained outputs and renders
at most 200 images per run; limits produce explicit notices, not silent omissions.
Plot images are excluded from the AI narrative payload. After changing the
checkbox, click **Generate Report** to load the requested figures.

Calibration RMSE is not degrees-of-freedom-adjusted SEC. A compact table alone
does not establish ASTM E1655 compliance, reference-method precision, replicate
weighting or independence of validation specimens.

Choose **Detailed report** for all retained quantities, settings, diagnostics
and optional row-level figures. PDF, HTML and Markdown follow the selected
report length; **JSON Data (full evidence)** retains the complete report payload.
**AI Summary** is a separate, optional subscription feature and starts off.

!!! note "Junior-user note"
    High calibration R² does not demonstrate predictive performance. Read the
    population and validation scope alongside every error metric. Cross-validation
    is not an external test, and an absent quantity does not mean zero.

## Validation evidence in reports

Saved-run reports use retained execution evidence rather than current editor
state. When available, a validation summary includes the evaluated population,
target identity and units; preprocessing, selector, component, group, fold and
repeat choices; exclusions and the metric denominator; per-repeat metrics and
spread; and the interpretation limits for calibration, cross-validation,
held-out, external or application results.

Grouped nested validation retains complete group membership at both levels.
Repeated validation retains one evidence record per repeat and must not be
flattened into one larger sample count. Recorded specimen or batch identity
comparisons are reported separately from operator-declared independence.

Row-level reference, prediction and residual values, together with prediction
versus reference and residual figures, require explicit export consent. Consent
is reset when the workflow changes, and these figures are never included in an
AI narrative payload. Figures are generated from exact retained evidence; for
more than 5,000 rows the report keeps numeric evidence and states that the
figure is unavailable instead of silently subsampling. Markdown exports use
inline SVG, so viewers that suppress SVG should use the HTML export.

Campaign verification remains data-free: it can preserve development,
selection and confirmation history, but row-level plots require local
reproduction with the bound dataset. Package integrity, publisher
authentication, validation reproduction and fitted-application reproduction
are separate outcomes and must not be collapsed into a generic `verified`
label.

## Exports

Export surfaces are intended for:

- data tables
- model outputs
- plot payloads
- workflow snapshots
- Python or notebook-style reproductions where supported

When exporting calibration or classification results, preserve sample IDs, target names, units, and metric labels. A CSV without context is rarely enough for a chemometrics handoff.

The same scope applies to Python, notebook, HTML, Markdown and JSON exports.
If a value, unit, split, figure or population was unavailable in the retained
run, the export records that limitation rather than resolving it from today's
defaults or the open workflow editor.
