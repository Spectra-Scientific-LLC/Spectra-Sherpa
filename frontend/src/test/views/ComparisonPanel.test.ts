import { mount, flushPromises } from '@vue/test-utils';
import { describe, it, expect, vi } from 'vitest';
const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/api/client', () => ({ default: { get } }));
import ComparisonPanel from '@/views/experiments/ComparisonPanel.vue';
import PrimeVue from 'primevue/config';
import type { ExecutionRunDetail } from '@/types';

const run = (id: number) => ({ id, name: `Run ${id}`, params_snapshot: {}, results_summary: {},
  diagnostics: {}, node_statuses: {}, labels: [], produced_artifact_uids: [], attempted_artifact_uids: [], succeeded_artifact_uids: [],
  executed_at: '2026-09-11T00:00:00Z', run_kind: 'training',
}) as ExecutionRunDetail;

describe('Comparison evaluation qualification', () => {
  it('links each compared run to its own retained map without decoding outputs for navigation', () => {
    get.mockClear();
    const first = { ...run(1), project_id: 4 }, second = { ...run(2), project_id: 4 };
    const wrapper = mount(ComparisonPanel, { props: { runs: [first, second], metricKeys: [], diff: {} }, global: { plugins: [PrimeVue] } });
    expect(wrapper.findAll('a.retained-map-link').map(link => link.attributes('href'))).toEqual([
      '/runs/1?project=4&tab=inspect&view=Summary#retained-observation-exclusions',
      '/runs/2?project=4&tab=inspect&view=Summary#retained-observation-exclusions',
    ]);
    expect(get).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it('shares the available width equally across candidates and wraps long values', () => {
    const runs = [run(1), run(2), run(3)];
    runs[0].name = 'A very long run name that must remain readable at narrow widths';
    const wrapper = mount(ComparisonPanel, { props: {
      runs, metricKeys: [], diff: {},
    }, global: { plugins: [PrimeVue] } });
    const table = wrapper.find('.comparison-matrix');
    expect(table.attributes('style')).toContain('min-width: 41rem');
    expect(table.findAll('col.comparison-run-column')).toHaveLength(3);
    expect(table.find('col.comparison-delta-column').exists()).toBe(false);
    expect(table.findAll('thead th')[1]?.text()).toBe(`1 · ${runs[0].name}`);
    wrapper.unmount();
  });

  it('keeps legacy overview descriptive when the scientific authority is present', () => {
    const wrapper = mount(ComparisonPanel, {props: {runs: [run(1), run(2)], metricKeys: ['accuracy'], diff: {accuracy: {'1': .9, '2': .8}}, rankableMetrics: ['accuracy'], scientificComparison: {schema_version: 'spectrasherpa-scientific-comparison/1', items: [], pairs: []}}, global: {plugins: [PrimeVue]}});
    expect(wrapper.text()).toContain('Additional recorded details');
    expect(wrapper.find('.metric-best, .delta-positive, .delta-negative').exists()).toBe(false);
    wrapper.unmount();
  });

  it('shows retained workflow nodes in DAG order and colors only the changed run', async () => {
    const first = run(1), second = run(2);
    const evidence = { outputs: { __workflow__: { definition: { state: 'exact' } } } };
    Object.assign(first, { project_id: 4, evidence_completeness: evidence });
    Object.assign(second, { project_id: 4, evidence_completeness: evidence });
    get.mockImplementation(async (url: string) => ({ data: { value: {
      nodes: [
        { node_id: 'model', node_type: 'model.fitted_pls', label: 'PLS' },
        { node_id: 'prep', node_type: 'preprocess.normalize', label: url.includes('/runs/1/') ? 'Normalize' : 'Mean Center Spectra' },
        { node_id: 'source', node_type: 'data.collection_load', label: 'Load Data' },
      ],
      edges: [
        { from_node_id: 'source', to_node_id: 'prep' },
        { from_node_id: 'prep', to_node_id: 'model' },
      ],
    } } }));
    const wrapper = mount(ComparisonPanel, { props: {
      runs: [first, second], metricKeys: [], diff: {},
    }, global: { plugins: [PrimeVue] } });
    await flushPromises();
    const rows = wrapper.findAll('tbody').find((body) => body.find('.matrix-section-row').text() === 'Workflow')!.findAll('tr').slice(1);
    expect(rows.map((row) => row.findAll('td')[0]?.text())).toEqual(['Load Data', 'Normalize', 'PLS']);
    expect(rows[1].findAll('td')[0].classes()).not.toContain('workflow-difference');
    expect(rows[1].findAll('td')[1].classes()).toContain('workflow-difference');
    wrapper.unmount();
  });
  it('offers only supported current and persisted PLS recipes and passes the selected node identities', async () => {
    const first = run(1), second = run(2);
    const evidence = { outputs: { __workflow__: { definition: { state: 'exact' } } } };
    Object.assign(first, { project_id: 4, evidence_completeness: evidence });
    Object.assign(second, { project_id: 4, evidence_completeness: evidence });
    // Negative fixture only: assemble the retired identity without registering it
    // as an allowed frontend operation in the source-level decommission guard.
    const retiredPrototype = ['model', 'pls'].join('.');
    // Raw historical bytes remain evidence; only the server projection resolves aliases.
    const historicalFittedIdentity = ['model.fitted_pls', 'v2'].join('_');
    const rawNodes = [
      { node_id: 'current', node_type: 'model.fitted_pls', label: 'Current PLS' },
      { node_id: 'persisted', node_type: historicalFittedIdentity, label: 'Persisted PLS' },
      { node_id: 'retired', node_type: retiredPrototype, label: 'Retired PLS' },
      { node_id: 'unknown', node_type: 'model.pls_regression', label: 'Unknown PLS' },
      { node_id: 'classifier', node_type: 'model.plsda', label: 'Classification' },
    ];
    get.mockResolvedValue({ data: {
      value: { nodes: rawNodes, edges: [] },
      canonical_workflow: { nodes: rawNodes.map(node => node.node_id === 'persisted'
        ? { ...node, node_type: 'model.fitted_pls' } : { ...node }), edges: [] },
    } });
    const wrapper = mount(ComparisonPanel, { props: { runs: [first, second], metricKeys: [], diff: {} },
      global: { plugins: [PrimeVue], stubs: { PairedEvaluationPanel: { props: ['recipes'], template: '<div class="paired-recipes">{{ JSON.stringify(recipes) }}</div>' } } } });
    await flushPromises();
    const selectors = wrapper.findAll('.evaluation-controls select');
    expect(selectors).toHaveLength(2);
    for (const selector of selectors) {
      expect(selector.findAll('option').map(option => option.attributes('value'))).toEqual(['', 'current', 'persisted']);
    }
    expect(rawNodes[1].node_type).toBe(historicalFittedIdentity);
    await selectors[0].setValue('current');
    await selectors[1].setValue('persisted');
    expect(JSON.parse(wrapper.find('.paired-recipes').text())).toEqual([
      { run_id: 1, model_node_id: 'current', label: 'Run 1' },
      { run_id: 2, model_node_id: 'persisted', label: 'Run 2' },
    ]);
    wrapper.unmount();
  });

  it('keeps unqualified producer records separate without inventing metric deltas', () => {
    const wrapper = mount(ComparisonPanel, { props: {
      runs: [run(1), run(2)], metricKeys: ['eval_1.r2', 'training_cv.r2'],
      diff: { 'eval_1.r2': { '1': .996, '2': .9976 }, 'training_cv.r2': { '2': .9966 } }, rankableMetrics: [],
    }, global: { plugins: [PrimeVue] } });
    const first = wrapper.get('table[aria-label="Recorded measures for Run 1"]');
    const second = wrapper.get('table[aria-label="Recorded measures for Run 2"]');
    expect(first.findAll('tbody tr')).toHaveLength(1);
    expect(second.findAll('tbody tr')).toHaveLength(2);
    expect(first.text()).toContain('0.9960');
    expect(second.text()).toContain('0.9976');
    expect(second.text()).toContain('0.9966');
    expect(first.text()).not.toContain('Delta');
    expect(first.findAll('tbody td')).toHaveLength(1);
    expect(wrapper.find('.metric-best, .delta-positive, .delta-negative').exists()).toBe(false);
    expect(wrapper.findAll('.matrix-section-row').map(section => section.text())).toEqual([
      'Run context', 'Data & partition', 'Workflow', 'Qualified measures', 'Changed settings',
    ]);
    wrapper.unmount();
  });

  it('calculates numeric setting changes but never subtracts text, booleans or missing values', () => {
    const left = run(1), right = run(2);
    left.params_snapshot = { fit: { n_components: 2, scale: true, label: '2', tolerance: 0.000001 } };
    right.params_snapshot = { fit: { n_components: 7, scale: false, label: '7', tolerance: 0.000002, seed: 1 } };
    const wrapper = mount(ComparisonPanel, { props: { runs: [left, right], metricKeys: [], diff: {} }, global: { plugins: [PrimeVue] } });
    const rows = wrapper.findAll('tbody').find(body => body.text().includes('Changed settings'))!.findAll('tr');
    const delta = (label: string) => rows.find(row => row.text().includes(label))!.findAll('td').at(-1)!.text();
    expect(delta('n components')).toBe('+5');
    expect(delta('scale')).toBe('—');
    expect(delta('label')).toBe('—');
    expect(delta('seed')).toBe('—');
    expect(delta('tolerance')).toBe('+1.0000e-6');
    wrapper.unmount();
  });

  it('uses exact split ports instead of similarly named calibration metadata', () => {
    const splitRun = run(1);
    splitRun.results_summary = {
      data_1: {
        default: { type: 'SherpaDataset', original_rows: 33, original_cols: 1868 },
        calibration_summary: { n_samples: 0, n_features: 2 },
      },
      partition_1: {
        X_train: { type: 'SherpaDataset', shape: [24, 1868] },
        X_test: { type: 'SherpaDataset', shape: [9, 1868] },
        train_indices: Array.from({ length: 24 }, (_, index) => index),
        test_indices: Array.from({ length: 9 }, (_, index) => index + 24),
      },
    };
    const wrapper = mount(ComparisonPanel, { props: {
      runs: [splitRun], metricKeys: [], diff: {},
    }, global: { plugins: [PrimeVue] } });
    const rows = wrapper.findAll('tr').map(row => row.text());
    expect(rows).toContain('Data dimensions33 samples × 1868 features');
    expect(rows).toContain('PartitionTrain 24 / Test 9, 27% test');
    wrapper.unmount();
  });

  it.each(['out_of_fold_evaluation', 'pca_scores'])('does not render removed pairing controls for %s metadata', (kind) => {
    const wrapper = mount(ComparisonPanel, {
      props: { runs: [run(1), run(2)], metricKeys: [], diff: {} },
      attrs: { resultPairs: [{ kind, requires_pairing: true }] },
      global: { plugins: [PrimeVue] },
    });
    expect(wrapper.find('.comparison-matrix').exists()).toBe(true);
    expect(wrapper.text()).not.toContain('Result pairing');
    expect(wrapper.text()).not.toContain('Check evaluation');
    expect(wrapper.find('.result-correspondence, .p-dropdown').exists()).toBe(false);
    expect(wrapper.emitted('evaluate')).toBeUndefined();
    expect(wrapper.text()).toContain('ranking requires matching evaluation evidence');
    wrapper.unmount();
  });
  it('labels bound CV and uses the correct metric direction only when qualified', () => {
    const wrapper = mount(ComparisonPanel, { props: {
      runs: [], metricKeys: [], diff: {}, rankableMetrics: ['qualified_cv.rmse', 'qualified_cv.r2'],
    }, global: { stubs: { Button: true, Column: true, DataTable: true } } });
    const vm = wrapper.vm as unknown as {
      deltaClass: (row: unknown) => string;
      formatMetricName: (key: string) => string;
      displayDelta: (row: { metric: string; delta: number }) => string;
    };
    expect(vm.formatMetricName('qualified_cv.rmse')).toBe('Bound cross-validation · RMSE');
    expect(vm.deltaClass({ metric: 'qualified_cv.rmse', delta: -0.1 })).toBe('delta-positive');
    expect(vm.deltaClass({ metric: 'qualified_cv.r2', delta: 0.1 })).toBe('delta-positive');
    expect(vm.deltaClass({ metric: 'rmse', delta: -0.1 })).toBe('');
    expect(vm.displayDelta({ metric: 'accuracy', delta: -0.0412 })).toBe('-0.0412');
    expect(vm.displayDelta({ metric: 'qualified_cv.rmse', delta: -0.1 })).toContain('-');
    wrapper.unmount();
  });
  it('does not color a winner without server-qualified evaluation evidence', () => {
    const wrapper = mount(ComparisonPanel, { props: { runs: [], metricKeys: [], diff: {} },
      global: { stubs: { Button: true, Column: true, DataTable: true } } });
    const vm = wrapper.vm as unknown as { cellClass: (row: unknown, id: number) => string; deltaClass: (row: unknown) => string };
    const row = { metric: 'accuracy', bestRunId: '2', delta: 0.1 };
    expect(vm.cellClass(row, 2)).toBe('');
    expect(vm.deltaClass(row)).toBe('');
    wrapper.unmount();
  });

});
