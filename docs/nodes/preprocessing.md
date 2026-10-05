# Preprocessing Nodes

Preprocessing nodes transform spectra before modeling.

Most preprocessing nodes accept a `SpectralDataset` port and return a transformed `SpectralDataset` port. At runtime, those ports carry `SherpaDataset` objects with spectral axes and processing history, so reports and exported workflows can show what happened before modeling.

## Baseline, Smoothing, and Derivatives

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Baseline Penalized LS (`baseline.penalized_ls`) | Correct smooth fluorescence, scattering, or instrument baseline while preserving peaks. | `default: SpectralDataset` | corrected spectral dataset | `method` (`als`, `arpls`, `airpls`); `lam`; `p`; `max_iter`; `tol`. Larger `lam` makes a smoother baseline. |
| Baseline Rubberband (`baseline.rubberband`) | You want the cited lower-convex-envelope baseline removed from every spectrum. Use Clip Range upstream to select an interval. | `default: SpectralDataset` | corrected spectral dataset | Sherpa-native; no parameters. |
| Smooth (`preprocess.smooth`) | Reduce noise before derivatives, peak finding, or visualization. | `default: SpectralDataset` | smoothed spectral dataset | `method` (`savitzky_golay`, `whittaker`, `gaussian`); `size`; `order`; `lam`; `d`; `sigma`. For Savitzky-Golay, `size` should be odd and larger than `order`. |
| Derivative (`preprocess.derivative`) | Remove broad baseline trends or emphasize bands; common for NIR and Raman preprocessing. | `default: SpectralDataset` | derivative spectral dataset | `method` (`savitzky_golay`, `norris_williams`); `deriv`; `size`; `order`; `gap`; `segment`. Derivatives amplify noise, so smooth carefully. |
| Cosmic Ray Removal (`preprocess.cosmic_ray`) | Remove Raman spike artifacts before modeling or peak finding. | `default: SpectralDataset` | cleaned spectral dataset | `window`; `zscore`. Uses centered local median and MAD-style spike detection. The first and last `(window - 1) / 2` features are preserved unassessed because a complete centered neighborhood is unavailable there. |

SciPy's `savgol_filter` is the underlying reference point for Savitzky-Golay concepts such as window length, polynomial order, and derivative order: <https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html>.

