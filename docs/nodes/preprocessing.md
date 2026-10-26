# Preprocessing Nodes

!!! abstract "Summary"
    Reference: nodes that transform spectra before modeling — scatter correction, derivatives, smoothing, baseline handling, alignment, and clipping.

Preprocessing nodes transform spectra before modeling.

Most preprocessing nodes accept a `SpectralDataset` port and return a transformed `SpectralDataset` port. At runtime, those ports carry `SherpaDataset` objects with spectral axes and processing history, so reports and exported workflows can show what happened before modeling.

## Baseline, Smoothing, and Derivatives

- [`baseline.penalized_ls`](preprocessing.md#registry-reference): Correct smooth fluorescence, scattering, or instrument baseline while preserving peaks. Larger `lam` makes a smoother baseline.
- [`baseline.rubberband`](preprocessing.md#registry-reference): You want the cited lower-convex-envelope baseline removed from every spectrum. Use Clip Range upstream to select an interval.
- [`preprocess.smooth`](preprocessing.md#registry-reference): Reduce noise before derivatives, peak finding, or visualization. For Savitzky-Golay, `size` should be odd and larger than `order`.
- [`preprocess.derivative`](preprocessing.md#registry-reference): Remove broad baseline trends or emphasize bands; common for NIR and Raman preprocessing. Derivatives amplify noise, so smooth carefully.
- [`preprocess.cosmic_ray`](preprocessing.md#registry-reference): Remove Raman spike artifacts before modeling or peak finding. Uses centered local median and MAD-style spike detection. The first and last `(window - 1) / 2` features are preserved unassessed because a complete centered neighborhood is unavailable there.

SciPy's `savgol_filter` is the underlying reference point for Savitzky-Golay concepts such as window length, polynomial order, and derivative order: <https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html>.

Rubberband baseline correction follows the spectroscopy treatment discussed by Butler et al., *Analyst* 143 (2018), DOI [10.1039/C8AN01384E](https://doi.org/10.1039/C8AN01384E). Its lower convex envelope uses Andrew's monotone-chain construction, *Information Processing Letters* 9 (1979), DOI [10.1016/0020-0190(79)90072-3](https://doi.org/10.1016/0020-0190(79)90072-3). The full connected spectral interval is used; place Clip Range upstream when only a declared interval should be corrected.

## Range, Alignment, Normalization, and Scaling

- [`preprocess.clip_range`](preprocessing.md#registry-reference): Keep a chemically relevant wavenumber range and drop unneeded variables. Check axis direction after cropping.
- [`preprocess.clip_floor`](preprocessing.md#registry-reference): Remove negative values before non-negative methods such as NMF.
- [`preprocess.wavenumber_align`](preprocessing.md#registry-reference): Align absolute-wavenumber spectra onto a common spectral grid before stacking, transfer, or comparison. Both inputs must declare absolute wavenumber in canonical `cm-1`; Raman shift is a different quantity and is refused. The connected reference supplies the exact output grid. A finer output grid is interpolation and does not add measured spectral resolution.
- [`preprocess.normalize`](preprocessing.md#registry-reference): Apply sample-local SNV or row scaling; no cohort statistics are learned.
- [`preprocess.msc`](preprocessing.md#registry-reference): Fit a reference spectrum from a declared cohort, then correct additive and multiplicative scatter with that frozen reference. Connect training/reference rows to `reference` when correcting held-out or future samples. `first` is row-order sensitive.
- [`preprocess.scale`](preprocessing.md#registry-reference): Fit mean-centering, autoscaling, or Pareto statistics before PCA, PLS, SVR, or KNN. Sample-wise maximum scaling is `preprocess.normalize` with `method=scale` and `scale_method=max`.
- [`preprocess.shared_reference_scale`](preprocessing.md#registry-reference): Fit one scale state on retained calibration rows and apply it to both branches of a fixed held-out PLS split. Connect `reference_scaled` to PLS training and `default` to its prediction node. This separate operation preserves the historical Scale / Center contract.
- [`preprocess.emsc`](preprocessing.md#registry-reference): Fit a reference spectrum and polynomial nuisance basis, then correct spectra with that frozen state. `first` means the first ordered reference row and is therefore row-order sensitive; prefer an explicit one-row reference input when that spectrum is intentional. Connect training rows to `reference` when correcting held-out or future samples; connect known interferent spectra to `constituents`.
- [`preprocess.osc`](preprocessing.md#registry-reference): Remove spectral variation orthogonal to the target before calibration. Use only inside validation folds to avoid leakage.

## Apply Frozen Preprocessing State

These application nodes replay a state fitted by the corresponding producer.
They do not refit a reference, scaling vector, constituent basis, or target-
orthogonal projection on application data.

- [`preprocess.apply_fitted_msc`](preprocessing.md#registry-reference): MSC fitted state Feature coordinates and units must match the fitted state.
- [`preprocess.apply_fitted_emsc`](preprocessing.md#registry-reference): EMSC fitted state The saved reference, polynomial basis, and optional constituents are replayed exactly.
- [`preprocess.apply_fitted_osc`](preprocessing.md#registry-reference): OSC fitted state The saved target-orthogonal projection is applied without seeing application targets.
- [`preprocess.apply_fitted_scale`](preprocessing.md#registry-reference): scaling fitted state Saved centering and scale vectors are applied without recomputing cohort statistics.

## Time-Series Helpers

- [`time_series.moving_window`](preprocessing.md#registry-reference): Analyze time-resolved spectra in rolling windows.
- [`time_series.trend_removal`](preprocessing.md#registry-reference): Remove drift from sequential spectra before PCA, monitoring, or calibration.

## Calibration Transfer

- [`transfer.pds`](preprocessing.md#registry-reference): Fit local PLS maps from paired primary/secondary standards. Unsupported local rank is rejected rather than silently reduced.
- [`transfer.sws`](preprocessing.md#registry-reference): Fit one affine secondary-to-primary relation at each wavelength from exactly paired standards. Requires identical measured spectral axes and non-constant secondary channels.
- [`transfer.ds`](preprocessing.md#registry-reference): Fit the published global Moore-Penrose secondary-to-primary spectral map. Primary and secondary feature counts may differ because the fitted matrix binds both axes.
- [`transfer.apply_fitted`](preprocessing.md#registry-reference): Apply an upstream digest-bound PDS, DS, or SWS state without refitting standards. The application axis and units must match the fitted secondary space exactly.

The Calibration Transfer Method Comparison starter splits the same paired M5/MP5 measurements by ordered
sample identity, fits all three methods on the training standards, and applies each frozen state only to the
held-out MP5 rows. It does not treat MP6 as if it came from the MP5 instrument. The displayed transfer-error
tables describe training-standard reconstruction; held-out primary-versus-standardized error remains a
separate evaluation step and is not implied by those tables.

## Notes

Preprocessing nodes in the current registry are Sherpa-native. The optional
SpectroChemPy boundary is limited to the private matrix adapter used by EFA,
MCR-ALS, and SIMPLISMA; it adds no preprocessing, reference-data, public
conversion, or file-reader authority.

EMSC is a fitted transform. Its saved state binds the reference spectrum, optional constituent spectra, feature coordinates, and units. Applying that state to a different feature axis fails rather than silently recomputing or coercing the correction. The node is available for local workbench workflows; managed-search eligibility requires a separately reviewed, bounded search envelope.

MSC is also a fitted transform. SNV and row scaling remain under `preprocess.normalize` because they are sample-local; MSC has its own operation identity because its reference must be learned from declared training/reference rows and replayed without refitting. Its saved state binds the reference method, reference spectrum, feature coordinates, and units. Managed-search eligibility requires a separately reviewed, bounded search envelope.

Wavenumber alignment records the source and reference axis quantities, whether
the reference grid is finer than the measured source grid, and the
corresponding upsampling factor. This is an interpolation-density statement
only: no interpolation method creates spectral resolution that the instrument
did not measure. When collection assembly or a common-grid operation refuses
otherwise compatible absolute-wavenumber inputs, its error names
`preprocess.wavenumber_align` as the explicit remediation rather than silently
interpolating during admission.

### Reference scaling input authority

Scaling state serializer 2 binds its means/scales to the ordered feature axis
(or tabular feature labels), signal units, declared signal quantity and
measurement mode. These checks apply to the live reference port, saved state,
generated Python, and saved-model preprocessing replay. A feature count alone
is insufficient. Reordering requires an explicit alignment before scaling.

Scaling state serializer 1 did not retain this authority and requires refitting
for current replay; its historical evidence remains unchanged. Two anonymous
arrays still support positional research, without a claim of named feature or
signal compatibility. Saved preprocessing chains preserve the live unit effects
of normalization, MSC, scaling and derivatives before checking the next fitted
operation.

Pareto scaling divides by the square root of standard deviation, so dimensional
signal units become square-root units, for example `sqrt(mg/L)`. Unknown units
remain unknown; they are not relabeled dimensionless.

### MSC reference signal authority

MSC serializer 2 retains ordered feature identity, reference signal units,
signal quantity and measurement mode. Application requires compatible authority
before correction: conversions must be explicit. MSC fits `X = b R + a` and
returns `(X-a)/b`, whose units belong to reference `R`; it does not produce a
dimensionless spectrum unless the reference is dimensionless. Unknown units
remain unknown. Live execution, generated Python and saved-model replay use
the same state. Serializer 1 lacks this evidence and requires refitting;
historical records are not silently upgraded. A `first` reference retains an
actual training spectrum, so it must not be treated as data-free state.

### Numerical inclusion and boundary safeguards

Reference fitting (including centering, autoscale, and MSC) refuses datasets
with unmaterialized sample or variable exclusions. Apply the explicit sample
and variable filters first. Autoscale and internal PCA scaling treat variation
within a column-relative floating-point resolution bound as constant, avoiding
unit-weight amplification of roundoff. Internal PLS autoscaling refuses such
columns, as it does exact constants. Meaningful low-amplitude signals near zero
remain eligible for scaling.

Norris–Williams derivatives retain zero-filled unsupported edge positions.
The second derivative has twice the first derivative's unsupported margin:
`2 * (gap + segment - 1)` points on each side. Its averaging stencils never use
artificial zeros from the first pass. Settings leaving no valid interior are
rejected.

<!-- BEGIN GENERATED NODE REFERENCE -->

<!-- NODE HELP REFERENCES {"help_reference": "docs/nodes/preprocessing.md", "node_types": ["baseline.penalized_ls", "baseline.rubberband", "preprocess.apply_fitted_emsc", "preprocess.apply_fitted_msc", "preprocess.apply_fitted_osc", "preprocess.apply_fitted_scale", "preprocess.bosch_phase_labels", "preprocess.clip_floor", "preprocess.clip_range", "preprocess.cosmic_ray", "preprocess.derivative", "preprocess.emsc", "preprocess.msc", "preprocess.normalize", "preprocess.osc", "preprocess.scale", "preprocess.shared_reference_scale", "preprocess.smooth", "preprocess.wavenumber_align", "time_series.moving_window", "time_series.trend_removal", "transfer.apply_fitted", "transfer.ds", "transfer.pds", "transfer.sws"]} -->

## Registry reference

Generated from registered node metadata. Edit methodology and examples outside the marked section.
Defaults and options below are JSON values; `null` means no concrete default is declared.
Internal parameters are retained for contract inspection and are not scientist-editable controls.
Conditional visibility describes the editor; execution admission remains node-owned.

| Node | Operation |
| --- | --- |
| Baseline (Penalized LS) | <code>baseline.penalized_ls</code> |
| Baseline (Rubberband) | <code>baseline.rubberband</code> |
| Apply Reference EMSC (Imported) | <code>preprocess.apply_fitted_emsc</code> |
| Apply Reference MSC (Imported) | <code>preprocess.apply_fitted_msc</code> |
| Apply Reference OSC (Imported) | <code>preprocess.apply_fitted_osc</code> |
| Apply Reference Scale (Imported) | <code>preprocess.apply_fitted_scale</code> |
| BOSCH Gas Phase Labels | <code>preprocess.bosch_phase_labels</code> |
| Clip Floor | <code>preprocess.clip_floor</code> |
| Clip Feature Range | <code>preprocess.clip_range</code> |
| Cosmic Ray Removal | <code>preprocess.cosmic_ray</code> |
| Derivative | <code>preprocess.derivative</code> |
| EMSC | <code>preprocess.emsc</code> |
| Multiplicative Scatter Correction (MSC) | <code>preprocess.msc</code> |
| Normalize | <code>preprocess.normalize</code> |
| Orthogonal Signal Correction | <code>preprocess.osc</code> |
| Scale / Center | <code>preprocess.scale</code> |
| Shared Reference Scale | <code>preprocess.shared_reference_scale</code> |
| Smooth | <code>preprocess.smooth</code> |
| Wavenumber Align | <code>preprocess.wavenumber_align</code> |
| Moving Window | <code>time_series.moving_window</code> |
| Trend Removal | <code>time_series.trend_removal</code> |
| Apply Fitted Spectral Transfer | <code>transfer.apply_fitted</code> |
| Direct Standardization | <code>transfer.ds</code> |
| Piecewise Direct Standardization | <code>transfer.pds</code> |
| Single-Wavelength Standardization | <code>transfer.sws</code> |

### Baseline (Penalized LS) (`baseline.penalized_ls`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>method</code> | <code>select</code> | <code>true</code> | <code>&quot;als&quot;</code> | <code>[&quot;als&quot;, &quot;arpls&quot;, &quot;airpls&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Closed penalized least-squares algorithm choice. |
| <code>lam</code> | <code>number</code> | <code>false</code> | <code>100000.0</code> | — | <code>{&quot;min_value&quot;: 100.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Exact smoothness penalty; larger values produce a smoother baseline. Hosted execution requires lambda at most 1e9. Increase by about 10× for residual baseline curvature; decrease if peaks flatten. |
| <code>p</code> | <code>number</code> | <code>false</code> | <code>0.001</code> | — | <code>{&quot;max_value&quot;: 0.9999, &quot;min_value&quot;: 0.0001, &quot;step&quot;: 0.0001}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;als&quot;]}}</code> | Exact ALS asymmetry; non-default values are rejected for ArPLS and AirPLS. Hosted execution requires ALS asymmetry at most 0.1. Keeps both ALS weight classes at or above 1e-4 so neither side of the asymmetric fit becomes numerically zero-weighted. |
| <code>max_iter</code> | <code>number</code> | <code>false</code> | <code>50</code> | — | <code>{&quot;max_value&quot;: 1000, &quot;min_value&quot;: 5, &quot;step&quot;: 5}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Hard convergence limit; non-convergence fails the node. Hosted execution admits at most 100 iterations per spectrum. Caps the number of sparse linear solves per spectrum so the node remains inside its declared local worker resource envelope. |
| <code>tol</code> | <code>number</code> | <code>false</code> | <code>1e-06</code> | — | <code>{&quot;max_value&quot;: 0.999999, &quot;min_value&quot;: 1e-10}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Finite convergence tolerance strictly between zero and one. Hosted execution requires tolerance at most 1e-2. Preserves the algorithm&#x27;s strict tolerance-below-one invariant at the six-decimal UI precision. |

### Baseline (Rubberband) (`baseline.rubberband`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

No parameters.

### Apply Reference EMSC (Imported) (`preprocess.apply_fitted_emsc`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>serializer</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_contract_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_content_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_node_id</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Apply Reference MSC (Imported) (`preprocess.apply_fitted_msc`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>serializer</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_contract_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_content_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_node_id</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Apply Reference OSC (Imported) (`preprocess.apply_fitted_osc`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>serializer</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_contract_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_content_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_node_id</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Apply Reference Scale (Imported) (`preprocess.apply_fitted_scale`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>artifact_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>serializer</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_contract_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_content_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_digest</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>state_node_id</code> | <code>text</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### BOSCH Gas Phase Labels (`preprocess.bosch_phase_labels`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>process</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_features&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

No parameters.

### Clip Floor (`preprocess.clip_floor`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>floor</code> | <code>number</code> | <code>true</code> | <code>0.0</code> | — | <code>{&quot;step&quot;: 0.001}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Exact minimum value; every smaller finite value is set to this threshold. |

### Clip Feature Range (`preprocess.clip_range`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>minimum</code> | <code>number</code> | <code>true</code> | <code>400.0</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Inclusive lower bound expressed in the input feature-axis units. |
| <code>maximum</code> | <code>number</code> | <code>true</code> | <code>4000.0</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Inclusive upper bound expressed in the input feature-axis units. |
| <code>exclude_range</code> | <code>boolean</code> | <code>true</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | When checked, remove the inclusive range and keep features outside it. |

### Cosmic Ray Removal (`preprocess.cosmic_ray`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>window</code> | <code>number</code> | <code>true</code> | <code>7</code> | — | <code>{&quot;max_value&quot;: 101, &quot;min_value&quot;: 3, &quot;step&quot;: 2}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Odd number of spectral features in each local Hampel neighborhood. The half-window at each spectrum edge is preserved unassessed. Bounds the per-spectrum neighborhood work while covering a much wider region than an isolated detector spike. |
| <code>zscore</code> | <code>number</code> | <code>true</code> | <code>3.0</code> | — | <code>{&quot;min_value&quot;: 1.5, &quot;step&quot;: 0.5}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Threshold in normal-consistent local MAD scale units. |

### Derivative (`preprocess.derivative`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>method</code> | <code>select</code> | <code>true</code> | <code>&quot;savitzky_golay&quot;</code> | <code>[{&quot;label&quot;: &quot;Savitzky-Golay&quot;, &quot;value&quot;: &quot;savitzky_golay&quot;}, {&quot;label&quot;: &quot;Norris-Williams&quot;, &quot;value&quot;: &quot;norris_williams&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Derivative algorithm |
| <code>deriv</code> | <code>select</code> | <code>true</code> | <code>&quot;1&quot;</code> | <code>[&quot;1&quot;, &quot;2&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | First or second derivative order |
| <code>size</code> | <code>number</code> | <code>false</code> | <code>11</code> | — | <code>{&quot;min_value&quot;: 3, &quot;step&quot;: 2}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;savitzky_golay&quot;]}}</code> | Odd Savitzky-Golay window size. Hosted execution admits Savitzky-Golay windows from 5 through 31 points. |
| <code>order</code> | <code>number</code> | <code>false</code> | <code>2</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;savitzky_golay&quot;]}}</code> | Savitzky-Golay polynomial order. Hosted execution admits polynomial orders from 2 through 4. |
| <code>gap</code> | <code>number</code> | <code>false</code> | <code>5</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;norris_williams&quot;]}}</code> | Norris-Williams gap size. Hosted execution admits Norris-Williams gaps from 1 through 15. |
| <code>segment</code> | <code>number</code> | <code>false</code> | <code>5</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;norris_williams&quot;]}}</code> | Norris-Williams segment size. Hosted execution admits Norris-Williams segments from 1 through 15. |

### EMSC (`preprocess.emsc`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>reference</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>false</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>constituents</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>false</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>reference_method</code> | <code>select</code> | <code>true</code> | <code>&quot;mean&quot;</code> | <code>[{&quot;label&quot;: &quot;Mean of reference rows&quot;, &quot;value&quot;: &quot;mean&quot;}, {&quot;label&quot;: &quot;Median of reference rows&quot;, &quot;value&quot;: &quot;median&quot;}, {&quot;label&quot;: &quot;First reference row (order-sensitive)&quot;, &quot;value&quot;: &quot;first&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Rule used to fit the reference spectrum. &#x27;First&#x27; means the first row of the ordered reference input and therefore changes if those rows are reordered; prefer an explicit one-row reference input when that spectrum is intentional. |
| <code>poly_order</code> | <code>number</code> | <code>true</code> | <code>2</code> | — | <code>{&quot;max_value&quot;: 5, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Polynomial nuisance order, including the constant term. Higher orders are unstable and confound spectral structure with baseline shape. |

### Multiplicative Scatter Correction (MSC) (`preprocess.msc`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>reference</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>false</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>reference_method</code> | <code>select</code> | <code>true</code> | <code>&quot;mean&quot;</code> | <code>[{&quot;label&quot;: &quot;Mean of reference rows&quot;, &quot;value&quot;: &quot;mean&quot;}, {&quot;label&quot;: &quot;Median of reference rows&quot;, &quot;value&quot;: &quot;median&quot;}, {&quot;label&quot;: &quot;First reference row (order-sensitive)&quot;, &quot;value&quot;: &quot;first&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Rule used to fit the reference spectrum. &#x27;First&#x27; is row-order sensitive; connect an explicit one-row reference when that spectrum is intentional. Hosted managed execution admits mean or median only; use mean with an explicit one-row reference to apply that exact spectrum. |

### Normalize (`preprocess.normalize`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>method</code> | <code>select</code> | <code>true</code> | <code>&quot;snv&quot;</code> | <code>[{&quot;label&quot;: &quot;SNV&quot;, &quot;value&quot;: &quot;snv&quot;}, {&quot;label&quot;: &quot;Scale&quot;, &quot;value&quot;: &quot;scale&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Normalization method |
| <code>std_ddof</code> | <code>select</code> | <code>false</code> | <code>0</code> | <code>[{&quot;label&quot;: &quot;Population (ddof=0)&quot;, &quot;value&quot;: 0}, {&quot;label&quot;: &quot;Sample (ddof=1)&quot;, &quot;value&quot;: 1}]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;snv&quot;]}}</code> | Standard-deviation convention used by SNV |
| <code>scale_method</code> | <code>select</code> | <code>false</code> | <code>&quot;max&quot;</code> | <code>[&quot;max&quot;, &quot;area&quot;, &quot;minmax&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;scale&quot;]}}</code> | Sample-wise scaling method |

### Orthogonal Signal Correction (`preprocess.osc`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>reference</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>false</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[&quot;y_continuous&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>1</code> | — | <code>{&quot;max_value&quot;: 10, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Dominant target-orthogonal spectral components to remove. Bounds SVD work and prevents an interactive correction from removing an unreviewably broad orthogonal subspace; resolved data rank imposes the tighter runtime limit. |

### Scale / Center (`preprocess.scale`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>reference</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>false</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>method</code> | <code>select</code> | <code>true</code> | <code>&quot;mean_center&quot;</code> | <code>[{&quot;label&quot;: &quot;Mean Center&quot;, &quot;value&quot;: &quot;mean_center&quot;}, {&quot;label&quot;: &quot;Autoscale&quot;, &quot;value&quot;: &quot;autoscale&quot;}, {&quot;label&quot;: &quot;Pareto&quot;, &quot;value&quot;: &quot;pareto&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Reference-fitted scaling method. |
| <code>center</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;autoscale&quot;, &quot;pareto&quot;]}}</code> | Subtract the fitted reference mean before autoscaling or Pareto scaling. |

### Shared Reference Scale (`preprocess.shared_reference_scale`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| input | <code>reference</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |
| output | <code>reference_scaled</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;, &quot;X_features&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>method</code> | <code>select</code> | <code>true</code> | <code>&quot;mean_center&quot;</code> | <code>[{&quot;label&quot;: &quot;Mean Center&quot;, &quot;value&quot;: &quot;mean_center&quot;}, {&quot;label&quot;: &quot;Autoscale&quot;, &quot;value&quot;: &quot;autoscale&quot;}, {&quot;label&quot;: &quot;Pareto&quot;, &quot;value&quot;: &quot;pareto&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Reference-fitted scaling method. |
| <code>center</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;autoscale&quot;, &quot;pareto&quot;]}}</code> | Subtract the fitted reference mean before autoscaling or Pareto scaling. |

### Smooth (`preprocess.smooth`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>method</code> | <code>select</code> | <code>true</code> | <code>&quot;savitzky_golay&quot;</code> | <code>[{&quot;label&quot;: &quot;Savitzky-Golay&quot;, &quot;value&quot;: &quot;savitzky_golay&quot;}, {&quot;label&quot;: &quot;Whittaker&quot;, &quot;value&quot;: &quot;whittaker&quot;}, {&quot;label&quot;: &quot;Gaussian&quot;, &quot;value&quot;: &quot;gaussian&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Smoothing algorithm |
| <code>size</code> | <code>number</code> | <code>true</code> | <code>11</code> | — | <code>{&quot;min_value&quot;: 3, &quot;step&quot;: 2}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;savitzky_golay&quot;]}}</code> | Odd Savitzky-Golay window size |
| <code>order</code> | <code>number</code> | <code>true</code> | <code>2</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;savitzky_golay&quot;]}}</code> | Savitzky-Golay polynomial order |
| <code>lam</code> | <code>number</code> | <code>true</code> | <code>100.0</code> | — | <code>{&quot;min_value&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;whittaker&quot;]}}</code> | Whittaker smoothness penalty |
| <code>d</code> | <code>select</code> | <code>true</code> | <code>&quot;2&quot;</code> | <code>[&quot;1&quot;, &quot;2&quot;, &quot;3&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;whittaker&quot;]}}</code> | Whittaker difference order |
| <code>sigma</code> | <code>number</code> | <code>true</code> | <code>2.0</code> | — | <code>{&quot;min_value&quot;: 0.1, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;method&quot;: [&quot;gaussian&quot;]}}</code> | Gaussian kernel width |

