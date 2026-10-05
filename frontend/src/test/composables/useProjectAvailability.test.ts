import { flushPromises } from "@vue/test-utils";
import { effectScope, nextTick, reactive, ref } from "vue";
import { beforeEach, expect, it, vi } from "vitest";
import { useProjectAvailability } from "@/composables/useProjectAvailability";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
const project = reactive({ currentProjectId: 3 as number | null });
const mode = ref("enterprise");
const profile = ref("pro");
vi.mock("@/api", () => ({ api: { get: mocks.get } }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => project }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => ({ user: { id: 7 } }) }));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({ appMode: mode, siteProfile: profile }) }));

beforeEach(() => {
  project.currentProjectId = 3;
  mode.value = "enterprise";
  profile.value = "pro";
  mocks.get.mockReset();
});

it.each(["success", "failure"])("ignores stale %s while checking a newly selected project", async outcome => {
  let finish!: (value: unknown) => void;
  let fail!: (reason: Error) => void;
  let finishNew!: (value: unknown) => void;
  mocks.get.mockReturnValueOnce(new Promise((resolve, reject) => { finish = resolve; fail = reject; }))
    .mockReturnValueOnce(new Promise(resolve => { finishNew = resolve; }));
  const scope = effectScope();
  const state = scope.run(() => useProjectAvailability())!;
  project.currentProjectId = 4;
  await nextTick();
  if (outcome === "success") finish({ data: { write: true } });
  else fail(new Error("Old project unavailable"));
  await flushPromises();
  expect(state.loading.value).toBe(true);
  expect(state.availability.value).toBeNull();
  expect(state.error.value).toBe("");
  finishNew({ data: { write: false } });
  await flushPromises();
  expect(state.loading.value).toBe(false);
  expect(state.availability.value?.write).toBe(false);
  scope.stop();
});

it("clears pending access when no project is selected", async () => {
  let finish!: (value: unknown) => void;
  mocks.get.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const scope = effectScope();
  const state = scope.run(() => useProjectAvailability())!;
  project.currentProjectId = null;
  await nextTick();
  expect(state.loading.value).toBe(false);
  finish({ data: { write: true } });
  await flushPromises();
  expect(state.availability.value).toBeNull();
  scope.stop();
});

it.each(["local", "demo"])("does not add a project access requirement to %s", async target => {
  if (target === "local") mode.value = "local";
  profile.value = target;
  const scope = effectScope();
  const state = scope.run(() => useProjectAvailability())!;
  await flushPromises();
  expect(state.qualified.value).toBe(false);
  expect(state.loading.value).toBe(false);
  expect(mocks.get).not.toHaveBeenCalled();
  scope.stop();
});
