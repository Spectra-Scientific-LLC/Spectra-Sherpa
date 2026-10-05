import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import RunDetailContent from '@/views/models/RunDetailContent.vue';

const { get, switchScope, downloadJson } = vi.hoisted(() => ({ get: vi.fn(), switchScope: vi.fn().mockResolvedValue(null), downloadJson: vi.fn() }));
vi.mock("@/utils/download", () => ({ downloadJson }));
vi.mock('@/api/client', () => ({ default: { get } }));
vi.mock('@/stores/advisor', () => ({ useAdvisorStore: () => ({ switchScope }) }));
vi.mock('@/stores/project', () => ({ useProjectStore: () => ({ currentProjectId: 1, ensureProjectForBrowserTab: async () => {} }) }));
const fixture = {
  run: { name: 'Saved PCA', status: 'completed', executed_at: '2026-09-11', run_kind: 'data' },
  evidence: { qualification: 'qualified', outputs: {
    __workflow__: { definition: { state: 'exact', storage: 'file' } },
    pca: { scores: { state: 'exact', storage: 'file' } },
    other: { default: { state: 'missing', reason: 'Output exceeded the configured limit.' } },
  } }, node_statuses: { pca: 'completed', other: 'error' },
};
beforeEach(() => {
  get.mockReset();
  switchScope.mockClear();
  get.mockImplementation(async (url: string) => {
    if (url.endsWith('/evidence')) return { data: structuredClone(fixture) };
    if (url.endsWith('/__workflow__/definition')) return { data: { value: { schema_version: 1, nodes: [{ node_id: 'pca', node_type: 'model.pca', label: 'Recorded PCA', parameters: { n_components: 2 } }], edges: [] } } };
    if (url.endsWith('/pca/scores')) return { data: { value: [[1, 2], [3, 4]] } };
    throw new Error(`Unexpected request ${url}`);
  });
});
async function open(query = '?project=1&view=Results&node=pca&offset=50') {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/runs/:runId', component: RunDetailContent }, { path: '/runs', component: { template: '<div />' } }] });
  await router.push(`/runs/42${query}`);
  await router.isReady();
  const wrapper = mount(RunDetailContent, { global: { plugins: [router], stubs: {
    Button: { props: ['label'], template: '<button @click="$emit(\'click\')">{{label}}<slot /></button>' },
    SelectButton: true, ProgressSpinner: true, Dropdown: true, ContextualActions: true,
    QuickPlotModal: { name: 'QuickPlotModal', props: ['nodeOutput', 'nodeType', 'nodeLabel'], template: '<div class="saved-plot">{{ nodeLabel }}</div>' },
  } } });
  await flushPromises();
  return { wrapper, router };
}
describe("Persistent run inspection", () => {
  it("shows the current sheet label while retaining the recorded run name", async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: {
        ...structuredClone(fixture),
        run: { ...fixture.run, id: 42, project_id: 1, workflow_id: 6,
          name: 'PLS — abc12345', display_name: 'Peak Find + PLS', workflow_name: 'Peak Find + PLS' },
      } };
      return original(url);
    });
    const { wrapper } = await open('?project=1&view=Summary');
    expect(wrapper.get('.run-detail__identity strong').text()).toBe('Peak Find + PLS');
    expect(wrapper.get('.run-detail__identity').text()).toContain('Run #42');
    expect(wrapper.get('.summary').text()).toContain('PLS — abc12345');
    expect(wrapper.get('[aria-label="Run actions"]').text()).toContain('Workflow: Peak Find + PLS');
    wrapper.unmount();
  });
  it("shows run identity and grouped actions before the final evidence warning", async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: {
        ...structuredClone(fixture),
        evidence_gaps: [{ node_id: 'pca', output: 'scores', state: 'missing', category: 'storage_limit', reason: 'Not retained', recovery: 'Re-run workflow' }],
      } };
      return original(url);
    });
    const { wrapper } = await open('?project=1&view=Summary');
    expect(wrapper.get('.run-detail__heading h2').text()).toBe('Inspect');
    expect(wrapper.get('.run-detail__identity').text()).toContain('Saved PCA');
    expect(wrapper.get('[aria-label="Run actions"]').find('[aria-label="Back to Runs"]').exists()).toBe(true);
    expect(wrapper.get('.summary').element.lastElementChild?.getAttribute('aria-label')).toBe('Incomplete durable evidence');
    wrapper.unmount();
  });
  it.each([true, false])(
    "GSC-11 preserves executed defaults or explicitly qualifies missing snapshots: %s",
    async (retained) => {
      const original = get.getMockImplementation()!;
      get.mockImplementation(async (url: string) => {
        if (url.endsWith("/evidence"))
          return {
            data: {
              ...structuredClone(fixture),
              params_snapshot: retained
                ? { pca: { n_components: 2, scale: false, random_state: 17 } }
                : null,
            },
          };
        if (url.endsWith("/__workflow__/definition"))
          return {
            data: {
              value: {
                schema_version: 1,
                nodes: [{ node_id: "pca", node_type: "model.pca", label: "PCA A", parameters: {} }],
                edges: [],
              },
            },
          };
        return original(url);
      });
      const { wrapper, router } = await open("?project=1&view=Validation&node=pca");
      expect(wrapper.text()).toContain("Effective executed parameters");
      if (retained) {
        expect(wrapper.text()).toContain("n components");
        expect(wrapper.text()).toContain("scale");
        expect(wrapper.text()).toContain("false");
        expect(wrapper.text()).toContain("17");
        await router.replace("/runs/42?project=1&view=Summary&node=pca");
        await flushPromises();
        await router.replace("/runs/42?project=1&view=Validation&node=pca");
        await flushPromises();
        expect(wrapper.text()).toContain("n components");
      } else expect(wrapper.text()).toContain("current defaults are not substituted");
      expect(get.mock.calls.some(([url]) => String(url).includes("/workflows/"))).toBe(false);
      wrapper.unmount();
    },
  );
  it("shows the retained failure on Results without claiming the definition is missing", async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith("/evidence")) {
        const data = structuredClone(fixture);
        data.evidence.outputs.pca = {} as typeof data.evidence.outputs.pca;
        data.node_statuses.pca = 'error';
        Object.assign(data.evidence.outputs, { __diagnostics__: { pca: { state: 'exact', storage: 'file' } } });
        return { data };
      }
      if (url.endsWith('/__diagnostics__/pca')) return { data: { value: { error: 'Input file layout is ambiguous.' } } };
      return original(url);
    });
    const { wrapper } = await open();
    expect(wrapper.get('[role="alert"]').text()).toBe('Input file layout is ambiguous.');
    expect(wrapper.text()).toContain('No scientific output was retained for this node.');
    expect(wrapper.text()).not.toContain('No saved node definition');
    wrapper.unmount();
  });

  it('shows each saved application failure from retained evidence on Summary', async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith("/evidence")) {
        const data = structuredClone(fixture);
        Object.assign(data.evidence.outputs, { __application__: { selection: { state: 'exact', storage: 'file' } } });
        return { data };
      }
      if (url.endsWith('/__application__/selection')) return { data: { value: {
        dataset: { name: 'Frozen input' }, scope: 'all', results: [
          { artifact_uid: 'saved-model', status: 'failed', error: 'Expected 3 features; received 2.' },
        ],
      } } };
      return original(url);
    });
    const { wrapper } = await open('?project=1&view=Summary');
    expect(wrapper.text()).toContain('Frozen input');
    expect(wrapper.text()).toContain('saved-model: failed');
    expect(wrapper.text()).toContain('Expected 3 features; received 2.');
    wrapper.unmount();
  });

  it.each([true, false])('honors saved scientific result plot support: %s', async (supportsPlot) => {
    const fallback = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) {
        const data = structuredClone(fixture);
        Object.assign(data.evidence.outputs, { __diagnostics__: { _scientific_presentations: { state: 'exact', storage: 'file' } } });
        return { data };
      }
      if (url.endsWith('/_scientific_presentations')) return { data: { value: { pca: {
        contract_digest: 'a'.repeat(64), contract: {
          schema_version: 'spectrasherpa-node-presentation/1', default_presentation: 'scores',
          presentations: [{ presentation_id: 'scores', label: 'Scores', kind: 'score_matrix', source_ports: ['scores'], modes: supportsPlot ? ['plot', 'table'] : ['table'] }],
        },
      } } } };
      return fallback(url);
    });
    const { wrapper } = await open();
    const plot = wrapper.findComponent({ name: 'QuickPlotModal' });
    expect(plot.exists()).toBe(supportsPlot);
    if (supportsPlot) {
      expect(plot.props('nodeOutput').metadata.scientific_presentation.presentation_id).toBe('scores');
      expect(plot.props('nodeOutput').presentation_value).toEqual([[1, 2], [3, 4]]);
    } else {
      expect(wrapper.find('.saved-value').exists()).toBe(true);
    }
    wrapper.unmount();
  });
  it('opens retained CV metrics when the optional comparison plot is absent, without fabricating rows', async () => {
    const fallback = get.getMockImplementation()!;
    const metrics = {
      task_type: 'regression', n_samples: 231, rmse: 1.2949488617445029,
      r2: 0.995418043105314,
      fold_validation: { scope: 'cross_validation', n_folds: 5, data_identity: 'verified_same', same_fold_indices: true },
    };
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: {
        ...structuredClone(fixture), evidence: { qualification: 'qualified', outputs: {
          __workflow__: { definition: { state: 'exact', storage: 'file' } },
          pca: { default: { state: 'exact', storage: 'file' } },
          __diagnostics__: { _scientific_presentations: { state: 'exact', storage: 'file' } },
        } },
      } };
      if (url.endsWith('/pca/default')) return { data: { value: metrics } };
      if (url.endsWith('/_scientific_presentations')) return { data: { value: { pca: {
        contract_digest: 'a'.repeat(64), contract: {
          schema_version: 'spectrasherpa-node-presentation/1', default_presentation: 'comparison',
          presentations: [
            { presentation_id: 'comparison', label: 'Predicted vs Reference', kind: 'regression_comparison', source_ports: ['comparison'], modes: ['plot', 'table'] },
            { presentation_id: 'metrics', label: 'Evaluation Metrics', kind: 'metric_record', source_ports: ['default'], modes: ['record'] },
          ],
        },
      } } } };
      return fallback(url);
    });
    const { wrapper, router } = await open();
    expect(wrapper.text()).toContain('Showing retained Evaluation Metrics');
    expect(wrapper.text()).toContain('1.2949488617445029');
    expect(wrapper.text()).toContain('231');
    expect(wrapper.findComponent({ name: 'QuickPlotModal' }).exists()).toBe(false);
    expect(wrapper.text()).not.toContain('missing declared source port');
    await router.replace({ query: { ...router.currentRoute.value.query, presentation: 'comparison' } });
    await flushPromises();
    expect(wrapper.text()).toContain('missing declared source port: comparison');
    expect(wrapper.find('.saved-value').exists()).toBe(false);
    wrapper.unmount();
  });
  it('reopens the selected saved node without loading or executing a workflow', async () => {
    const { wrapper } = await open();
    expect(wrapper.text()).toContain('Recorded PCA');
    expect(wrapper.findComponent({ name: 'QuickPlotModal' }).exists() || wrapper.find('.saved-plot').exists()).toBe(true);
    expect(get.mock.calls.map(call => call[0])).toEqual([
      '/runs/42/evidence', '/runs/42/outputs/__workflow__/definition', '/runs/42/outputs/pca/scores',
    ]);
    expect(wrapper.find('pre').exists()).toBe(false);
    expect(switchScope).toHaveBeenCalledWith(expect.objectContaining({ subscopeKey: 'run:42', resourceId: 42 }));
    wrapper.unmount();
  });
  it('preserves a missing-output reason and selected-node URL', async () => {
    const { wrapper, router } = await open();
    await router.replace('/runs/42?project=1&view=Results&node=other');
    await flushPromises();
    expect(wrapper.text()).toContain('Output exceeded the configured limit.');
    expect(wrapper.find('.saved-plot').exists()).toBe(false);
    expect(get.mock.calls.some(call => String(call[0]).includes('/other/'))).toBe(false);
    wrapper.unmount();
  });
  it('reuses retained evidence when only the presentation changes', async () => {
    const { wrapper, router } = await open();
    const requests = get.mock.calls.length;
    await router.replace({ query: { ...router.currentRoute.value.query, presentation: 'loadings' } });
    await flushPromises();
    expect(get.mock.calls).toHaveLength(requests);
    expect(switchScope).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });
  it('restores list pagination without a legacy run redirect loop', async () => {
    const { wrapper, router } = await open();
    await wrapper.get('[aria-label="Back to Runs"]').trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/runs');
    expect(router.currentRoute.value.query.offset).toBe('50');
    expect(router.currentRoute.value.query.project).toBe('1');
    expect(router.currentRoute.value.query.node).toBeUndefined();
    expect(router.currentRoute.value.query.tab).toBe('run_history');
    wrapper.unmount();
  });
});

 it.each([true, false])('preserves recorded environment on reopen/export or explicit absence: %s', async recorded => {
    const snapshot = { schema_version: 2, python: 'recorded-python', packages: { numpy: 'recorded-numpy' } };
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: { ...structuredClone(fixture), run: { ...fixture.run, id: 42 }, environment_snapshot: recorded ? snapshot : null } };
      if (url.endsWith('/__workflow__/definition')) return { data: { value: { schema_version: 1, nodes: [], edges: [] } } };
      throw new Error(url);
    });
    const { wrapper } = await open('?project=1&view=Summary');
    expect(wrapper.text()).toContain('Execution environment');
    if (recorded) {
      expect(wrapper.text()).toContain('recorded-numpy');
      await wrapper.findAll('button').find(button => button.text().includes('Export environment evidence'))!.trigger('click');
      expect(downloadJson).toHaveBeenCalledWith(expect.objectContaining({ run_id: 42, environment_snapshot: snapshot }), 'run-42-environment.json');
    } else expect(wrapper.text()).toContain('Not recorded for this run');
    expect(get.mock.calls.some(([url]) => String(url).includes('/version'))).toBe(false);
    wrapper.unmount();
  });
