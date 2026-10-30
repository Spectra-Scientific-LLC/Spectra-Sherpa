import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils';
import { reactive } from 'vue';
import { createRouter, createMemoryHistory } from 'vue-router';
import RunDetailContent from '@/views/models/RunDetailContent.vue';
import { registerContextualActions, removeContextualActions } from '@/composables/useContextualActions';
import { runProjectScopeResets } from '@/stores/projectScopeRegistry';

const { get, patch, switchScope, downloadJson, downloadCsv } = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), switchScope: vi.fn().mockResolvedValue(null), downloadJson: vi.fn(), downloadCsv: vi.fn() }));
vi.mock("@/utils/download", () => ({ downloadJson, downloadCsv }));
vi.mock('@/api/client', () => ({ default: { get, patch } }));
vi.mock('@/stores/advisor', () => ({ useAdvisorStore: () => ({ switchScope }) }));
const project = reactive({
  currentProjectId: 1 as number | null,
  ensureProjectForBrowserTab: vi.fn(async () => {}),
  selectProject: vi.fn(async (id: number) => { project.currentProjectId = id; }),
});
const auth = reactive({ user: { id: 1 } as { id: number } | null, token: 'session-A' as string | null, get sessionRevision() { return this.token; } });
vi.mock('@/stores/project', () => ({ useProjectStore: () => project }));
vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }));
let mounted: VueWrapper[] = [];
const fixture = {
  run: { name: 'Saved PCA', status: 'completed', executed_at: '2026-09-11', run_kind: 'data' },
  evidence: { qualification: 'qualified', outputs: {
    __workflow__: { definition: { state: 'exact', storage: 'file' } },
    pca: { scores: { state: 'exact', storage: 'file' }, _internal: { state: 'missing', reason: 'Internal execution bookkeeping' } },
    other: { default: { state: 'missing', reason: 'Output exceeded the configured limit.' } },
  } }, node_statuses: { pca: 'completed', other: 'error' },
};
beforeEach(() => {
  project.currentProjectId = 1;
  project.ensureProjectForBrowserTab.mockReset().mockResolvedValue(undefined);
  project.selectProject.mockReset().mockImplementation(async (id: number) => { project.currentProjectId = id; });
  auth.user = { id: 1 }; auth.token = 'session-A';
  get.mockReset();
  patch.mockReset().mockImplementation(async (_url: string, payload: { name: string }) => ({ data: { name: payload.name } }));
  switchScope.mockClear();
  downloadCsv.mockClear();
  get.mockImplementation(async (url: string) => {
    if (url.endsWith('/evidence')) return { data: structuredClone(fixture) };
    if (url.endsWith('/__workflow__/definition')) return { data: { value: { schema_version: 1, nodes: [{ node_id: 'pca', node_type: 'model.pca', label: 'Recorded PCA', parameters: { n_components: 2 } }], edges: [] } } };
    if (url.endsWith('/pca/scores')) return { data: { value: [[1, 2], [3, 4]] } };
    throw new Error(`Unexpected request ${url}`);
  });
});
afterEach(() => { for (const wrapper of mounted) wrapper.unmount(); mounted = []; });
async function open(query = '?project=1&view=Results&node=pca&offset=50', realContext = false) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/runs/:runId', component: RunDetailContent }, { path: '/runs', component: { template: '<div />' } }, { path: '/report', component: { template: '<div />' } }] });
  await router.push(`/runs/42${query}`);
  await router.isReady();
  const wrapper = mount(RunDetailContent, { global: { plugins: [router], stubs: {
    Button: { props: ['label'], template: '<button @click="$emit(\'click\')">{{label}}<slot /></button>' },
    ModelPromotionReview: { props: ['artifactUid'], template: '<div class="promotion-dialog">{{artifactUid}}</div>' },
    SelectButton: true, ProgressSpinner: true, Dropdown: true, ContextualActions: !realContext,
    QuickPlotModal: { name: 'QuickPlotModal', props: ['nodeOutput', 'nodeType', 'nodeLabel'], template: '<div class="saved-plot">{{ nodeLabel }}</div>' },
  } } });
  mounted.push(wrapper);
  await flushPromises();
  return { wrapper, router };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function runEvidence(id: number, name = `Run ${id}`) {
  return { data: {
    ...structuredClone(fixture),
    run: { ...fixture.run, id, name, project_id: 1, workflow_id: 7 },
  } };
}
function installIdentifiedRuns() {
  const original = get.getMockImplementation()!;
  get.mockImplementation(async (url: string, config?: unknown) => {
    if (url.endsWith('/evidence')) return runEvidence(Number(url.split('/')[2]));
    return original(url, config);
  });
}

