# Data Nodes

!!! abstract "Summary"
    Reference: nodes that bring data into a workflow — loading datasets, files, and references, and splitting samples into calibration and test sets.

## `data.collection_load`

Loads the exact project-owned collection members selected in **My Dataset**.
The saved node records the selected file identities plus source-manifest,
collection-definition, and scientific-collection digests. At execution Sherpa
re-admits those members and refuses missing, added, changed, or out-of-scope
sources. An explicitly selected sample-table target and validation group are
bound without adding metadata columns to the predictor matrix.

Data nodes introduce datasets into a workflow.

## Core Data Nodes

- [`data.file_load`](data.md#registry-reference): You want one exact authorized experiment file, including an explicit target when supervised analysis needs one.
- [`data.nist_library`](data.md#registry-reference): You need one exact local NIST reference spectrum. The node requires a supported spectral technique, monotonic axis, units, and binds the JCAMP bytes by SHA-256.
- [`data.load_group`](data.md#registry-reference): You need to stack many compatible files from a folder into one dataset. Uses the native ingestion registry. Axes and signal units must match; exact source bytes are bound by a manifest digest.
- [`data.attach_target`](data.md#registry-reference): You want downstream supervised nodes to use either a connected target or one exact aligned sample-table column. A separate metadata column may define validation groups without entering `X`. For sample-table supervision, choose an exact target column; a separate group column can define validation groups without entering the predictor matrix.
- [`data.train_test_split`](data.md#registry-reference): You need one digest-bound statistical or chemometric calibration/test design. Bound validation groups are held out whole. Grouped input is supported by random, stratified, sequential, and group holdout methods; observation-level space-filling methods refuse it.

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

Before planning, Train/Test Split materializes the input's declared sample
inclusion. Excluded rows never enter either partition. Targets, sample IDs,
labels and group annotations follow the same row selection; the original
dataset is unchanged. Connected response identities are checked before
selection. `train_indices` and `test_indices` identify original input rows;
the retained split plan indexes the compact active population used for planning.
Feature exclusions must be materialized separately before this row operation.

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

- [`data.filter_samples`](data.md#registry-reference): You need to subset rows by sample label, class, target, metadata, row number, or intensity rule. Guided mode selection supports row ranges, populated value lists, intensity rules, and advanced pattern controls.

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

- [`synthesis.ppm_fraction`](data.md#registry-reference): Convert declared non-negative ppm concentrations into the dimensionless mole fractions required by the bilinear mixture. The exact scale factor is `10^-6`.
- [`synthesis.nist_quant_ir_response`](data.md#registry-reference): Convert one NIST quantitative-IR coefficient in `ppm^-1 m^-1` into a unit-mole-fraction decadic response. The optical path length must be strictly positive.
- [`synthesis.hitran_response`](data.md#registry-reference): Convert one HITRAN cross section in `cm^2 molecule^-1` into a unit-mole-fraction decadic response. Optical path length, absolute temperature, and pressure must be strictly positive.
- [`synthesis.species`](data.md#registry-reference): Mark a spectrum as a component/species before mixture generation.
- [`synthesis.merge`](data.md#registry-reference): Stack exactly aligned, species-labelled pure responses into the response matrix `S`. Alignment must be an explicit upstream operation.
- [`synthesis.blend`](data.md#registry-reference): Evaluate the standard bilinear mixture `D = C @ S`. Retains the exact concentration and pure-response factors; noise and nonlinear response are separate explicit nodes.
- [`data.synthetic_curve`](data.md#registry-reference): Generate deterministic concentration/time curves for synthetic examples. Specify a physical duration in seconds.
- [`custom.concentration_curve`](data.md#registry-reference): Generate simple concentration curves for custom blending workflows.
- [`custom.catmull_rom_curve`](data.md#registry-reference): Generate smoother custom curves from control points.
- [`custom.noise_injection`](data.md#registry-reference): Stress-test workflows with reproducible independent Gaussian noise. Retain the seed to reproduce the perturbation.
- [`custom.system_saturation`](data.md#registry-reference): Simulate detector or system saturation in synthetic spectra.
- [`custom.linear_calibration`](data.md#registry-reference): Apply an explicit affine Beer-Lambert calibration without inferred coefficients. Input metadata must carry the matching slope, intercept, and applied-reference status for the declared concentration unit.
- [`custom.saturation_model`](data.md#registry-reference): Simulate nonlinear high-concentration response.
- [`custom.hybrid_selector`](data.md#registry-reference): Choose linear or saturation output per variable.
- [`custom.golden_grid_align`](data.md#registry-reference): Align and stack spectra on measured coordinates within every input's common wavenumber coverage. Extrapolation is rejected, and denser interpolation is admitted explicitly without claiming added measured resolution. Use only common measured coverage, reject extrapolation, and explicitly admit any denser interpolation.

### Scientific references for reference-response synthesis

- Ppm quantity and unit semantics follow the IUPAC Green Book, 3rd edition, DOI `10.1039/9781847557889`.
- Decadic absorbance scaling follows the IUPAC Beer–Lambert definition, DOI `10.1351/goldbook.B00626`.
- HITRAN cross sections and line parameters follow Gordon et al., *The HITRAN2020 molecular spectroscopic database*, DOI `10.1016/j.jqsrt.2021.107949`.
- NIST coefficient provenance follows the NIST Chemistry WebBook Quantitative Infrared Database. The node accepts only the database's declared `ppm^-1 m^-1` coefficient convention.
- The bilinear mixture follows de Juan and Tauler, *Multivariate Curve Resolution (MCR) from 2000*, DOI `10.1080/10408340600970005`.

These operations expose only the referenced equations and exact unit conversions. A different physical model, interpolation, response correction, or decision rule requires a separate cited canonical operation; it is never hidden in the application synthesis service.

## Deployment I/O Helpers

- [`deploy.input`](data.md#registry-reference): Building a headless prediction workflow that receives external data.
- [`deploy.output`](data.md#registry-reference): Formatting headless prediction results for a service response.

## Data Checks Before Modeling

Confirm sample count, variable count, spectral axis units, sample IDs, and target alignment before connecting to supervised nodes. A model can train on row-misaligned spectra and targets, but the results are scientifically invalid.

## Import Boundary

Current native file support and pending vendor readers are documented in [Supported File Types](../introduction/file-types.md). Installing `spectra-sherpa[scp]` enables three specialized algorithms, not additional file readers.

Reference examples are imported through Analysis Starter into an exact project file before a canonical workflow is created. Eigenvector Research raw files are not redistributed in the OSS wheel; the reference-dataset manifest records their acquisition and attribution.

<!-- BEGIN GENERATED NODE REFERENCE -->

<!-- NODE HELP REFERENCES {"help_reference": "docs/nodes/data.md", "node_types": ["analysis.partitioned_peaks", "custom.catmull_rom_curve", "custom.concentration_curve", "custom.golden_grid_align", "custom.hybrid_selector", "custom.linear_calibration", "custom.noise_injection", "custom.saturation_model", "custom.system_saturation", "data.attach_target", "data.collection_load", "data.file_load", "data.filter_samples", "data.load_group", "data.nist_library", "data.portfolio_load", "data.synthetic_curve", "data.train_test_split", "data.wide_peak_table", "deploy.input", "deploy.output", "output.peak_csv", "preprocess.portfolio_average", "synthesis.blend", "synthesis.hitran_response", "synthesis.merge", "synthesis.nist_quant_ir_response", "synthesis.ppm_fraction", "synthesis.species"]} -->

## Registry reference

Generated from registered node metadata. Edit methodology and examples outside the marked section.
Defaults and options below are JSON values; `null` means no concrete default is declared.
Internal parameters are retained for contract inspection and are not scientist-editable controls.
Conditional visibility describes the editor; execution admission remains node-owned.

| Node | Operation |
| --- | --- |
| Find peaks · Partitioned | <code>analysis.partitioned_peaks</code> |
| Catmull-Rom Curve | <code>custom.catmull_rom_curve</code> |
| Concentration Curve | <code>custom.concentration_curve</code> |
| Golden Grid Align | <code>custom.golden_grid_align</code> |
| Explicit Hybrid Composition | <code>custom.hybrid_selector</code> |
| Linear Calibration | <code>custom.linear_calibration</code> |
| Noise Injection | <code>custom.noise_injection</code> |
| Saturation Model | <code>custom.saturation_model</code> |
| System Saturation | <code>custom.system_saturation</code> |
| Attach Target | <code>data.attach_target</code> |
| Collection Load | <code>data.collection_load</code> |
| File Load | <code>data.file_load</code> |
| Filter Samples | <code>data.filter_samples</code> |
| Load Group | <code>data.load_group</code> |
| NIST Library | <code>data.nist_library</code> |
| Load Data · Portfolio | <code>data.portfolio_load</code> |
| Synthetic Curve | <code>data.synthetic_curve</code> |
| Train/Test Split | <code>data.train_test_split</code> |
| Combine peak columns | <code>data.wide_peak_table</code> |
| Deploy Input | <code>deploy.input</code> |
| Deploy Output | <code>deploy.output</code> |
| Export wide peak CSV | <code>output.peak_csv</code> |
| Average · Portfolio | <code>preprocess.portfolio_average</code> |
| Bilinear Mixture | <code>synthesis.blend</code> |
| HITRAN Cross-section Response | <code>synthesis.hitran_response</code> |
| Merge Pure Responses | <code>synthesis.merge</code> |
| NIST Quant IR Response | <code>synthesis.nist_quant_ir_response</code> |
| PPM to Fraction | <code>synthesis.ppm_fraction</code> |
| Species | <code>synthesis.species</code> |

### Find peaks · Partitioned (`analysis.partitioned_peaks`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>per_spectrum</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>height</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum peak height in response units. Blank passes height=None (no height filter). |
| <code>threshold</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum vertical distance to neighbors in response units. Blank passes threshold=None. |
| <code>distance</code> | <code>number</code> | <code>false</code> | <code>10</code> | — | <code>{&quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum horizontal distance in sample points (default 10). Blank or 0 passes distance=None (disabled); otherwise must be &gt;= 1. |
| <code>prominence</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum prominence in response units. Blank passes prominence=None (no prominence filter). |
| <code>width</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Minimum width at half prominence in sample points. Blank or 0 passes width=None (no width filter). |
| <code>consensus_tolerance</code> | <code>number</code> | <code>true</code> | <code>0.0</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Maximum span of one cross-sample consensus bin in feature-axis units; enter 0 to group only identical positions. Required; not a SciPy find_peaks argument. |
| <code>reference_positions</code> | <code>string_list</code> | <code>false</code> | <code>[]</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>matching_tolerance</code> | <code>number</code> | <code>true</code> | <code>0.5</code> | — | <code>{&quot;min_value&quot;: 0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |

### Catmull-Rom Curve (`custom.catmull_rom_curve`)

#### Ports

No input ports (source node).

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| output | <code>default</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>n_points</code> | <code>number</code> | <code>true</code> | <code>100</code> | — | <code>{&quot;max_value&quot;: 100000, &quot;min_value&quot;: 10}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of points in the output curve Bounds interactive curve evaluation and serialized output size. |
| <code>max_concentration</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Scale factor for output concentrations |
| <code>control_points</code> | <code>json</code> | <code>true</code> | <code>[]</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | List of {x, y} control points (x: 0-100, y: 0-1) |

### Concentration Curve (`custom.concentration_curve`)

#### Ports

No input ports (source node).

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| output | <code>default</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>curve_type</code> | <code>select</code> | <code>true</code> | <code>&quot;sigmoid&quot;</code> | <code>[&quot;sigmoid&quot;, &quot;gaussian&quot;, &quot;linear&quot;, &quot;exponential&quot;, &quot;step&quot;, &quot;constant&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Type of concentration profile |
| <code>n_points</code> | <code>number</code> | <code>true</code> | <code>100</code> | — | <code>{&quot;max_value&quot;: 100000, &quot;min_value&quot;: 10}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of time points Bounds interactive curve evaluation and serialized output size. |
| <code>max_concentration</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Maximum concentration value |
| <code>center</code> | <code>number</code> | <code>true</code> | <code>0.5</code> | — | <code>{&quot;max_value&quot;: 1.0, &quot;min_value&quot;: 0.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Center position for sigmoid/gaussian (0-1) The center is expressed on the normalized zero-to-one time axis. |
| <code>width</code> | <code>number</code> | <code>true</code> | <code>0.1</code> | — | <code>{&quot;max_value&quot;: 1.0, &quot;min_value&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Width parameter for sigmoid/gaussian The width is expressed as a fraction of the normalized time span. |

### Golden Grid Align (`custom.golden_grid_align`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>true</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>method</code> | <code>select</code> | <code>true</code> | <code>&quot;pchip&quot;</code> | <code>[&quot;pchip&quot;, &quot;linear&quot;, &quot;sinc&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Interpolation method for resampling |
| <code>merge_tolerance</code> | <code>number</code> | <code>true</code> | <code>0.05</code> | — | <code>{&quot;min_value&quot;: 0.001}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Tolerance for merging near-duplicate wavenumbers |
| <code>coverage_policy</code> | <code>select</code> | <code>true</code> | <code>&quot;common_overlap&quot;</code> | <code>[&quot;common_overlap&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Use only the spectral interval measured by every connected input. |
| <code>extrapolation</code> | <code>select</code> | <code>true</code> | <code>&quot;reject&quot;</code> | <code>[&quot;reject&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Reject any operation that would fabricate signal outside measured coverage. |
| <code>max_upsampling_factor</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 1.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Largest explicitly admitted interpolation-density increase relative to any input. Increasing it does not add measured spectral resolution. |

### Explicit Hybrid Composition (`custom.hybrid_selector`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>linear_result</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>saturation_result</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>model_mask</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

No parameters.

### Linear Calibration (`custom.linear_calibration`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>spectrum</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>concentrations</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>concentration_unit</code> | <code>select</code> | <code>true</code> | <code>&quot;ppm&quot;</code> | <code>[{&quot;label&quot;: &quot;ppm (parts per million)&quot;, &quot;value&quot;: &quot;ppm&quot;}, {&quot;label&quot;: &quot;ppmv (by volume, gas)&quot;, &quot;value&quot;: &quot;ppmv&quot;}, {&quot;label&quot;: &quot;mol/L (molar)&quot;, &quot;value&quot;: &quot;mol/L&quot;}, {&quot;label&quot;: &quot;mg/L&quot;, &quot;value&quot;: &quot;mg/L&quot;}, {&quot;label&quot;: &quot;wt% (weight percent)&quot;, &quot;value&quot;: &quot;wt%&quot;}, {&quot;label&quot;: &quot;vol% (volume percent)&quot;, &quot;value&quot;: &quot;vol%&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Unit of the input concentrations; must exactly match calibration metadata |

### Noise Injection (`custom.noise_injection`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>noise_level</code> | <code>number</code> | <code>true</code> | <code>0.01</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.001}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Absolute standard deviation or a fraction of the input RMS |
| <code>noise_type</code> | <code>select</code> | <code>true</code> | <code>&quot;relative_rms&quot;</code> | <code>[&quot;absolute&quot;, &quot;relative_rms&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Interpret noise_level as an absolute standard deviation or as a fraction of RMS |
| <code>seed</code> | <code>number</code> | <code>true</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Required invocation-local random seed NumPy Generator seeds are bounded to the portable unsigned 32-bit domain. |

### Saturation Model (`custom.saturation_model`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>sensitivity</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>saturation_levels</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>shape_exponents</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>concentrations</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>calibration_minimum</code> | <code>spectrasherpa://types/Scalar/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>calibration_maximum</code> | <code>spectrasherpa://types/Scalar/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>concentration_unit</code> | <code>select</code> | <code>true</code> | <code>&quot;ppm&quot;</code> | <code>[{&quot;label&quot;: &quot;ppm (parts per million)&quot;, &quot;value&quot;: &quot;ppm&quot;}, {&quot;label&quot;: &quot;ppmv (by volume, gas)&quot;, &quot;value&quot;: &quot;ppmv&quot;}, {&quot;label&quot;: &quot;mol/L (molar)&quot;, &quot;value&quot;: &quot;mol/L&quot;}, {&quot;label&quot;: &quot;mg/L&quot;, &quot;value&quot;: &quot;mg/L&quot;}, {&quot;label&quot;: &quot;wt% (weight percent)&quot;, &quot;value&quot;: &quot;wt%&quot;}, {&quot;label&quot;: &quot;vol% (volume percent)&quot;, &quot;value&quot;: &quot;vol%&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Unit shared by sensitivity coefficients, concentrations, and calibration bounds |

### System Saturation (`custom.system_saturation`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>s_system</code> | <code>number</code> | <code>true</code> | <code>2.0</code> | — | <code>{&quot;min_value&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Maximum absorbance the detector can measure |
| <code>p_system</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Shape exponent controlling transition sharpness |

### Attach Target (`data.attach_target`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| input | <code>sample_table</code> | <code>spectrasherpa://types/SampleTable/2.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>target_source</code> | <code>select</code> | <code>true</code> | <code>&quot;connected_target&quot;</code> | <code>[{&quot;label&quot;: &quot;Connected Target&quot;, &quot;value&quot;: &quot;connected_target&quot;}, {&quot;label&quot;: &quot;Sample Table Column&quot;, &quot;value&quot;: &quot;sample_table_column&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Use a connected target or explicitly select an aligned sample-table column |
| <code>target_type</code> | <code>select</code> | <code>true</code> | <code>&quot;continuous&quot;</code> | <code>[&quot;continuous&quot;, &quot;categorical&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Type of target variable |
| <code>target_column</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Exact sample-table column used when Target Source is Sample Table Column |
| <code>group_column</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Optional aligned grouping context; never appended to X or used as a predictor |
| <code>target_authority</code> | <code>json</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Collection Load (`data.collection_load`)

#### Ports

No input ports (source node).

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>target</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>experiment_id</code> | <code>number</code> | <code>true</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>stage</code> | <code>select</code> | <code>true</code> | <code>&quot;raw&quot;</code> | <code>[&quot;raw&quot;, &quot;preprocessed&quot;, &quot;synthetic&quot;]</code> | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>group_title</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>asset_id</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>selected_file_ids</code> | <code>string_list</code> | <code>true</code> | <code>[]</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>source_manifest_sha256</code> | <code>text</code> | <code>true</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>collection_definition_sha256</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>scientific_collection_sha256</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>target_authority</code> | <code>json</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>group_column</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>dataset_view_id</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |
| <code>dataset_view_sha256</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### File Load (`data.file_load`)

#### Ports

No input ports (source node).

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>target</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>sample_table</code> | <code>spectrasherpa://types/SampleTable/2.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>experiment_id</code> | <code>number</code> | <code>true</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Experiment containing the file |
| <code>file_id</code> | <code>number</code> | <code>true</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Specific file to load |
| <code>stage</code> | <code>select</code> | <code>false</code> | <code>&quot;raw&quot;</code> | <code>[&quot;raw&quot;, &quot;preprocessed&quot;, &quot;synthetic&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Data processing stage |
| <code>asset_id</code> | <code>text</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Exact named result inside a multi-asset source, such as OPUS absorbance &#x27;a&#x27;; single-asset files do not require it |
| <code>target_authority</code> | <code>json</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Exact response column, type, units, and source identity |

### Filter Samples (`data.filter_samples`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>field</code> | <code>select</code> | <code>true</code> | <code>&quot;sample_label&quot;</code> | <code>[{&quot;label&quot;: &quot;Sample Label&quot;, &quot;value&quot;: &quot;sample_label&quot;}, {&quot;label&quot;: &quot;Sample Class&quot;, &quot;value&quot;: &quot;sample_class&quot;}, {&quot;label&quot;: &quot;Sample Table&quot;, &quot;value&quot;: &quot;sample_table&quot;}, {&quot;label&quot;: &quot;Sample Index&quot;, &quot;value&quot;: &quot;sample_index&quot;}, {&quot;label&quot;: &quot;Source Inclusion&quot;, &quot;value&quot;: &quot;source_inclusion&quot;}, {&quot;label&quot;: &quot;Intensity&quot;, &quot;value&quot;: &quot;intensity&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Sample metadata field used to select rows. Hosted execution excludes sample-index ranges. |
| <code>pattern</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Text, comma-separated values, or regular expression to match. Hosted managed execution admits at most 4096 UTF-8 bytes; exact-value lists admit at most 1024 items and 4096 bytes. |
| <code>match_mode</code> | <code>select</code> | <code>true</code> | <code>&quot;contains&quot;</code> | <code>[{&quot;label&quot;: &quot;Contains&quot;, &quot;value&quot;: &quot;contains&quot;}, {&quot;label&quot;: &quot;Equals&quot;, &quot;value&quot;: &quot;equals&quot;}, {&quot;label&quot;: &quot;In List&quot;, &quot;value&quot;: &quot;in_list&quot;}, {&quot;label&quot;: &quot;Regex&quot;, &quot;value&quot;: &quot;regex&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | How the pattern is matched against each sample. Hosted managed execution excludes regex. |
| <code>case_sensitive</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Require exact letter case when matching text |
| <code>invert</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Keep samples that do not match the filter |
| <code>sample_table_column</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;field&quot;: [&quot;sample_table&quot;]}}</code> | Metadata column to use when Filter Field is sample_table |
| <code>intensity_metric</code> | <code>select</code> | <code>false</code> | <code>&quot;max&quot;</code> | <code>[{&quot;label&quot;: &quot;Mean Intensity&quot;, &quot;value&quot;: &quot;mean&quot;}, {&quot;label&quot;: &quot;Max Intensity&quot;, &quot;value&quot;: &quot;max&quot;}, {&quot;label&quot;: &quot;Min Intensity&quot;, &quot;value&quot;: &quot;min&quot;}, {&quot;label&quot;: &quot;Any Point&quot;, &quot;value&quot;: &quot;any&quot;}, {&quot;label&quot;: &quot;All Points&quot;, &quot;value&quot;: &quot;all&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;field&quot;: [&quot;intensity&quot;]}}</code> | How each sample spectrum is summarized for intensity filtering |
| <code>intensity_operator</code> | <code>select</code> | <code>false</code> | <code>&quot;gte&quot;</code> | <code>[{&quot;label&quot;: &quot;Greater Than&quot;, &quot;value&quot;: &quot;gt&quot;}, {&quot;label&quot;: &quot;Greater Than or Equal&quot;, &quot;value&quot;: &quot;gte&quot;}, {&quot;label&quot;: &quot;Less Than&quot;, &quot;value&quot;: &quot;lt&quot;}, {&quot;label&quot;: &quot;Less Than or Equal&quot;, &quot;value&quot;: &quot;lte&quot;}, {&quot;label&quot;: &quot;Equal&quot;, &quot;value&quot;: &quot;eq&quot;}, {&quot;label&quot;: &quot;Not Equal&quot;, &quot;value&quot;: &quot;neq&quot;}, {&quot;label&quot;: &quot;Between&quot;, &quot;value&quot;: &quot;between&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;field&quot;: [&quot;intensity&quot;]}}</code> | Numeric comparison used for intensity filtering |
| <code>intensity_threshold</code> | <code>number</code> | <code>false</code> | <code>0.0</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;field&quot;: [&quot;intensity&quot;]}}</code> | Numeric threshold for intensity filtering |
| <code>intensity_upper_threshold</code> | <code>number</code> | <code>false</code> | <code>1.0</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;field&quot;: [&quot;intensity&quot;]}}</code> | Upper threshold used by the Between operator |
| <code>allow_empty</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Allow a zero-sample result. Hosted managed execution requires this option to remain off. |
| <code>filter_values</code> | <code>string_list</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Exact UI-selected labels, classes, or metadata values; null uses the text rule |

### Load Group (`data.load_group`)

#### Ports

No input ports (source node).

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>source_mode</code> | <code>select</code> | <code>false</code> | <code>&quot;local_folder&quot;</code> | <code>[&quot;local_folder&quot;, &quot;experiment_collection&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Use a local folder or an exact project-owned experiment collection |
| <code>collection_definition_sha256</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Exact scientist-definition digest, empty only when no definition is attached |
| <code>scientific_collection_sha256</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Combined exact source and scientist-definition identity |
| <code>folder_path</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Absolute local path; used only in local-folder mode |
| <code>pattern</code> | <code>text</code> | <code>false</code> | <code>&quot;*.csv&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Glob pattern for native files (e.g., &#x27;*.csv&#x27;, &#x27;*.jdx&#x27;, &#x27;*.npz&#x27;, or &#x27;*.mat&#x27;) |
| <code>recursive</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Scan subdirectories recursively |
| <code>sort_by</code> | <code>select</code> | <code>false</code> | <code>&quot;filename&quot;</code> | <code>[&quot;filename&quot;, &quot;numeric_suffix&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | How to order files before concatenation (filename=alphabetical, numeric_suffix=extract numbers from filename) |
| <code>group_title</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Title for the grouped dataset (auto-generated from folder name if empty) |
| <code>asset_id</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Exact asset identity to select from every file. Required for multi-asset formats; the same identity is applied to all group members. |
| <code>experiment_id</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Project experiment identity; used only in experiment-collection mode |
| <code>stage</code> | <code>select</code> | <code>false</code> | <code>&quot;raw&quot;</code> | <code>[&quot;raw&quot;, &quot;preprocessed&quot;, &quot;synthetic&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Exact persisted experiment stage |
| <code>source_manifest_sha256</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | Exact ordered collection digest recorded when the workflow is authored |

### NIST Library (`data.nist_library`)

#### Ports

No input ports (source node).

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>library_id</code> | <code>number</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | ID of the NIST library entry |

### Load Data · Portfolio (`data.portfolio_load`)

#### Ports

No input ports (source node).

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| output | <code>default</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>project_id</code> | <code>number</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>portfolio_id</code> | <code>number</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>selection_sha256</code> | <code>text</code> | <code>true</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |

### Synthetic Curve (`data.synthetic_curve`)

#### Ports

No input ports (source node).

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| output | <code>default</code> | <code>spectrasherpa://types/TimeSeries/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>curve_type</code> | <code>select</code> | <code>true</code> | <code>&quot;sigmoid&quot;</code> | <code>[&quot;sigmoid&quot;, &quot;gaussian&quot;, &quot;linear&quot;, &quot;exponential&quot;, &quot;step&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Type of concentration curve |
| <code>n_points</code> | <code>number</code> | <code>true</code> | <code>100</code> | — | <code>{&quot;min_value&quot;: 10}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Number of time points |
| <code>max_concentration</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Maximum concentration value |
| <code>center</code> | <code>number</code> | <code>false</code> | <code>0.5</code> | — | <code>{&quot;min_value&quot;: 0.0, &quot;step&quot;: 0.1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Center of sigmoid/gaussian (0-1) |
| <code>width</code> | <code>number</code> | <code>false</code> | <code>0.1</code> | — | <code>{&quot;min_value&quot;: 0.01, &quot;step&quot;: 0.01}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Width of sigmoid/gaussian |
| <code>duration_seconds</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 1e-12}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Physical duration represented by the normalized curve domain |

### Train/Test Split (`data.train_test_split`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>X</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| input | <code>y</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_train</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>X_test</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>y_train</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>y_test</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |
| output | <code>train_indices</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>test_indices</code> | <code>spectrasherpa://types/Array1D/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>test_size</code> | <code>number</code> | <code>true</code> | <code>0.2</code> | — | <code>{&quot;max_value&quot;: 0.99, &quot;min_value&quot;: 0.01, &quot;step&quot;: 0.05}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;split_method&quot;: [&quot;random&quot;, &quot;stratified&quot;, &quot;sequential&quot;, &quot;kennard_stone&quot;, &quot;duplex&quot;, &quot;spxy&quot;]}}</code> | Fraction of data to use for testing (0.2 = 20%) A split fraction must remain below 1 so the training partition is non-empty. |
| <code>split_method</code> | <code>select</code> | <code>true</code> | <code>&quot;random&quot;</code> | <code>[{&quot;label&quot;: &quot;Random&quot;, &quot;value&quot;: &quot;random&quot;}, {&quot;label&quot;: &quot;Stratified&quot;, &quot;value&quot;: &quot;stratified&quot;}, {&quot;label&quot;: &quot;Sequential&quot;, &quot;value&quot;: &quot;sequential&quot;}, {&quot;label&quot;: &quot;Group Holdout (selected groups)&quot;, &quot;value&quot;: &quot;group_holdout&quot;}, {&quot;label&quot;: &quot;Kennard–Stone&quot;, &quot;value&quot;: &quot;kennard_stone&quot;}, {&quot;label&quot;: &quot;DUPLEX&quot;, &quot;value&quot;: &quot;duplex&quot;}, {&quot;label&quot;: &quot;SPXY (joint X–Y)&quot;, &quot;value&quot;: &quot;spxy&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Published or statistical rule used to construct the partition |
| <code>held_out_groups</code> | <code>string_list</code> | <code>false</code> | <code>[]</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;split_method&quot;: [&quot;group_holdout&quot;]}}</code> | Exact values of the bound grouping column to place in the test partition, comma-separated (e.g. MP5). Every other group trains. |
| <code>validation_goal</code> | <code>select</code> | <code>true</code> | <code>&quot;unseen_specimens&quot;</code> | <code>[{&quot;label&quot;: &quot;Unseen specimens&quot;, &quot;value&quot;: &quot;unseen_specimens&quot;}, {&quot;label&quot;: &quot;Known specimens across blocks&quot;, &quot;value&quot;: &quot;known_specimen_cross_block&quot;}]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;split_method&quot;: [&quot;group_holdout&quot;]}}</code> | Name whether the holdout tests new specimens or repeat measurements of known specimens. |
| <code>random_seed</code> | <code>number</code> | <code>false</code> | <code>42</code> | — | <code>{&quot;max_value&quot;: 4294967295, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;basic&quot;, &quot;visible_when&quot;: {&quot;split_method&quot;: [&quot;random&quot;, &quot;stratified&quot;]}}</code> | Seed for reproducible random splits NumPy RandomState seeds are unsigned 32-bit integers. |
| <code>distance_metric</code> | <code>select</code> | <code>false</code> | <code>&quot;euclidean&quot;</code> | <code>[&quot;euclidean&quot;, &quot;mahalanobis&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;, &quot;visible_when&quot;: {&quot;split_method&quot;: [&quot;kennard_stone&quot;, &quot;duplex&quot;]}}</code> | Sample dissimilarity for Kennard–Stone and DUPLEX |
| <code>n_components</code> | <code>number</code> | <code>false</code> | <code>0</code> | — | <code>{&quot;max_value&quot;: 10000, &quot;min_value&quot;: 0, &quot;step&quot;: 1}</code> | <code>{&quot;category&quot;: &quot;advanced&quot;, &quot;visible_when&quot;: {&quot;split_method&quot;: [&quot;kennard_stone&quot;, &quot;duplex&quot;]}}</code> | Optional centered PCA projection before Kennard–Stone or DUPLEX distances (0 = raw X) The runtime additionally limits components to the smaller data dimension. |

### Combine peak columns (`data.wide_peak_table`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>true</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>reference_positions</code> | <code>string_list</code> | <code>true</code> | <code>[]</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>tolerance</code> | <code>number</code> | <code>true</code> | <code>0.5</code> | — | <code>{&quot;min_value&quot;: 0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |

### Deploy Input (`deploy.input`)

#### Ports

No input ports (source node).

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>target</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>false</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>stream_name</code> | <code>text</code> | <code>true</code> | <code>&quot;sample&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Unique portable identifier for this external data stream |
| <code>schema_version</code> | <code>select</code> | <code>true</code> | <code>&quot;spectrasherpa.deploy-input/1&quot;</code> | <code>[&quot;spectrasherpa.deploy-input/1&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Closed external scientific-dataset request schema |

### Deploy Output (`deploy.output`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/DeploymentResponse/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>output_format</code> | <code>select</code> | <code>true</code> | <code>&quot;json&quot;</code> | <code>[&quot;json&quot;, &quot;csv&quot;, &quot;plain_text&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Exact response representation |
| <code>key_value_separator</code> | <code>select</code> | <code>true</code> | <code>&quot;=&quot;</code> | <code>[&quot;=&quot;, &quot;:&quot;, &quot;\t&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Closed separator for plain-text mappings |
| <code>end_of_message_tag</code> | <code>select</code> | <code>true</code> | <code>&quot;\\n&quot;</code> | <code>[&quot;&quot;, &quot;\\n&quot;, &quot;\\r\\n&quot;]</code> | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Closed line ending for plain-text responses |

### Export wide peak CSV (`output.peak_csv`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>artifact</code> | <code>spectrasherpa://types/ExportArtifact/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>filename</code> | <code>text</code> | <code>true</code> | <code>&quot;peak-intensities.csv&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>format</code> | <code>select</code> | <code>true</code> | <code>&quot;csv&quot;</code> | <code>[&quot;csv&quot;]</code> | — | <code>{&quot;category&quot;: &quot;internal&quot;}</code> | — |

### Average · Portfolio (`preprocess.portfolio_average`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>project_id</code> | <code>number</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>portfolio_id</code> | <code>number</code> | <code>true</code> | <code>null</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>selection_sha256</code> | <code>text</code> | <code>true</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>mode</code> | <code>select</code> | <code>true</code> | <code>&quot;step&quot;</code> | <code>[&quot;step&quot;, &quot;phase_across_cycles&quot;, &quot;cycle_phase&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |
| <code>transition_trim_seconds</code> | <code>number</code> | <code>true</code> | <code>0</code> | — | <code>{&quot;min_value&quot;: 0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | — |

### Bilinear Mixture (`synthesis.blend`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>pure_spectra</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| input | <code>concentrations</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

No parameters.

### HITRAN Cross-section Response (`synthesis.hitran_response`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>pathlength_cm</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Strictly positive optical pathlength in centimetres |
| <code>temperature_k</code> | <code>number</code> | <code>true</code> | <code>293.0</code> | — | <code>{&quot;min_value&quot;: 0.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Strictly positive absolute temperature |
| <code>pressure_atm</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Strictly positive absolute pressure |

### Merge Pure Responses (`synthesis.merge`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>true</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

No parameters.

### NIST Quant IR Response (`synthesis.nist_quant_ir_response`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>pathlength_cm</code> | <code>number</code> | <code>true</code> | <code>1.0</code> | — | <code>{&quot;min_value&quot;: 0.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Strictly positive optical pathlength in centimetres |

### PPM to Fraction (`synthesis.ppm_fraction`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/TargetMatrix/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

No parameters.

### Species (`synthesis.species`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |
| output | <code>default</code> | <code>spectrasherpa://types/SpectralDataset/1.0</code> | <code>true</code> | <code>false</code> | <code>[&quot;X_spectra&quot;]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>species_name</code> | <code>text</code> | <code>true</code> | <code>&quot;Species&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Non-empty chemical or component identity |
| <code>molar_absorptivity</code> | <code>number</code> | <code>false</code> | <code>null</code> | — | <code>{&quot;min_value&quot;: 0.0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Optional finite positive reference molar absorptivity |

<!-- END GENERATED NODE REFERENCE -->
