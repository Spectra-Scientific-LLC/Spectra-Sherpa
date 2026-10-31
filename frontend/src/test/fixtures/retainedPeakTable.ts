/** Synthetic values in the retained PeakFinding producer shape; not a captured scientific run. */
export function retainedPeakFixture() {
  const row = {
    median_pos: 1200.123456789, mean_pos: 1200.123456789, std_pos: 0, min_pos: 1200.123456789, max_pos: 1200.123456789,
    detection_count: 1, sample_count: 1, detection_fraction: 0.5,
    member_sample_indices: [0], member_sample_labels: ['Synthetic A'],
    constituent_detections: [{ sample_index: 0, sample_label: 'Synthetic A', position: 1200.123456789,
      height: 0.123456789, half_prominence_width: 2.5, absolute_window_integral: 0.234567891 }],
    median_height: 0.123456789, q1_height: 0.123456789, q3_height: 0.123456789,
    median_half_prominence_width: 2.5, q1_half_prominence_width: 2.5, q3_half_prominence_width: 2.5,
    median_absolute_window_integral: 0.234567891, q1_absolute_window_integral: 0.234567891, q3_absolute_window_integral: 0.234567891,
    consensus_peak_id: 'peak-000001', consensus_group: 1, label: 'consensus peak (1/2 samples)',
  };
  const column_units = Object.fromEntries([
    ...['median_pos', 'mean_pos', 'std_pos', 'min_pos', 'max_pos', 'median_half_prominence_width', 'q1_half_prominence_width', 'q3_half_prominence_width'].map(key => [key, 'cm-1']),
    ...['median_height', 'q1_height', 'q3_height'].map(key => [key, 'absorbance']),
    ...['median_absolute_window_integral', 'q1_absolute_window_integral', 'q3_absolute_window_integral'].map(key => [key, 'absorbance · cm-1']),
  ]);
  const peaks = { data: [row], metadata: { type: 'PeakFinding', method: 'peak_finding', n_samples: 2, n_features: 1868,
    x_title: 'Wavenumber', x_units: 'cm-1', column_units, n_consensus_peaks: 1, n_total_detections: 1 } };
  const x = Array.from({ length: 1868 }, (_, i) => 4000 - i);
  const plots = { peak_finding: { data: [
    { type: 'scatter', mode: 'lines', name: 'Synthetic A', x, y: x.map(() => 0.1) },
    { type: 'scatter', mode: 'lines', name: 'Synthetic B', x, y: x.map(() => 0.2) },
  ], layout: {} }, metadata: { n_samples: 2, n_peaks: 1 } };
  const contract = { schema_version: 'spectrasherpa-node-presentation/1', default_presentation: 'peak_overlay', presentations: [
    { presentation_id: 'peak_overlay', label: 'Spectra with Peaks', kind: 'visualization', source_ports: ['plots'], modes: ['plot'] },
    { presentation_id: 'peak_table', label: 'Peak Table', kind: 'peak_table', source_ports: ['peaks'], modes: ['plot', 'table'] },
  ] };
  const descriptor = { scientific_kind: 'peak_table', shape: [1], shape_valid: true, dimensions: [{ role: 'detected_peak', size: 1 }] };
  return { peaks, plots, contract, descriptor };
}