describe('Retained run request scope', () => {
  it('rejects an old A response after A→B→A and keeps the newly loaded A', async () => {
    installIdentifiedRuns();
    const normal = get.getMockImplementation()!;
    const old = deferred<ReturnType<typeof runEvidence>>();
    let first = true;
    get.mockImplementation((url: string, config?: unknown) => {
      if (url === '/runs/42/evidence' && first) { first = false; return old.promise; }
      return normal(url, config);
    });
    const { wrapper, router } = await open('?project=1&view=Summary');
    const firstSignal = get.mock.calls.find(([url]) => url === '/runs/42/evidence')![1].signal;
    await router.replace('/runs/43?project=1&view=Summary'); await flushPromises();
    expect(wrapper.get('[aria-label="Run name"]').element).toHaveProperty('value', 'Run 43');
    await router.replace('/runs/42?project=1&view=Summary'); await flushPromises();
    old.resolve(runEvidence(42, 'Stale first A'));
    await flushPromises();
    expect(firstSignal.aborted).toBe(true);
    expect(wrapper.get('[aria-label="Run name"]').element).toHaveProperty('value', 'Run 42');
    expect(wrapper.text()).not.toContain('Stale first A');
  });

  it('ignores an old run error/finally while the replacement run is still loading', async () => {
    installIdentifiedRuns();
    const normal = get.getMockImplementation()!;
    const old = deferred<ReturnType<typeof runEvidence>>();
    const current = deferred<ReturnType<typeof runEvidence>>();
    get.mockImplementation((url: string, config?: unknown) => {
      if (url === '/runs/42/evidence') return old.promise;
      if (url === '/runs/43/evidence') return current.promise;
      return normal(url, config);
    });
    const { wrapper, router } = await open('?project=1&view=Summary');
    await router.replace('/runs/43?project=1&view=Summary'); await flushPromises();
    old.reject(new Error('Obsolete run failed'));
    await flushPromises();
    expect((wrapper.vm as any).loading).toBe(true);
    expect(wrapper.text()).not.toContain('Obsolete run failed');
    expect(wrapper.find('[aria-label="Run name"]').exists()).toBe(false);
    current.resolve(runEvidence(43)); await flushPromises();
    expect((wrapper.vm as any).loading).toBe(false);
    expect(wrapper.get('[aria-label="Run name"]').element).toHaveProperty('value', 'Run 43');
  });

  it.each(['success', 'error'])('ignores late rename %s and its report continuation after A→B→A', async outcome => {
    installIdentifiedRuns();
    const old = deferred<{ data: { name: string } }>();
    const current = deferred<{ data: { name: string } }>();
    patch.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const { wrapper, router } = await open('?project=1&view=Summary');
    await wrapper.get('[aria-label="Run name"]').setValue('Old rename');
    await wrapper.get('[aria-label="Run name"]').trigger('blur');
    await wrapper.findAll('button').find(button => button.text() === 'Report')!.trigger('click');
    await router.replace('/runs/43?project=1&view=Summary'); await flushPromises();
    await router.replace('/runs/42?project=1&view=Summary'); await flushPromises();
    await wrapper.get('[aria-label="Run name"]').setValue('Current rename');
    await wrapper.get('[aria-label="Run name"]').trigger('blur');
    expect(patch.mock.calls[0][2].signal.aborted).toBe(true);
    if (outcome === 'success') old.resolve({ data: { name: 'Old rename' } });
    else old.reject(new Error('Obsolete rename failed'));
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/runs/42');
    expect(wrapper.get('[aria-label="Run name"]').element).toHaveProperty('value', 'Current rename');
    expect((wrapper.vm as any).runNameSaving).toBe(true);
    expect((wrapper.vm as any).runNameError).toBe('');
    expect(wrapper.emitted('renamed')).toBeUndefined();
    current.resolve({ data: { name: 'Current rename' } }); await flushPromises();
    expect((wrapper.vm as any).runNameSaving).toBe(false);
    expect(wrapper.emitted('renamed')).toHaveLength(1);
    expect(router.currentRoute.value.path).toBe('/runs/42');
  });

  it('does not restore a linked old project or display its delayed retained output after a project switch', async () => {
    installIdentifiedRuns();
    const normal = get.getMockImplementation()!;
    const old = deferred<{ data: { value: number[][] } }>();
    get.mockImplementation((url: string, config?: unknown) =>
      url.endsWith('/pca/scores') ? old.promise : normal(url, config));
    const { wrapper } = await open();
    const signal = get.mock.calls.find(([url]) => String(url).endsWith('/pca/scores'))![1].signal;
    project.ensureProjectForBrowserTab.mockClear().mockImplementation(async () => {
      // A browser-tab restoration is not allowed to undo the dropdown choice.
      project.currentProjectId = 1;
    });
    project.selectProject.mockClear();
    project.currentProjectId = 2;
    await flushPromises();
    old.resolve({ data: { value: [[999, 999]] } }); await flushPromises();
    expect(project.currentProjectId).toBe(2);
    expect(project.selectProject).not.toHaveBeenCalled();
    expect(project.ensureProjectForBrowserTab).not.toHaveBeenCalled();
    expect(signal.aborted).toBe(true);
    expect(wrapper.text()).toContain('Select the project that owns this run.');
    expect(wrapper.find('.saved-plot').exists()).toBe(false);
    expect((wrapper.vm as any).values).toEqual({});
  });

  it('still admits an explicitly followed project deep link and loads under that project', async () => {
    installIdentifiedRuns();
    project.currentProjectId = 2;
    const { wrapper } = await open('?project=1&view=Summary');
    expect(project.selectProject).toHaveBeenCalledExactlyOnceWith(1);
    expect(project.currentProjectId).toBe(1);
    expect(wrapper.get('[aria-label="Run name"]').element).toHaveProperty('value', 'Run 42');
    expect(get.mock.calls.filter(([url]) => url === '/runs/42/evidence')).toHaveLength(1);
  });

  it.each(['user', 'session', 'reset'])('invalidates the retained cache on a %s A→B→A/reset even with unchanged run and project IDs', async kind => {
    installIdentifiedRuns();
    const normal = get.getMockImplementation()!;
    const old = deferred<{ data: { value: number[][] } }>();
    let scoresReads = 0;
    get.mockImplementation((url: string, config?: unknown) => {
      if (url.endsWith('/pca/scores')) {
        scoresReads++;
        return scoresReads === 1 ? old.promise : Promise.resolve({ data: { value: [[7, 8]] } });
      }
      return normal(url, config);
    });
    const { wrapper } = await open();
    const vm = wrapper.vm as any;
    const signal = get.mock.calls.find(([url]) => String(url).endsWith('/pca/scores'))![1].signal;
    if (kind === 'user') { auth.user = { id: 2 }; auth.user = { id: 1 }; }
    else if (kind === 'session') { auth.token = 'session-B'; auth.token = 'session-A'; }
    else runProjectScopeResets();
    expect(vm.detail).toBeNull();
    expect(vm.values).toEqual({});
    expect(signal.aborted).toBe(true);
    old.resolve({ data: { value: [[999, 999]] } }); await flushPromises();
    expect(vm.values).toEqual({});
    await vm.loadRun(false); await flushPromises();
    expect(scoresReads).toBe(2);
    expect(vm.values.scores).toEqual([[7, 8]]);
    expect(wrapper.find('.saved-plot').exists()).toBe(true);
  });

  it('clears visible cached records on logout without making anonymous retained-output requests', async () => {
    installIdentifiedRuns();
    const { wrapper } = await open();
    expect((wrapper.vm as any).values.scores).toEqual([[1, 2], [3, 4]]);
    const requests = get.mock.calls.length;
    auth.user = null; auth.token = null;
    expect((wrapper.vm as any).detail).toBeNull();
    expect((wrapper.vm as any).values).toEqual({});
    await flushPromises();
    expect(get.mock.calls).toHaveLength(requests);
    expect(wrapper.find('.saved-plot').exists()).toBe(false);
  });

  it('refetches cached output for a validated replacement session on the same route', async () => {
    installIdentifiedRuns();
    const { wrapper } = await open();
    const reads = () => get.mock.calls.filter(([url]) => String(url).endsWith('/pca/scores')).length;
    expect(reads()).toBe(1);
    auth.token = 'session-B';
    await flushPromises();
    expect(reads()).toBe(2);
    expect((wrapper.vm as any).values.scores).toEqual([[1, 2], [3, 4]]);
  });
});

