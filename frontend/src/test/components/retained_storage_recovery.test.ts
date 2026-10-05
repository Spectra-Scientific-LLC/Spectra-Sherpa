import { mount, flushPromises } from "@vue/test-utils";
import { beforeEach, expect, it, vi } from "vitest";
import Recovery from "@/components/RetainedStorageRecovery.vue";
const reclaim = vi.hoisted(() => vi.fn());
vi.mock("@/stores/runs", () => ({ useRunsStore: () => ({ reclaimStorage: reclaim }) }));
beforeEach(() => vi.clearAllMocks());
const open = () => mount(Recovery, { global: { stubs: {
  Button: { emits: ["click"], props: ["label"], template: '<button @click="$emit(\'click\')">{{label}}</button>' },
} } });
it("needs no project or model listing and discloses retained storage and grace", async () => {
  reclaim.mockResolvedValue({ removed_files: 1, used_bytes: 1048576, quota_bytes: 2097152, grace_seconds: 86400 });
  const view = open();
  expect(reclaim).not.toHaveBeenCalled();
  await view.get("button").trigger("click"); await flushPromises();
  expect(reclaim).toHaveBeenCalledOnce();
  expect(view.get('[role="status"]').text()).toContain("1.00 MiB of 2.00 MiB");
  expect(view.text()).toContain("24 hours");
  expect(view.text()).toContain("saved runs and their shared outputs remain intact");
});
it("does not claim recovery after a server refusal", async () => {
  reclaim.mockRejectedValue(new Error("invalid inventory"));
  const view = open();
  expect(reclaim).not.toHaveBeenCalled();
  await view.get("button").trigger("click"); await flushPromises();
  expect(view.get('[role="status"]').text()).toContain("No success was confirmed");
});
