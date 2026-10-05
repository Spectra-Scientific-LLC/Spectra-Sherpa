import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import api from "@/api/client";
import { useDeployStore } from "@/stores/deploy";

vi.mock("@/api/client", () => ({ default: { get: vi.fn() } }));

const get = vi.mocked(api.get);

describe("deploy application projection", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    get.mockReset();
  });

  it("uses the durable application handle and keeps legacy binding fields separate", async () => {
    get.mockResolvedValue({
      data: [{
        handle: "app_saved_run_1",
        origin: "saved_run",
        state: "released",
        label: "Wine PLS-DA",
        workflow_id: 7,
        workflow_version_id: 4,
        source_run_id: 42,
        model_artifact_uid: "model-1",
        canonical_artifact_id: null,
      }],
    });

    const store = useDeployStore();
    await store.fetchApplications(3);

    expect(get).toHaveBeenCalledWith("/deploy/applications", { params: { project_id: 3 } });
    expect(store.applications).toEqual([expect.objectContaining({
      application_id: "app_saved_run_1",
      application_handle: "app_saved_run_1",
      artifact_uid: "model-1",
      source_run_id: 42,
      deploy_ready: true,
    })]);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("uses recorded campaign validation rather than portable origin for the star", async () => {
    get.mockResolvedValue({ data: [
      { handle: "verified", origin: "campaign_solution", workflow_id: 7, campaign_validation: { recorded: true } },
      { handle: "unknown", origin: "campaign_solution", workflow_id: 8 },
    ] });
    const store = useDeployStore();
    await store.fetchApplications(3);
    expect(store.applications.map(item => item.campaign_validation_recorded)).toEqual([true, false]);
  });

  it("falls back to legacy model and portable target reads during rollout", async () => {
    get
      .mockRejectedValueOnce({ response: { status: 404 } })
      .mockResolvedValueOnce({ data: [{
        artifact_uid: "model-2", name: "Wine PLS", workflow_id: 7,
        workflow_version_id: 5, is_deploy_ready: true,
      }] })
      .mockResolvedValueOnce({ data: [{
        canonical_artifact_id: 9, workflow_id: 8, name: "Imported PLS",
        artifact_digest: "abc", deploy_ready: true,
      }] });

    const store = useDeployStore();
    await store.fetchApplications(3);

    expect(store.applications.map((item) => item.application_id)).toEqual([
      "artifact:model-2", "canonical:9",
    ]);
    expect(store.applications.every((item) => item.application_handle == null)).toBe(true);
  });
});

it('scopes both operational collections to the active project', async () => {
  setActivePinia(createPinia()); get.mockReset();
  get.mockImplementation(async path=>({data:path === '/deploy/watches' ? [] : {runs:[],total:0}}));
  const store=useDeployStore();
  await store.fetchWatches(7); await store.fetchDeployRuns(undefined,undefined,7);
  expect(get).toHaveBeenCalledWith('/deploy/watches',{params:{project_id:7}});
  expect(get).toHaveBeenCalledWith('/deploy/runs',{params:{project_id:7}});
});

it.each(['watches','runs','applications'])('ignores old-project %s responses after a reset',async kind=>{
  setActivePinia(createPinia()); get.mockReset(); let finish!:(value:unknown)=>void;
  get.mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  const store=useDeployStore();
  const pending=kind === 'watches' ? store.fetchWatches(1) : kind === 'runs' ? store.fetchDeployRuns(undefined,undefined,1) : store.fetchApplications(1);
  store.resetProjectScope();
  finish({data:kind === 'watches' ? [{id:1}] : kind === 'runs' ? {runs:[{id:1}]} : [{handle:'old',workflow_id:1}]});
  await pending;
  expect(store.watches).toEqual([]); expect(store.deployRuns).toEqual([]); expect(store.applications).toEqual([]);
});

it('shows failed collection reads separately from a confirmed empty result and recovers',async()=>{
  setActivePinia(createPinia()); get.mockReset(); get.mockRejectedValue(new Error('offline'));
  const store=useDeployStore(); await store.fetchWatches(1); await store.fetchDeployRuns(undefined,undefined,1);
  expect(store.watchesError).toContain('could not be loaded'); expect(store.runsError).toContain('could not be loaded');
  get.mockImplementation(async path=>({data:path === '/deploy/watches' ? [] : {runs:[],total:0}}));
  await store.fetchWatches(1); await store.fetchDeployRuns(undefined,undefined,1);
  expect(store.watchesError).toBe(''); expect(store.runsError).toBe('');
});