Rubberband baseline correction follows the spectroscopy treatment discussed by Butler et al., *Analyst* 143 (2018), DOI [10.1039/C8AN01384E](https://doi.org/10.1039/C8AN01384E). Its lower convex envelope uses Andrew's monotone-chain construction, *Information Processing Letters* 9 (1979), DOI [10.1016/0020-0190(79)90072-3](https://doi.org/10.1016/0020-0190(79)90072-3). The full connected spectral interval is used; place Clip Range upstream when only a declared interval should be corrected.

## Range, Alignment, Normalization, and Scaling

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Clip Range (`preprocess.clip_range`) | Keep a chemically relevant wavenumber range and drop unneeded variables. | `default: SpectralDataset` | cropped spectral dataset | `min_wavenumber`; `max_wavenumber`. Check axis direction after cropping. |
| Clip Floor (`preprocess.clip_floor`) | Remove negative values before non-negative methods such as NMF. | `default: SpectralDataset` | clipped spectral dataset | `floor`. |
| Wavenumber Align (`preprocess.wavenumber_align`) | Align absolute-wavenumber spectra onto a common spectral grid before stacking, transfer, or comparison. | `spectra: SpectralDataset`; `reference: SpectralDataset` | aligned spectral dataset | `method` (`pchip`, `linear`, or `sinc`); fixed `extrapolation=reject`. Both inputs must declare absolute wavenumber in canonical `cm-1`; Raman shift is a different quantity and is refused. The connected reference supplies the exact output grid. A finer output grid is interpolation and does not add measured spectral resolution. |
| Normalize (`preprocess.normalize`) | Apply sample-local SNV or row scaling; no cohort statistics are learned. | `default: SpectralDataset` | normalized spectral dataset | `method` (`snv`, `scale`); `std_ddof`; `scale_method`. |
| MSC (`preprocess.msc`) | Fit a reference spectrum from a declared cohort, then correct additive and multiplicative scatter with that frozen reference. | `default: SpectralDataset`; `reference: SpectralDataset?` | corrected spectral dataset | `reference_method` (`mean`, `median`, `first`). Connect training/reference rows to `reference` when correcting held-out or future samples. `first` is row-order sensitive. |
| Scale / Center (`preprocess.scale`) | Fit mean-centering, autoscaling, or Pareto statistics before PCA, PLS, SVR, or KNN. | `default: SpectralDataset`; `reference: SpectralDataset?` | scaled spectral dataset | `method` (`mean_center`, `autoscale`, `pareto`); `center`. Connect training rows to `reference` when transforming held-out or future samples. Sample-wise maximum scaling is `preprocess.normalize` with `method=scale` and `scale_method=max`. |
| EMSC (`preprocess.emsc`) | Fit a reference spectrum and polynomial nuisance basis, then correct spectra with that frozen state. | `default: SpectralDataset`; `reference: SpectralDataset?`; `constituents: SpectralDataset?` | corrected spectral dataset | `reference_method` (`mean`, `median`, `first`); `poly_order` (0–5). `first` means the first ordered reference row and is therefore row-order sensitive; prefer an explicit one-row reference input when that spectrum is intentional. Connect training rows to `reference` when correcting held-out or future samples; connect known interferent spectra to `constituents`. |
| OSC Filter (`preprocess.osc`) | Remove spectral variation orthogonal to the target before calibration. | `X: SpectralDataset`; `y: TargetMatrix?` | filtered spectral dataset | `n_components`; `tol`; `max_iter`. Use only inside validation folds to avoid leakage. |

## Apply Frozen Preprocessing State

These application nodes replay a state fitted by the corresponding producer.
They do not refit a reference, scaling vector, constituent basis, or target-
orthogonal projection on application data.

| Node | Accepted State | Output | Key Rule |
| --- | --- | --- | --- |
| Apply Fitted MSC (`preprocess.apply_fitted_msc`) | MSC fitted state | corrected spectral dataset | Feature coordinates and units must match the fitted state. |
| Apply Fitted EMSC (`preprocess.apply_fitted_emsc`) | EMSC fitted state | corrected spectral dataset | The saved reference, polynomial basis, and optional constituents are replayed exactly. |
| Apply Fitted OSC (`preprocess.apply_fitted_osc`) | OSC fitted state | filtered spectral dataset | The saved target-orthogonal projection is applied without seeing application targets. |
| Apply Fitted Scale (`preprocess.apply_fitted_scale`) | scaling fitted state | scaled spectral dataset | Saved centering and scale vectors are applied without recomputing cohort statistics. |

## Time-Series Helpers

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Moving Window (`time_series.moving_window`) | Analyze time-resolved spectra in rolling windows. | `default: SpectralDataset` | windowed spectral dataset | `window_size`; `step_size`; `aggregation`. |
| Trend Removal (`time_series.trend_removal`) | Remove drift from sequential spectra before PCA, monitoring, or calibration. | `default: SpectralDataset` | detrended spectral dataset | `method`; `poly_order`; `window_size`. |

## Calibration Transfer

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| PDS Transfer (`transfer.pds`) | Fit local PLS maps from paired primary/secondary standards. | `X_primary`; `X_secondary` | standardized secondary standards; `fitted_state`; `transfer_error` | `half_window`; `n_components`. Unsupported local rank is rejected rather than silently reduced. |
| Single-Wavelength Standardization (`transfer.sws`) | Fit one affine secondary-to-primary relation at each wavelength from exactly paired standards. | `X_primary`; `X_secondary` | standardized secondary standards; `fitted_state`; `transfer_error` | No parameters. Requires identical measured spectral axes and non-constant secondary channels. |
| Direct Standardization (`transfer.ds`) | Fit the published global Moore-Penrose secondary-to-primary spectral map. | `X_primary`; `X_secondary` | standardized secondary standards; `fitted_state`; `transfer_error` | No parameters. Primary and secondary feature counts may differ because the fitted matrix binds both axes. |
| Apply Fitted Spectral Transfer (`transfer.apply_fitted`) | Apply an upstream digest-bound PDS, DS, or SWS state without refitting standards. | `default`; `fitted_state` | `default` | No parameters. The application axis and units must match the fitted secondary space exactly. |

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