/** Size/trace-structure reproduction of the producer, using only synthetic coordinates. */
export function retainedPeakScaleFixture() {
  const saved = retainedPeakFixture();
  const x = Array.from({ length: 1868 }, (_, i) => 4000 - i);
  const data: Array<Record<string, unknown> & { type: string; mode: string; name: string; x: number[]; y: number[] }> = [];
  for (let sample = 0; sample < 27; sample += 1) {
    const label = `Synthetic ${sample + 1}`;
    const y = x.map((_, i) => (sample + 1) / 100 + (i % 7) / 1000);
    const indices = Array.from({ length: sample < 21 ? 110 : 109 }, (_, i) => i * 16);
    data.push({ type: 'scatter', mode: 'lines', name: label, x: [...x], y, legendgroup: label,
      line: { color: '#123456', width: 1.5 }, opacity: 0.8 });
    data.push({ type: 'scatter', mode: 'markers', name: `${label} peaks`, legendgroup: label, showlegend: false,
      x: indices.map(i => x[i]), y: indices.map(i => y[i]),
      marker: { symbol: 'triangle-down', size: 6, color: '#123456', line: { color: '#fff', width: 0.5 } } });
  }
  saved.peaks.data = Array.from({ length: 1080 }, (_, i) => ({ ...structuredClone(saved.peaks.data[0]),
    median_pos: x[i], median_height: 0.1, consensus_group: i + 1, consensus_peak_id: `peak-${i + 1}` }));
  Object.assign(saved.peaks.metadata, { n_samples: 27, n_consensus_peaks: 1080, n_total_detections: 2964 });
  saved.descriptor.shape = [1080];
  saved.descriptor.dimensions[0].size = 1080;
  data.push({ type: 'scatter', mode: 'markers', name: 'Consensus peaks', visible: true,
    x: saved.peaks.data.map(row => row.median_pos), y: saved.peaks.data.map(row => row.median_height),
    customdata: saved.peaks.data.map(row => [row.detection_fraction, row.member_sample_labels.join(', '), row.sample_count, 27]),
    marker: { symbol: 'diamond-open', size: 8, color: '#ffffff' },
    hovertemplate: 'Position: %{x}<br>Median height: %{y}<br>Spectra with detected peak: %{customdata[0]:.1%} (%{customdata[2]}/%{customdata[3]})<br>Detected in: %{customdata[1]}<extra>Consensus peaks</extra>' });
  return { ...saved, plots: { peak_finding: { data, layout: {
    xaxis: { title: 'Wavenumber (cm-1)', autorange: 'reversed' }, yaxis: { title: 'Absorbance' },
    annotations: saved.peaks.data.map((row, i) => ({ x: row.median_pos, xref: 'x', y: 1, yref: 'paper', text: String(i + 1),
      showarrow: false, yanchor: 'bottom', yshift: 14 * (i % 2), font: { color: '#f59e0b', size: 12 }, hovertext: `Consensus group ${i + 1}: ${row.median_pos}` })),
    shapes: saved.peaks.data.map(row => ({ type: 'line', xref: 'x', yref: 'paper', x0: row.median_pos, x1: row.median_pos,
      y0: 0, y1: 1, line: { color: '#f59e0b', width: 1, dash: 'dot' }, layer: 'below' })),
  } }, metadata: { n_samples: 27, n_peaks: 2964, n_consensus_peaks: 1080 } } };
}


/** Adds the actual producer's mixed-unit primary port shape; every value is synthetic. */
export function retainedPeakPrimaryFixture() {
  const saved = retainedPeakScaleFixture();
  const columnNames = Array.from({ length: 1080 }, (_, i) => [
    `peak_position_${i + 1}`, `magnitude_at_peak_${i + 1}`,
    `group_position_${i + 1}`, `magnitude_at_group_position_${i + 1}`,
  ]).flat();
  const columnUnits = Object.fromEntries(columnNames.map((name, i) => [name, i % 2 === 0 ? 'cm-1' : 'absorbance']));
  const per_spectrum = { type: 'SherpaDataset',
    data: Array.from({ length: 27 }, (_, sample) => columnNames.map((_, column) => column % 2 === 0 ? 4000 - Math.floor(column / 4) : (sample + 1) / 100)),
    metadata: { data_role: 'X_features', 'sherpa.data_role': 'X_features',
      data_modality: 'features', 'sherpa.data_modality': 'features', n_samples: 27, n_features: 4320, column_units: columnUnits,
      feature_names: columnNames, x_title: 'Peak measurements' },
    x_axis: { labels: columnNames, title: 'Peak measurements' },
  };
  const perSpectrumDescriptor = { scientific_kind: 'spectral_dataset', shape: [27, 4320], shape_valid: true,
    dimensions: [{ role: 'sample', size: 27 }, { role: 'feature', size: 4320 }] };
  saved.contract.presentations.push({ presentation_id: 'per_spectrum', label: 'Per-spectrum Peak Matrix',
    kind: 'spectral_dataset', source_ports: ['per_spectrum'], modes: ['plot', 'table'] });
  return { ...saved, per_spectrum, perSpectrumDescriptor };
}