describe("Persistent run inspection", () => {
  it('shows retained paired evaluation after reopening Inspect without requiring a workflow snapshot', async () => {
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return {data: {run: {...fixture.run, id: 42, project_id: 1, source_type: 'paired_evaluation', run_kind: 'other'}, evidence: {qualification: 'qualified', outputs: {__evaluation__: {record: {state: 'exact', storage: 'file'}}}}, node_statuses: {}}};
      if (url === '/runs/paired-evaluations/42') return {data: {status: 'completed', record: {
        schema_version: 'spectrasherpa-paired-evaluation/1', protocol: {recipes: [{run_id: 1, model_node_id: 'pls'}, {run_id: 2, model_node_id: 'pls'}]}, protocol_digest: 'receipt', population: {development_count: 174, held_out_count: 57}, splits: [], paired_rmsecv_differences: [-.2], results: [{execution: {metrics: {rmse: 1.2}}}, {execution: {metrics: {rmse: 1}}}], summary: {right_meaningfully_better: 1, left_meaningfully_better: 0, within_margin: 0}, interpretation: 'Not independent validation',
      }}};
      throw new Error(`Unexpected request ${url}`);
    });
    const {wrapper} = await open('?project=1');
    expect(wrapper.get('[aria-label="Paired training CV results"]').text()).toContain('Held-out excluded: 57');
    expect(wrapper.text()).not.toContain('Open Deploy');
    expect(get.mock.calls.some(([url]) => String(url).includes('__workflow__'))).toBe(false);
    wrapper.unmount();
  });

  it.each([{ uids: ['first'] }, { uids: ['first', 'second'] }])('opens the exact produced model under Models: $uids', async ({ uids }) => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: { ...structuredClone(fixture), run: { ...fixture.run, id: 42, project_id: 1, produced_artifact_uids: uids } } };
      return original(url);
    });
    const { wrapper, router } = await open('?project=1&view=Summary&node=pca');
    const button = wrapper.findAll('button').find(b => b.text() === 'Open model')!;
    if (uids.length > 1) {
      expect(button.attributes('disabled')).toBeDefined();
      await wrapper.get('[aria-label="Fitted model to open"]').setValue('second');
      const menu = (wrapper.vm as any).headerActions.find((item: {label: string}) => item.label === 'Open model');
      expect(menu.command).toBeUndefined();
      expect(menu.items.map((item: {label: string}) => item.label)).toEqual(uids);
    }
    await button.trigger('click');
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/runs');
    expect(router.currentRoute.value.query).toEqual({ tab: 'models', project: '1', artifact: uids.at(-1) });
    expect(wrapper.text()).not.toContain('Review for promotion');
    expect(patch).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('shows the exact per-file operational screen when Deploy opens its retained model node', async () => {
    const original = get.getMockImplementation()!;
    let reduced = false;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: { ...structuredClone(fixture), run: { ...fixture.run, run_kind: 'batch_inference' }, evidence: { qualification: 'qualified', outputs: {
        __workflow__: { definition: { state: 'exact', storage: 'file' } },
        'file_0::model': {
          result: { state: 'exact', storage: 'file' },
          labels: { state: 'exact', storage: 'file' },
          model_id: { state: 'exact', storage: 'file' },
          applicability: { state: reduced ? 'reduced' : 'exact', storage: 'file', sha256: 'd'.repeat(64) },
        },
      } }, node_statuses: { 'file_0::model': 'completed' } } };
      if (url.endsWith('/__workflow__/definition')) return { data: { value: {
        schema_version: 1, nodes: [
          { node_id: 'file_0::model', node_type: 'model.load_apply', label: 'Saved model', parameters: {} },
          { node_id: 'file_0::exit', node_type: 'output.table', label: 'Output', parameters: {} },
        ], edges: [],
      } } };
      if (url.endsWith('/file_0%3A%3Amodel/result')) return { data: { value: [[1.1], [1.3]] } };
      if (url.endsWith('/file_0%3A%3Amodel/labels')) return { data: { value: ['Class A', 'Class B'] } };
      if (url.endsWith('/file_0%3A%3Amodel/model_id')) return { data: { value: 'saved-plsda' } };
      if (url.endsWith('/file_0%3A%3Amodel/applicability')) return { data: { value: {
        claim_scope: 'provisional_calibration_screening', method: 'prediction_f_and_residual_spectrum_0.95_strict_greater',
        reference_samples: 12, t2_limit: 4, q_limit: 1,
        rows: [{ row_index: 0, screening_status: 'within_global_screen', t2: 2, q: .3 },
          { row_index: 1, screening_status: 'outside_global_screen', t2: 5, q: .4 }],
      } } };
      return original(url);
    });
    const { wrapper } = await open('?project=1&view=Results&node=file_0%3A%3Amodel');
    expect(wrapper.get('[aria-label="Retained prediction trust"]').text()).toContain('Outside global screen');
    expect(wrapper.get('[aria-label="Retained prediction trust"]').text()).toContain('File dataset position');
    expect(wrapper.get('[aria-label="Retained prediction trust"]').text()).toContain('Class B');
    expect(wrapper.get('[aria-label="Retained prediction trust"]').text()).toContain('saved-plsda');
    wrapper.unmount();
    const inspected = await open('?project=1&view=Results&node=file_0%3A%3Aexit&trust=1');
    expect(inspected.router.currentRoute.value.query.node).toBe('file_0::model');
    expect(inspected.wrapper.get('[aria-label="Retained prediction trust"]').text()).toContain('Class B');
    inspected.wrapper.unmount();
    reduced = true;
    const unavailable = await open('?project=1&view=Results&node=file_0%3A%3Amodel');
    expect(unavailable.wrapper.find('[aria-label="Retained prediction trust"]').exists()).toBe(false);
    expect(unavailable.wrapper.text()).toContain('Applicability unavailable: no matching, exact fitted row-level screen');
    unavailable.wrapper.unmount();
  });
  it('shows retained PLS-DA trust rows in batch history and exports safe assembled positions', async () => {
    const original = get.getMockImplementation()!;
    let reducedSelection = false;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: { ...structuredClone(fixture), evidence: { qualification: 'qualified', outputs: {
        __workflow__: { definition: { state: 'exact', storage: 'file' } },
        __application__: { selection: { state: reducedSelection ? 'reduced' : 'exact', storage: 'file' } },
        'model-1': { default: { state: 'exact', storage: 'file' } },
      } } } };
      if (url.endsWith('/__application__/selection')) return { data: { value: {
        dataset: { name: 'Batch cohort' }, scope: 'all', successful_artifact_uids: ['model-1'],
        results: [{ artifact_uid: 'model-1', status: 'completed' }],
      } } };
      if (url.endsWith('/model-1/default')) return { data: { value: {
        artifact_uid: 'model-1', model_type: 'plsda', sample_indices: [2, 5, 8], predictions: ['\u0001=HYPERLINK("bad")', 'B', '\u00a0=HYPERLINK("bad")'],
        applicability: { method: 'prediction_f_and_residual_spectrum_0.95_strict_greater', claim_scope: 'provisional_calibration_screening',
          reference_samples: 12, t2_limit: 4, q_limit: 1,
          rows: [{ row_index: 0, screening_status: 'within_global_screen', t2: 2, q: .3 },
            { row_index: 1, screening_status: 'outside_global_screen', t2: 5, q: .4 },
            { row_index: 2, screening_status: 'within_global_screen', t2: 2, q: .2 }] },
      } } };
      return original(url);
    });
    const { wrapper } = await open('?project=1&view=Summary');
    expect(wrapper.get('[aria-label="Prediction trust for model-1"]').text()).toContain('Outside global screen');
    expect(wrapper.get('[aria-label="Prediction trust for model-1"]').text()).toContain('Within global screen; unqualified');
    await wrapper.get('[aria-label="Prediction trust for model-1"] button').trigger('click');
    expect(downloadCsv).toHaveBeenCalled();
    const rows = downloadCsv.mock.calls.at(-1)?.[0];
    expect(rows[1]).toContain(3);
    expect(rows[2]).toContain(6);
    expect(rows[1]).toContain("'\u0001=HYPERLINK(\"bad\")");
    expect(rows[3]).toContain(9);
    expect(rows[3]).toContain("'\u00a0=HYPERLINK(\"bad\")");
    expect(rows[0]).toContain('dataset_position');
    wrapper.unmount();
    reducedSelection = true;
    const unavailable = await open('?project=1&view=Summary');
    expect(unavailable.wrapper.find('[aria-label="Prediction trust for model-1"]').exists()).toBe(false);
    expect(unavailable.wrapper.text()).toContain('Application context unavailable: exact selection evidence was not retained.');
    unavailable.wrapper.unmount();
  });
  it('saves the editable run name on blur and keeps retained results unchanged', async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: {
        ...structuredClone(fixture), run: { ...fixture.run, id: 42, project_id: 1 },
      } };
      return original(url);
    });
    const { wrapper } = await open('?project=1&view=Summary');
    const input = wrapper.get('[aria-label="Run name"]');
    await input.setValue('  Reviewed PCA  ');
    await input.trigger('blur');
    await flushPromises();
    expect(patch).toHaveBeenCalledWith('/runs/42/name', { name: 'Reviewed PCA' }, { params: { project_id: 1 }, signal: expect.any(AbortSignal) });
    expect((input.element as HTMLInputElement).value).toBe('Reviewed PCA');
    expect(wrapper.get('.summary').text()).toContain('Reviewed PCA');
    expect(wrapper.emitted('renamed')).toHaveLength(1);
    wrapper.unmount();
  });
  it('waits for an in-flight rename before opening the report', async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: { ...structuredClone(fixture),
        run: { ...fixture.run, id: 42, workflow_id: 7, project_id: 1 },
      } };
      return original(url);
    });
    let finishRename!: (value: { data: { name: string } }) => void;
    patch.mockImplementationOnce(() => new Promise((resolve) => { finishRename = resolve; }));
    const { wrapper, router } = await open('?project=1&view=Summary');
    const input = wrapper.get('[aria-label="Run name"]');
    await input.setValue('Reviewed Iris run');
    await input.trigger('blur');
    await wrapper.findAll('button').find((button) => button.text() === 'Report')!.trigger('click');
    expect(router.currentRoute.value.path).toBe('/runs/42');
    finishRename({ data: { name: 'Reviewed Iris run' } });
    await flushPromises();
    expect(router.currentRoute.value.path).toBe('/report');
  });
  it('shows one complete prediction ledger instead of duplicating its raw comparison', async () => {
    const fallback = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: { ...structuredClone(fixture), evidence: { qualification: 'qualified', outputs: {
        __workflow__: { definition: { state: 'exact', storage: 'file' } },
        pca: { comparison: { state: 'exact', storage: 'file' } },
        __diagnostics__: { _scientific_presentations: { state: 'exact', storage: 'file' } },
      } } } };
      if (url.endsWith('/pca/comparison')) return { data: { value: {
        schema_version: 'spectrasherpa-classification-comparison/1', shape: [1, 5],
        data: [{ sample: 'Specimen A', reference: 'class A', predicted: 'class A', correct: true, role: 'held_out_test' }],
      } } };
      if (url.endsWith('/_scientific_presentations')) return { data: { value: { pca: {
        contract_digest: 'a'.repeat(64), contract: {
          schema_version: 'spectrasherpa-node-presentation/1', default_presentation: 'comparison',
          presentations: [{ presentation_id: 'comparison', label: 'Predictions', kind: 'classification_comparison', source_ports: ['comparison'], modes: ['table'] }],
        },
      } } } };
      return fallback(url);
    });
    const { wrapper } = await open();
    expect(wrapper.findAll('[aria-label="Validation ledger"]')).toHaveLength(1);
    expect(wrapper.find('.saved-value').exists()).toBe(false);
    expect(wrapper.findComponent({ name: 'QuickPlotModal' }).exists()).toBe(false);
    wrapper.unmount();
  });

  it("opens with a model summary built only from retained calibration and test statistics", async () => {
    const comparison = (role: string, target: string, metrics: Record<string, number>) => ({
      schema_version: 'spectrasherpa-regression-comparison/1', data: [], metadata: { role },
      statistics: { targets: [{ target, metrics }] },
    });
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: { ...structuredClone(fixture),
        params_snapshot: { model_1: { n_components: 3, scale: false } },
        evidence: { qualification: 'qualified', outputs: {
          __workflow__: { definition: { state: 'exact', storage: 'file' } },
          __diagnostics__: { _scientific_presentations: { state: 'exact', storage: 'file' } },
          model_1: { calibration_comparison: { state: 'exact', storage: 'file' } },
          eval_1: { comparison: { state: 'exact', storage: 'file' } },
        } } } };
      if (url.endsWith('/__workflow__/definition')) return { data: { value: { schema_version: 1, nodes: [
        { node_id: 'snv_1', node_type: 'preprocess.normalize', label: 'SNV', parameters: {} },
        { node_id: 'model_1', node_type: 'model.fitted_pls', label: 'Train PLS', parameters: { n_components: 7 } },
        { node_id: 'eval_1', node_type: 'diagnostics.labeled_regression_evaluator', label: 'Test Evaluation', parameters: {} },
      ], edges: [{ from_node_id: 'snv_1', from_output: 'default', to_node_id: 'model_1', to_input: 'default' }] } } };
      if (url.endsWith('/_scientific_presentations')) return { data: { value: {
        model_1: { contract: { presentations: [{ presentation_id: 'calibration_fit', kind: 'regression_comparison', source_ports: ['calibration_comparison'] }] } },
        eval_1: { contract: { presentations: [{ presentation_id: 'held_out_comparison', kind: 'regression_comparison', source_ports: ['comparison'] }] } },
      } } };
      if (url.endsWith('/model_1/calibration_comparison')) return { data: { value: comparison('calibration', 'Target 1', { n_samples: 30, rmse: 0.2894, r2: 0.9999 }) } };
      if (url.endsWith('/eval_1/comparison')) return { data: { value: comparison('held_out_test', 'Moisture', { n_samples: 10, rmse: 0.3975, r2: 0.9992 }) } };
      return { data: { value: null } };
    });
    const { wrapper } = await open('?project=1&view=Summary');
    const card = wrapper.get('[aria-label="Model summary"]');
    expect(card.text()).toContain('PLS regression');
    // Effective parameters, never the authored value or a current default.
    expect(card.text()).toContain('3 latent variables');
    expect(card.text()).not.toContain('7 latent');
    expect(card.text()).toContain('SNV');
    const statistics = wrapper.get('.summary [aria-label="Model summary"]');
    expect(statistics.text()).toContain('RMSEC (units not declared) 0.2894');
    expect(statistics.text()).toContain('RMSEP (units not declared) 0.3975');
    expect(statistics.text()).toContain('Protocol: Calibration fit');
    expect(statistics.text()).toContain('Protocol: Held-out test');
    wrapper.unmount();
  });
  it('uses independent canonical Summary, Results and Validation panels without discarding retained evidence', async () => {
    const { wrapper, router } = await open();
    const panels = wrapper.findAllComponents({ name: 'Panel' });
    expect(panels.map(panel => panel.props('header'))).toEqual(['Summary', 'Results', 'Validation']);
    expect(panels.map(panel => panel.props('collapsed'))).toEqual([true, false, true]);
    const before = get.mock.calls.filter(([url]) => url.endsWith('/pca/scores')).length;
    panels[2].vm.$emit('update:collapsed', false); await flushPromises();
    expect(router.currentRoute.value.query.view).toBe('Validation');
    expect(panels.map(panel => panel.props('collapsed'))).toEqual([true, false, false]);
    panels[0].vm.$emit('update:collapsed', false); await flushPromises();
    expect(panels.map(panel => panel.props('collapsed'))).toEqual([false, false, false]);
    expect(get.mock.calls.filter(([url]) => url.endsWith('/pca/scores')).length).toBe(before);
    expect(wrapper.find('.saved-plot').exists()).toBe(true);
    panels[0].vm.$emit('update:collapsed', true); await flushPromises();
    expect(panels[0].props('collapsed')).toBe(true);
    wrapper.unmount();
  });
  it('explains partial retention on the default Results view', async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url.endsWith('/evidence')) return { data: {
        ...structuredClone(fixture), run: { ...fixture.run, status: 'partial' },
        error: 'Execution succeeded; export exceeds the retained materialization budget.',
      } };
      return original(url);
    });
    const { wrapper } = await open();
    expect(wrapper.get('[role="status"]').text()).toContain('Incomplete saved run:');
    expect(wrapper.get('[role="status"]').text()).toContain('Execution succeeded; export exceeds');
    wrapper.unmount();
  });
  it('omits internal bookkeeping from scientific evidence warnings', async () => {
    const { wrapper } = await open();
    expect(wrapper.text()).not.toContain('_internal');
    expect(wrapper.text()).not.toContain('Internal execution bookkeeping');
    wrapper.unmount();
  });
  it.each(['', '&view=Validation', '&node=source&view=Results'])(
    'opens retained evaluation evidence by default, preserving explicit node links: %s', async (selection) => {
      get.mockImplementation(async (url: string) => {
        if (url.endsWith('/evidence')) return { data: {
          ...structuredClone(fixture), node_statuses: { source: 'completed', model: 'completed', evaluation: 'completed' },
          evidence: { qualification: 'qualified', outputs: {
            __workflow__: { definition: { state: 'exact', storage: 'file' } },
            source: { default: { state: 'exact', storage: 'file' } },
            __diagnostics__: { evaluation: { state: 'exact', storage: 'file' } },
          } },
        } };
        if (url.endsWith('/__workflow__/definition')) return { data: { value: { schema_version: 1, nodes: [
          { node_id: 'source', node_type: 'data.file_load', label: 'Load Data', parameters: {} },
          { node_id: 'model', node_type: 'model.fitted_pls', label: 'PLS', parameters: {} },
          { node_id: 'evaluation', node_type: 'diagnostics.labeled_regression_evaluator', label: 'Test Evaluation', parameters: {} },
        ], edges: [] } } };
        if (url.endsWith('/__diagnostics__/evaluation')) return { data: { value: { rmse: 4.5, n_samples: 57 } } };
        if (url.endsWith('/source/default')) return { data: { value: [] } };
        throw new Error(`Unexpected evidence request: ${url}`);
      });
      const { wrapper, router } = await open('?project=1' + selection);
      expect(router.currentRoute.value.query.node).toBe(selection.includes('node=source') ? 'source' : 'evaluation');
      expect(wrapper.find('.inspection').exists()).toBe(true);
      if (!selection || selection.includes('Validation')) {
        expect(wrapper.text()).toContain('4.5');
        expect(wrapper.text()).not.toContain('No scientific output was retained');
      }
      expect(get.mock.calls.some(([url]) => String(url).includes('/workflows/'))).toBe(false);
      wrapper.unmount();
    },
  );
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
    expect((wrapper.get('[aria-label="Run name"]').element as HTMLInputElement).value).toBe('PLS — abc12345');
    expect(wrapper.get('.run-detail__identity').text()).not.toContain('Run #42');
    expect(wrapper.get('.summary').text()).toContain('PLS — abc12345');
    expect(wrapper.get('[aria-label="Workflow: Peak Find + PLS"]').text()).toBe('Workflow');
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
    expect(wrapper.find('.run-detail__heading h2').exists()).toBe(false);
    expect((wrapper.get('[aria-label="Run name"]').element as HTMLInputElement).value).toBe('Saved PCA');
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
      expect(wrapper.text()).toContain("Parameters used in this run");
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
    // Rounded for reading; the exact saved value stays in the tooltip.
    expect(wrapper.text()).toContain('1.2949');
    expect(wrapper.text()).not.toContain('1.2949488617445029');
    expect(wrapper.find('[title="1.2949488617445029"]').exists()).toBe(true);
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


