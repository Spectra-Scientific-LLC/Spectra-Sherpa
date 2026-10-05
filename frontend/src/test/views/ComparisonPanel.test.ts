import { mount } from '@vue/test-utils';
import { describe, it, expect } from 'vitest';
import ComparisonPanel from '@/views/experiments/ComparisonPanel.vue';
import PrimeVue from 'primevue/config';
import type { ExecutionRunDetail } from '@/types';

const run = (id: number) => ({ id, name: `Run ${id}`, params_snapshot: {}, results_summary: {},
  diagnostics: {}, node_statuses: {}, labels: [], produced_artifact_uids: [], attempted_artifact_uids: [], succeeded_artifact_uids: [],
  executed_at: '2026-09-11T00:00:00Z', run_kind: 'training',
}) as ExecutionRunDetail;

describe('Comparison evaluation qualification', () => {
  it('shows neutral arithmetic deltas without asserting an unqualified winner', () => {
    const wrapper = mount(ComparisonPanel, { props: {
      runs: [run(1), run(2)], metricKeys: ['accuracy'], diff: { accuracy: { '1': 0.9, '2': 0.8588 } },
      rankableMetrics: [],
    }, global: { plugins: [PrimeVue] } });
    const row = wrapper.findAll('tr').find(row => row.text().includes('Accuracy'));
    expect(row).toBeDefined();
    expect(row!.findAll('td').at(-1)!.text()).toBe('-0.0412');
    expect(wrapper.find('.metric-best, .delta-positive, .delta-negative').exists()).toBe(false);
    expect(wrapper.findAll('.matrix-section-row').map(section => section.text())).toEqual([
      'Run context', 'Data & partition', 'Workflow', 'Results', 'Changed settings',
    ]);
    expect(row!.find('.difference-neutral').exists()).toBe(true);
    expect(wrapper.text()).not.toContain('Result pairing');
    expect(wrapper.find('.result-correspondence').exists()).toBe(false);
    expect(wrapper.find('.p-dropdown').exists()).toBe(false);
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
