# Data Nodes

## `data.collection_load`

Loads the exact project-owned collection members selected in **My Dataset**.
The saved node records the selected file identities plus source-manifest,
collection-definition, and scientific-collection digests. At execution Sherpa
re-admits those members and refuses missing, added, changed, or out-of-scope
sources. An explicitly selected sample-table target and validation group are
bound without adding metadata columns to the predictor matrix.

Data nodes introduce datasets into a workflow.

## Core Data Nodes

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| File Load (`data.file_load`) | You want one exact authorized experiment file, including an explicit target when supervised analysis needs one. | none | `default: SpectralDataset`; `target: TargetMatrix` when selected | `experiment_id`; `file_id`; `stage`; optional exact `selected_target` and `target_type`. |
| NIST Library (`data.nist_library`) | You need one exact local NIST reference spectrum. | none | `SpectralDataset` | Exact `library_id`. The node requires a supported spectral technique, monotonic axis, units, and binds the JCAMP bytes by SHA-256. |
| Load Group (`data.load_group`) | You need to stack many compatible files from a folder into one dataset. | none | grouped spectral dataset | `folder_path`; `pattern`; `recursive`; deterministic `sort_by`; `group_title`. Uses the native ingestion registry. Axes and signal units must match; exact source bytes are bound by a manifest digest. |
| Attach Target (`data.attach_target`) | You want downstream supervised nodes to use either a connected target or one exact aligned sample-table column. A separate metadata column may define validation groups without entering `X`. | `X: SpectralDataset`; optional `y: TargetMatrix` | `default: SpectralDataset` with attached targets | Choose `target_source`, `target_type`, and, for sample-table supervision, exact `target_column` plus optional `group_column`. |
| Train/Test Split (`data.train_test_split`) | You need one digest-bound statistical or chemometric calibration/test design. Bound validation groups are held out whole. | `X: SpectralDataset`; `y: TargetMatrix?` | `X_train`; `X_test`; `y_train`; `y_test`; exact membership indices | `test_size`; `split_method` (`random`, `stratified`, `sequential`, `group_holdout`, `kennard_stone`, `duplex`, or `spxy`); method-specific bounded settings. Grouped input is supported by random, stratified, sequential, and group holdout methods; observation-level space-filling methods refuse it. |

Grouped stratification first selects a class-complete `StratifiedGroupKFold`
candidate closest to the requested sample count, then class proportions. If
no candidate exists and every group has exactly one class, it constructs a
seeded class-stratified holdout of `ceil(test_size * group_count)` groups.
Every class must retain at least one independent group on each side. Remaining
test groups are allocated by the largest deficit from the requested per-class
group count, with stable class-order tie breaking. This fallback balances
independent groups, not replicate counts; unequal group sizes can change the
actual sample fraction. Exact membership and realized counts are retained.
Neither route uses spectra or model performance to choose membership. Failure
to find a class-complete split is reported without reverting to row splitting.

Named group holdout (`group_holdout`) is the external-validation design: the
scientist names the exact values of the bound grouping column that form the
test partition (`held_out_groups`, e.g. `MP5`), and every other group pools
into training. This answers "pilot lots against a production lot" or "one
instrument against a specific new instrument" directly, following
Leave-P-Groups-Out semantics. The grouping column is validation context only
and never enters `X`. The method is deterministic: it admits no test fraction,
seed, or distance setting, and it refuses a selection that is empty, names an
unknown group (the error lists the valid groups), names one twice, or leaves
no group in training.
| Filter Samples (`data.filter_samples`) | You need to subset rows by sample label, class, target, metadata, row number, or intensity rule. | `X: SpectralDataset` | filtered `SpectralDataset` | Guided mode selection; row ranges; populated value lists; intensity metric, operator, and threshold; optional advanced pattern controls. |

### Filter Samples

Filter Samples keeps or removes rows from a connected dataset before modeling, plotting, export, or report generation. The workflow inspector reads the connected dataset and exposes the practical choices first:

- **By index** for row ranges such as `1-10, 15`.
- **By name** when sample labels are available.
- **By class** when class labels are available.
- **By target** when target values are attached.
- **By metadata** when sample-table columns are available.
- **By intensity** for simple row-wise spectral rules such as maximum intensity above a threshold.

The panel previews how many samples will be kept before the workflow is run. Advanced settings remain available for regular-expression matching, inverted selection, case sensitivity, and allowing an intentionally empty result.

## Synthesis and Mixture Helpers

