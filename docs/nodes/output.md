# Output Nodes

!!! abstract "Summary"
    Reference: nodes that present or export results — plots, tables, reports, and export files.

Output nodes make workflow results visible or exportable.

## Nodes

- [`output.plot`](output.md#registry-reference): Show spectra, scores, loadings, diagnostics, dendrograms, or metrics-derived plots. Many model outputs carry plot-ready payloads.
- [`output.contour`](output.md#registry-reference): Show a 2D heatmap or contour view of matrix-like spectral data.
- [`output.data_table`](output.md#registry-reference): Inspect numeric arrays, metrics, sample tables, or selected variables as rows and columns.
- [`stats.summary`](output.md#registry-reference): Generate deterministic descriptive summaries for datasets and typed scientific results. Inferential decisions remain in dedicated diagnostic nodes.
- [`output.export`](output.md#registry-reference): Prepare exact, verified bytes for a scientist-controlled download or generated-script materialization. Choose a safe basename for the prepared export; the node never chooses a filesystem path.

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
  labels, units, and role needed by the recipient. **CSV (plain)** is the default:
  a header row followed by data rows, suitable for spreadsheets and other tools.
  **CSV (portable)** adds Sherpa's encoded metadata preamble for round-trip
  preservation of typed axes, units, and inclusion marks. JSON also retains
  that scientific context. Plain CSV does not promise this metadata round trip.
  JDX prepares a `.zip` containing one
  JCAMP-DX file per input spectrum, in row order, plus `manifest.json` mapping
  filenames to source rows and recorded sample metadata. Even one spectrum
  produces a ZIP. A measured numeric feature axis and declared axis units are
  required; the node never invents them or a multi-spectrum JCAMP dialect.
  Every row reaching the node is exported, with inclusion marks preserved in
  the manifest; use Filter Samples upstream to remove excluded rows.
- After changing format or filename, rerun Prepare Export before downloading.
  The Inspector and trial editor update the extension for the chosen format.
  Existing saved `.jdx` filenames remain accepted and produce a `.zip` on rerun;
  historical single-file JDX artifacts remain readable without being rewritten.
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

<!-- BEGIN GENERATED NODE REFERENCE -->

<!-- NODE HELP REFERENCES {"help_reference": "docs/nodes/output.md", "node_types": ["output.contour", "output.data_table", "output.export", "output.plot", "stats.summary"]} -->

## Registry reference

Generated from registered node metadata. Edit methodology and examples outside the marked section.
Defaults and options below are JSON values; `null` means no concrete default is declared.
Internal parameters are retained for contract inspection and are not scientist-editable controls.
Conditional visibility describes the editor; execution admission remains node-owned.

| Node | Operation |
| --- | --- |
| Contour Plot | <code>output.contour</code> |
| Data Table | <code>output.data_table</code> |
| Prepare Export | <code>output.export</code> |
| Plot | <code>output.plot</code> |
| Statistics | <code>stats.summary</code> |

### Contour Plot (`output.contour`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>visualization</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>colorscale</code> | <code>select</code> | <code>false</code> | <code>&quot;Viridis&quot;</code> | <code>[&quot;Viridis&quot;, &quot;Hot&quot;, &quot;RdBu&quot;, &quot;Blues&quot;, &quot;Greys&quot;, &quot;Jet&quot;, &quot;Spectral&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Color scale for contour plot |
| <code>plot_type</code> | <code>select</code> | <code>false</code> | <code>&quot;heatmap&quot;</code> | <code>[&quot;heatmap&quot;, &quot;contour&quot;, &quot;surface&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Type of 2D visualization |
| <code>reverse_x</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Reverse X-axis direction (auto-enabled for wavenumber axes) |
| <code>transpose</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Swap sample and feature axes |

### Data Table (`output.data_table`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>visualization</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>max_rows</code> | <code>number</code> | <code>false</code> | <code>100000</code> | — | <code>{&quot;max_value&quot;: 100000, &quot;min_value&quot;: 10, &quot;step&quot;: 10}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Maximum number of rows to display before truncating the table preview Bounds browser memory and serialized preview size. |
| <code>transpose</code> | <code>boolean</code> | <code>false</code> | <code>false</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Swap rows and columns |
| <code>show_index</code> | <code>boolean</code> | <code>false</code> | <code>true</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Display row indices |

### Prepare Export (`output.export`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>artifact</code> | <code>spectrasherpa://types/ExportArtifact/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>filename</code> | <code>text</code> | <code>true</code> | <code>&quot;output.csv&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Safe basename including the extension required by the selected format |
| <code>format</code> | <code>select</code> | <code>true</code> | <code>&quot;csv&quot;</code> | <code>[&quot;csv&quot;, &quot;portable_csv&quot;, &quot;json&quot;, &quot;jdx&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Plain CSV, portable CSV with a metadata preamble, JSON, or JDX (ZIP of all input spectra) |

### Plot (`output.plot`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>true</code> | <code>[]</code> |
| output | <code>visualization</code> | <code>spectrasherpa://types/Visualization/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>plot_type</code> | <code>select</code> | <code>false</code> | <code>&quot;spectra&quot;</code> | <code>[&quot;spectra&quot;, &quot;contour&quot;, &quot;heatmap&quot;, &quot;scores&quot;, &quot;biplot&quot;, &quot;loadings&quot;, &quot;scatter&quot;, &quot;dendrogram&quot;, &quot;explained_variance&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Type of plot to generate. Hosted execution admits spectra, scores, loadings, explained variance, or scatter. Plot input is bounded to 500,000 values and 2 MiB of text before expansion. |
| <code>colorscale</code> | <code>select</code> | <code>false</code> | <code>&quot;Viridis&quot;</code> | <code>[&quot;Viridis&quot;, &quot;Hot&quot;, &quot;RdBu&quot;, &quot;Blues&quot;, &quot;Greys&quot;, &quot;Jet&quot;, &quot;Spectral&quot;]</code> | — | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Color scale for contour/heatmap plots |
| <code>x_axis</code> | <code>number</code> | <code>false</code> | <code>0</code> | — | <code>{&quot;max_value&quot;: 63, &quot;min_value&quot;: 0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Index or label for X axis Bounds component selection to a practical visualization range. |
| <code>y_axis</code> | <code>number</code> | <code>false</code> | <code>1</code> | — | <code>{&quot;max_value&quot;: 63, &quot;min_value&quot;: 0}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Index or label for Y axis Bounds component selection to a practical visualization range. |
| <code>plot_key</code> | <code>text</code> | <code>false</code> | <code>&quot;&quot;</code> | — | — | <code>{&quot;category&quot;: &quot;advanced&quot;}</code> | Optional exact key selecting a plot payload from a structured input. Hosted execution requires this field to remain blank. |

### Statistics (`stats.summary`)

#### Ports

| Direction | Port | Type URI | Required | Variadic | Accepted data roles |
| --- | --- | --- | --- | --- | --- |
| input | <code>default</code> | <code>spectrasherpa://types/Any/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |
| output | <code>statistics</code> | <code>spectrasherpa://types/StatisticsSummary/1.0</code> | <code>true</code> | <code>false</code> | <code>[]</code> |

#### Parameters

| Parameter | Editor type | Required | Default | Options / enum | Bounds / step | Visibility / category | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| <code>max_samples</code> | <code>number</code> | <code>false</code> | <code>100</code> | — | <code>{&quot;max_value&quot;: 10000, &quot;min_value&quot;: 10}</code> | <code>{&quot;category&quot;: &quot;basic&quot;}</code> | Maximum rows in per-sample statistics table Bounds the serialized per-sample table and workbench response size; the result reports explicit truncation. |

<!-- END GENERATED NODE REFERENCE -->