describe('Inspect contributed header actions', () => {
  it('keeps Optimize in the header and responsive menu with the same scoped executor', async () => {
    installIdentifiedRuns();
    const execute = vi.fn().mockRejectedValue(new Error('Review is unavailable'));
    registerContextualActions('inspect-header-test', [{
      id: 'optimize', label: 'Optimize', icon: 'pi pi-chart-line',
      available: context => context.surface === 'run' && context.runId === 42,
      execute,
    }], () => true);
    try {
      const { wrapper } = await open('?project=1&view=Summary', true);
      const action = wrapper.get('[aria-label="Run actions"]').findAll('button').find(button => button.text() === 'Optimize');
      expect(action).toBeDefined();
      const menu = (wrapper.vm as unknown as { headerActions: { label: string; command: () => void }[] }).headerActions;
      menu.find(item => item.label === 'Optimize')!.command();
      await flushPromises();
      expect(execute).toHaveBeenCalledWith({ surface: 'run', projectId: 1, runId: 42 }, expect.any(AbortSignal));
      expect(wrapper.get('[role="alert"]').text()).toBe('Review is unavailable');
      expect(wrapper.get('[role="alert"]').element.closest('[aria-label="Run actions"]')).toBeNull();
      project.currentProjectId = 2;
      await flushPromises();
      expect((wrapper.vm as unknown as { headerActions: { label: string }[] }).headerActions.some(item => item.label === 'Optimize')).toBe(false);
    } finally {
      removeContextualActions('inspect-header-test');
    }
  });
});
