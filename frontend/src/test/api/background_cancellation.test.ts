import { beforeEach, describe, expect, it, vi } from "vitest";
import { AxiosError, CanceledError } from "axios";
import api from "@/api/client";

const notify = vi.hoisted(() => vi.fn());
vi.mock("@/composables/useNotifier", () => ({
  useNotifier: () => ({ notifySystemEvent: notify, notifyDeployOutcome: notify }),
}));

beforeEach(() => notify.mockClear());

describe("background cancellation notifications", () => {
  it("keeps cancellation rejected for its owner without reporting a network failure", async () => {
    await expect(api.get("/experiments", {
      adapter: async (config) => { throw new CanceledError("canceled", config); },
    })).rejects.toMatchObject({ code: "ERR_CANCELED" });
    expect(notify).not.toHaveBeenCalled();
  });

  it("still reports a genuine experiment inventory network failure", async () => {
    await expect(api.get("/experiments", {
      adapter: async (config) => { throw new AxiosError("offline", "ERR_NETWORK", config); },
    })).rejects.toMatchObject({ code: "ERR_NETWORK" });
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({
      title: "Background Sync Error",
      message: "Network error while syncing /experiments.",
    }));
  });
});