These nodes are useful for examples, simulation, and method development. They should not be mistaken for measured calibration data.

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| PPM to Fraction (`synthesis.ppm_fraction`) | Convert declared non-negative ppm concentrations into the dimensionless mole fractions required by the bilinear mixture. | `default: TargetMatrix` | dimensionless `TargetMatrix` | No parameters; the exact scale factor is `10^-6`. |
| NIST Quant IR Response (`synthesis.nist_quant_ir_response`) | Convert one NIST quantitative-IR coefficient in `ppm^-1 m^-1` into a unit-mole-fraction decadic response. | `default: SpectralDataset` | unit-fraction response | Strictly positive `pathlength_cm`. |
| HITRAN Cross-section Response (`synthesis.hitran_response`) | Convert one HITRAN cross section in `cm^2 molecule^-1` into a unit-mole-fraction decadic response. | `default: SpectralDataset` | unit-fraction response | Strictly positive `pathlength_cm`, `temperature_k`, and `pressure_atm`. |
| Species (`synthesis.species`) | Mark a spectrum as a component/species before mixture generation. | `default: SpectralDataset` | spectral dataset with species metadata | `species_name`; `molar_absorptivity`. |
| Merge Spectra (`synthesis.merge`) | Stack exactly aligned, species-labelled pure responses into the response matrix `S`. | variadic `default: SpectralDataset` | pure-response `SpectralDataset` | No parameters; alignment must be an explicit upstream operation. |
| Blend (`synthesis.blend`) | Evaluate the standard bilinear mixture `D = C @ S`. | `pure_spectra: SpectralDataset`; `concentrations: TargetMatrix` | synthetic spectral dataset retaining exact `C` and `S` factors | No parameters; noise and nonlinear response are separate explicit nodes. |
| Synthetic Curve (`data.synthetic_curve`) | Generate deterministic concentration/time curves for synthetic examples. | none | `TimeSeries` | `curve_type`; `n_points`; `max_concentration`; `center`; `width`; physical `duration_seconds`. |
| Concentration Curve (`custom.concentration_curve`) | Generate simple concentration curves for custom blending workflows. | none | array | `curve_type`; `n_points`; `max_concentration`; `center`; `width`. |
| Catmull-Rom Curve (`custom.catmull_rom_curve`) | Generate smoother custom curves from control points. | none | array | `n_points`; `max_concentration`; `control_points`. |
| Noise Injection (`custom.noise_injection`) | Stress-test workflows with reproducible independent Gaussian noise. | `default: SpectralDataset` | spectral dataset | `noise_level`; `noise_type` (`absolute` or `relative_rms`); required `seed`. |
| System Saturation (`custom.system_saturation`) | Simulate detector or system saturation in synthetic spectra. | `default: SpectralDataset` | spectral dataset | `s_system`; `p_system`. |
| Linear Calibration (`custom.linear_calibration`) | Apply an explicit affine Beer-Lambert calibration without inferred coefficients. | `spectrum: SpectralDataset`; `concentrations: TargetMatrix` | spectral dataset | `concentration_unit`; input metadata must carry the matching slope, intercept, and applied-reference status. |
| Saturation Model (`custom.saturation_model`) | Simulate nonlinear high-concentration response. | `spectrum: SpectralDataset`; `concentrations: Any` | spectral dataset | `validate_params`; `concentration_unit`; `warn_extrapolation`. |
| Hybrid Model Selector (`custom.hybrid_selector`) | Choose linear or saturation output per variable. | `linear_result`; `saturation_result`; `concentrations` | spectral dataset | `auto_select`; `saturation_threshold`. |
| Golden Grid Align (`custom.golden_grid_align`) | Align and stack spectra on measured coordinates within every input's common wavenumber coverage. Extrapolation is rejected, and denser interpolation is admitted explicitly without claiming added measured resolution. | variadic `default: SpectralDataset` | one aligned and stacked `SpectralDataset` | `method`; `merge_tolerance`; `coverage_policy=common_overlap`; `extrapolation=reject`; `max_upsampling_factor`. |

### Scientific references for reference-response synthesis

- Ppm quantity and unit semantics follow the IUPAC Green Book, 3rd edition, DOI `10.1039/9781847557889`.
- Decadic absorbance scaling follows the IUPAC Beer–Lambert definition, DOI `10.1351/goldbook.B00626`.
- HITRAN cross sections and line parameters follow Gordon et al., *The HITRAN2020 molecular spectroscopic database*, DOI `10.1016/j.jqsrt.2021.107949`.
- NIST coefficient provenance follows the NIST Chemistry WebBook Quantitative Infrared Database. The node accepts only the database's declared `ppm^-1 m^-1` coefficient convention.
- The bilinear mixture follows de Juan and Tauler, *Multivariate Curve Resolution (MCR) from 2000*, DOI `10.1080/10408340600970005`.

These operations expose only the referenced equations and exact unit conversions. A different physical model, interpolation, response correction, or decision rule requires a separate cited canonical operation; it is never hidden in the application synthesis service.

## Deployment I/O Helpers

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Deploy Input (`deploy.input`) | Building a headless prediction workflow that receives external data. | none | `default: SpectralDataset` | `stream_name`. |
| Deploy Output (`deploy.output`) | Formatting headless prediction results for a service response. | `default: Any` | scalar or structured response payload | `output_format`; `key_value_separator`; `end_of_message_tag`. |

## Data Checks Before Modeling

Confirm sample count, variable count, spectral axis units, sample IDs, and target alignment before connecting to supervised nodes. A model can train on row-misaligned spectra and targets, but the results are scientifically invalid.

## Import Boundary

Current native file support and pending vendor readers are documented in [Supported File Types](../introduction/file-types.md). Installing `spectra-sherpa[scp]` enables three specialized algorithms, not additional file readers.

Reference examples are imported through Analysis Starter into an exact project file before a canonical workflow is created. Eigenvector Research raw files are not redistributed in the OSS wheel; the reference-dataset manifest records their acquisition and attribution.
