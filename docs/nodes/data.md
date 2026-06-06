# Data Nodes

Data nodes introduce datasets into a workflow.

## Core Data Nodes

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Data Source (`data.source`) | You need an example dataset, uploaded experiment file, library entry, or direct file path. | none | `default: SpectralDataset`; `target: TargetMatrix` when available | `source`; source-specific selectors such as `example_dataset`, `sklearn_dataset`, `eigenvector_dataset`, `synthetic_dataset`, `experiment_id`, `file_id`, `stage`, `library_id`, `file_path`. |
| File Load (`data.file_load`) | You want a specific uploaded experiment file from a project dataset. | none | spectral dataset | `experiment_id`; `file_id`; `stage` such as raw or processed. |
| My Dataset (`data.my_dataset`) | You want to load all files in a saved dataset collection. | none | `default: SpectralDataset`; `target: TargetMatrix` if the dataset has targets | `dataset_id`. |
| NIST Library (`data.nist_library`) | You need reference spectra from the bundled/reference NIST library. | none | `SherpaDataset` | `library_id`; `compound_name`. |
| Load Group (`data.load_group`) | You need to stack many files from a folder into one dataset. | none | grouped spectral dataset | `folder_path`; `pattern`; `recursive`; `sort_by`; `validate_axes`; `group_title`. Requires SpectroChemPy for spectroscopy-native grouped file loading. |
| Attach Target (`data.attach_target`) | You already have spectra and a target vector or matrix and want downstream supervised nodes to see them together. | `X: SpectralDataset`; `y: TargetMatrix` | `default: SpectralDataset` with attached targets | `target_type` such as continuous or categorical. |
| Train/Test Split (`data.train_test_split`) | You need a simple train/test split before modeling or holdout evaluation. | `X: SpectralDataset`; `y: TargetMatrix?` | `X_train`; `X_test`; `y_train`; `y_test` | `test_size`; `split_method`; `random_seed`; `shuffle`. |
| Filter Samples (`data.filter_samples`) | You need to subset rows by sample label, class, target, metadata, row number, or intensity rule. | `X: SpectralDataset` | filtered `SpectralDataset` | `field`; `pattern`; `match_mode`; `case_sensitive`; `invert`; sample-table and intensity threshold settings. |

## Synthesis and Mixture Helpers

These nodes are useful for examples, simulation, and method development. They should not be mistaken for measured calibration data.

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Species (`synthesis.species`) | Mark a spectrum as a component/species before mixture generation. | `default: SpectralDataset` | spectral dataset with species metadata | `species_name`; `molar_absorptivity`. |
| Blend (`synthesis.blend`) | Create synthetic mixtures from component spectra and concentration curves. | `default: SpectralDataset` | synthetic spectral dataset | `n_timepoints`; `model_type`; `pathlength`; `noise_level`; `species_config`. |
| Merge Spectra (`synthesis.merge`) | Stack or combine spectra into one dataset. | `default: SpectralDataset` | merged spectral dataset | `align_wavenumbers`. |
| Synthetic Curve (`data.synthetic_curve`) | Generate concentration/time curves for synthetic examples. | none | synthetic curve dataset | `curve_type`; `n_points`; `max_concentration`; `center`; `width`. |
| Concentration Curve (`custom.concentration_curve`) | Generate simple concentration curves for custom blending workflows. | none | array | `curve_type`; `n_points`; `max_concentration`; `center`; `width`. |
| Catmull-Rom Curve (`custom.catmull_rom_curve`) | Generate smoother custom curves from control points. | none | array | `n_points`; `max_concentration`; `control_points`. |
| Noise Injection (`custom.noise_injection`) | Stress-test workflows with controlled synthetic noise. | `default: SpectralDataset` | spectral dataset | `noise_level`; `noise_type`; `seed`. |
| System Saturation (`custom.system_saturation`) | Simulate detector or system saturation in synthetic spectra. | `default: SpectralDataset` | spectral dataset | `s_system`; `p_system`. |
| Linear Calibration (`custom.linear_calibration`) | Simulate Beer-Lambert style response with saturation capping. | `spectrum: SpectralDataset`; `concentrations: Any` | spectral dataset | `s_max`; `concentration_unit`; `reference_confirmed`. |
| Saturation Model (`custom.saturation_model`) | Simulate nonlinear high-concentration response. | `spectrum: SpectralDataset`; `concentrations: Any` | spectral dataset | `validate_params`; `concentration_unit`; `warn_extrapolation`. |
| Hybrid Model Selector (`custom.hybrid_selector`) | Choose linear or saturation output per variable. | `linear_result`; `saturation_result`; `concentrations` | spectral dataset | `auto_select`; `saturation_threshold`. |
| Golden Grid Align (`custom.golden_grid_align`) | Align spectra to a common wavenumber grid for synthetic or imported sets. | `default: SpectralDataset` | aligned spectral dataset | `method`; `merge_tolerance`. |

## Deployment I/O Helpers

| Node | Use When | Inputs | Outputs | Key Configuration |
| --- | --- | --- | --- | --- |
| Deploy Input (`deploy.input`) | Building a headless prediction workflow that receives external data. | none | `default: SpectralDataset` | `stream_name`. |
| Deploy Output (`deploy.output`) | Formatting headless prediction results for a service response. | `default: Any` | scalar or structured response payload | `output_format`; `key_value_separator`; `end_of_message_tag`. |

## Data Checks Before Modeling

Confirm sample count, variable count, spectral axis units, sample IDs, and target alignment before connecting to supervised nodes. A model can train on row-misaligned spectra and targets, but the results are scientifically invalid.

## Import Boundary

Base file support and SpectroChemPy-backed vendor support are documented in [Supported File Types](../introduction/file-types.md). With `spectra-sherpa[scp]`, supported vendor formats include Thermo OMNIC/OMNICxi `.spa`, `.spg`, `.srs`, Bruker `.opus`, Galactic `.spc`, Renishaw `.wdf`, and vendor `.txt`/`.dat`.
