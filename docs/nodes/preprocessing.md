# Preprocessing Nodes

Preprocessing nodes transform spectra before modeling.

Most preprocessing nodes accept a `SpectralDataset` port and return a transformed `SpectralDataset` port. At runtime, those ports carry `SherpaDataset` objects with spectral axes and processing history, so reports and exported workflows can show what happened before modeling.

## Baseline, Smoothing, and Derivatives

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Baseline Penalized LS (`baseline.penalized_ls`) | Correct smooth fluorescence, scattering, or instrument baseline while preserving peaks. | `default: SpectralDataset` | corrected spectral dataset | `method` (`als`, `arpls`, `airpls`); `lam`; `p`; `max_iter`; `tol`. Larger `lam` makes a smoother baseline. |
| Baseline Rubberband (`baseline.rubberband`) | You want convex-hull style baseline correction over selected spectral ranges. | `default: SpectralDataset` | corrected spectral dataset | `ranges`. Requires SpectroChemPy. |
| Smooth (`preprocess.smooth`) | Reduce noise before derivatives, peak finding, or visualization. | `default: SpectralDataset` | smoothed spectral dataset | `method` (`savitzky_golay`, `whittaker`, `gaussian`); `size`; `order`; `lam`; `d`; `sigma`. For Savitzky-Golay, `size` should be odd and larger than `order`. |
| Derivative (`preprocess.derivative`) | Remove broad baseline trends or emphasize bands; common for NIR and Raman preprocessing. | `default: SpectralDataset` | derivative spectral dataset | `method` (`savitzky_golay`, `norris_williams`); `deriv`; `size`; `order`; `gap`; `segment`. Derivatives amplify noise, so smooth carefully. |
| Cosmic Ray Removal (`preprocess.cosmic_ray`) | Remove Raman spike artifacts before modeling or peak finding. | `default: SpectralDataset` | cleaned spectral dataset | `window`; `zscore`. Uses local median and MAD-style spike detection. |

SciPy's `savgol_filter` is the underlying reference point for Savitzky-Golay concepts such as window length, polynomial order, and derivative order: <https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html>.

## Range, Alignment, Normalization, and Scaling

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Clip Range (`preprocess.clip_range`) | Keep a chemically relevant wavenumber range and drop unneeded variables. | `default: SpectralDataset` | cropped spectral dataset | `min_wavenumber`; `max_wavenumber`. Check axis direction after cropping. |
| Clip Floor (`preprocess.clip_floor`) | Remove negative values before non-negative methods such as NMF. | `default: SpectralDataset` | clipped spectral dataset | `floor`. |
| Wavenumber Align (`preprocess.wavenumber_align`) | Align spectra onto a common spectral grid before stacking, transfer, or comparison. | `default: SpectralDataset` | aligned spectral dataset | `method` such as `pchip`; `merge_tolerance`. |
| Normalize (`preprocess.normalize`) | Normalize each spectrum for scatter, pathlength, or scale differences. | `default: Array2D` | normalized spectral dataset | `method` (`snv`, `msc`, `scale`); `reference`; `scale_method`. |
| Scale / Center (`preprocess.scale`) | Mean-center, autoscale, Pareto-scale, or max-scale before PCA, PLS, SVR, or KNN. | `default: Array2D`; `reference: Array2D?` | scaled spectral dataset | `method`; `center`; `target_max`. Use a training reference when applying preprocessing consistently to new data. |
| EMSC (`preprocess.emsc`) | Correct scatter and baseline with a polynomial model and optional constituent spectra. | `default: SpectralDataset`; `constituents: SpectralDataset?` | corrected spectral dataset | `reference`; `poly_order`. |
| OSC Filter (`preprocess.osc`) | Remove spectral variation orthogonal to the target before calibration. | `X: SpectralDataset`; `y: TargetMatrix?` | filtered spectral dataset | `n_components`; `tol`; `max_iter`. Requires SpectroChemPy. Use only inside validation folds to avoid leakage. |

## Time-Series Helpers

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Moving Window (`time_series.moving_window`) | Analyze time-resolved spectra in rolling windows. | `default: SpectralDataset` | windowed spectral dataset | `window_size`; `step_size`; `aggregation`. |
| Trend Removal (`time_series.trend_removal`) | Remove drift from sequential spectra before PCA, monitoring, or calibration. | `default: SpectralDataset` | detrended spectral dataset | `method`; `poly_order`; `window_size`. |

## Calibration Transfer

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| PDS Transfer (`transfer.pds`) | Standardize spectra from a secondary instrument to a primary/master instrument using local windows. | `X_primary`; `X_secondary`; `X_new` | `X_standardized`; `transfer_error` | `half_window`; `n_components`. Best when paired primary/secondary transfer standards are available. |
| SBC / DS Transfer (`transfer.sbc`) | Apply global slope/bias correction or direct standardization for instrument transfer. | `X_primary`; `X_secondary`; `X_new` | `X_standardized`; `transfer_error` | `method`; `regularization`. Simpler than PDS, but less local. |

## Notes

Some preprocessing methods are base-install implementations. Some rely on SpectroChemPy for coordinate-aware spectroscopy routines. When a node or file reader depends on SpectroChemPy, install `spectra-sherpa[scp]`.