### Wavenumber Align (`preprocess.wavenumber_align`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>spectra</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>reference</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>method</code> | <code>select</code> | <code>true</code> | <code>&quot;pchip&quot;</code> | <code>[&quot;pchip&quot;, &quot;linear&quot;, &quot;sinc&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Exact interpolation rule; sinc requires a uniform source grid. Upsampling never implies additional measured resolution. |
| <code>extrapolation</code> | <code>select</code> | <code>true</code> | <code>&quot;reject&quot;</code> | <code>[&quot;reject&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Fail when the reference grid extends beyond measured source coverage. |

### Moving Window (`time_series.moving_window`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>window_size</code> | <code>number</code> | <code>true</code> | <code>10</code> | — | <code>{&quot;max_value&quot;: 100000, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of consecutive spectra in each window Bounds window metadata and worker memory on local batch analyses. |
| <code>step_size</code> | <code>number</code> | <code>true</code> | <code>1</code> | — | <code>{&quot;max_value&quot;: 100000, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of spectra to move between windows (1=maximum overlap) Bounds window traversal and worker memory on local batch analyses. |
| <code>aggregation</code> | <code>select</code> | <code>false</code> | <code>&quot;none&quot;</code> | <code>[&quot;none&quot;, &quot;mean&quot;, &quot;median&quot;, &quot;std&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | How to aggregate spectra within each window |

### Trend Removal (`time_series.trend_removal`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>method</code> | <code>select</code> | <code>true</code> | <code>&quot;linear&quot;</code> | <code>[&quot;linear&quot;, &quot;polynomial&quot;, &quot;difference&quot;, &quot;moving_average&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Method for trend removal |
| <code>poly_order</code> | <code>number</code> | <code>false</code> | <code>2</code> | — | <code>{&quot;max_value&quot;: 10, &quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Polynomial order (for polynomial method) Bounds polynomial conditioning and local worker cost. |
| <code>window_size</code> | <code>number</code> | <code>false</code> | <code>5</code> | — | <code>{&quot;max_value&quot;: 100000, &quot;min_value&quot;: 2, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Window size for moving average baseline Bounds moving-average worker memory and makes the admitted domain explicit. |

### Apply Fitted Spectral Transfer (`transfer.apply_fitted`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>fitted_state</code> | <code>spectrasherpa://types/SpectralTransferModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

No parameters.

### Direct Standardization (`transfer.ds`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X_primary</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>X_secondary</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>X_standardized</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/SpectralTransferModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>transfer_error</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

No parameters.

### Piecewise Direct Standardization (`transfer.pds`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X_primary</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>X_secondary</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>X_standardized</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/SpectralTransferModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>transfer_error</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>half_window</code> | <code>number</code> | <code>true</code> | <code>3</code> | — | <code>{&quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Secondary channels on either side of each primary wavelength. |
| <code>n_components</code> | <code>number</code> | <code>true</code> | <code>2</code> | — | <code>{&quot;min_value&quot;: 1, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Exact local PLS rank; unsupported ranks are rejected rather than truncated. |

### Single-Wavelength Standardization (`transfer.sws`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X_primary</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>X_secondary</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>X_standardized</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>fitted_state</code> | <code>spectrasherpa://types/SpectralTransferModel/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>transfer_error</code> | <code>spectrasherpa://types/ValidationResult/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

No parameters.

<!-- END GENERATED NODE REFERENCE -->
