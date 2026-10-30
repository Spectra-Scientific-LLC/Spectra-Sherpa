import { describe, expect, it, vi } from "vitest";
import {
  clearRetainedInspection,
  retainedInspection,
  retainedDatasetWorkspace,
  retainCompleteSource,
  retainCompletePackage,
  retainedCompletePackage,
  retainedCompleteSource,
} from "@/utils/retainedInspection";

describe("retained inspection reads", () => {
  it("requires an exact source object and account/project/file binding", () => {
    const source = { n_samples: 1, n_features: 1, data: [[1]] };
    const scope = "user1:project2:experiment3:files4";
    expect(retainedCompleteSource(source, scope)).toBeNull();
    retainCompleteSource(source, scope);
    expect(retainedCompleteSource(source, scope)).toBe(source);
    expect(retainedCompleteSource({ ...source }, scope)).toBeNull();
    expect(retainedCompleteSource(source, "user2:project2:experiment3:files4")).toBeNull();
    expect(retainedCompleteSource(source, "user1:project5:experiment3:files4")).toBeNull();
    clearRetainedInspection(source);
    expect(retainedCompleteSource(source, scope)).toBeNull();
  });
  it("invalidates package receipts on object, source scope, refresh and account changes", () => {
    const owner = {};
    const dataset = {n_samples: 1, n_features: 1, data: [[1]]};
    const views = [dataset, {...dataset}];
    retainedDatasetWorkspace(owner, 'user1:project1').set(1, dataset);
    retainCompletePackage(dataset, views, 'user1:project1:files-a');
    expect(retainedCompletePackage(dataset, 'user1:project1:files-a')).toBe(views);
    expect(retainedCompletePackage({...dataset}, 'user1:project1:files-a')).toBeNull();
    expect(retainedCompletePackage(dataset, 'user1:project1:files-b')).toBeNull();
    retainedDatasetWorkspace(owner, 'user2:project1');
    expect(retainedCompletePackage(dataset, 'user1:project1:files-a')).toBeNull();
    retainCompletePackage(dataset, views, 'user2:project1:files-a');
    clearRetainedInspection(dataset);
    expect(retainedCompletePackage(dataset, 'user2:project1:files-a')).toBeNull();
  });
  it("retains workspace sources across routes and clears them on scope changes", () => {
    const owner = {};
    const workspace = retainedDatasetWorkspace(owner, "user-1:project-1");
    workspace.set(1, { n_samples: 1, n_features: 1, data: [[1]] });
    expect(retainedDatasetWorkspace(owner, "user-1:project-1")).toBe(workspace);
    expect(retainedDatasetWorkspace({}, "user-1:project-1").size).toBe(0);
    expect(retainedDatasetWorkspace(owner, "user-2:project-1").size).toBe(0);
    expect(workspace.size).toBe(0);
  });
  it("shares in-flight and completed reads for the same retained object and selection", async () => {
    const dataset = {};
    const read = vi.fn().mockResolvedValue({ rows: [1, 2] });
    const first = retainedInspection(dataset, "selection:1,2", read);
    expect(retainedInspection(dataset, "selection:1,2", read)).toBe(first);
    const value = await first;
    expect(await retainedInspection(dataset, "selection:1,2", read)).toBe(value);
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("isolates changed selections, replaced datasets, and explicit refreshes", async () => {
    const dataset = {};
    const read = vi.fn().mockResolvedValue({});
    await retainedInspection(dataset, "selection:1", read);
    await retainedInspection(dataset, "selection:2", read);
    await retainedInspection({}, "selection:1", read);
    clearRetainedInspection(dataset);
    await retainedInspection(dataset, "selection:1", read);
    expect(read).toHaveBeenCalledTimes(4);
  });

  it("retries failed reads rather than retaining an error", async () => {
    const dataset = {};
    const read = vi.fn().mockRejectedValueOnce(new Error("unavailable")).mockResolvedValue("ok");
    await expect(retainedInspection(dataset, "axes", read)).rejects.toThrow("unavailable");
    expect(await retainedInspection(dataset, "axes", read)).toBe("ok");
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("bounds retained selection history", async () => {
    const dataset = {};
    const read = vi.fn().mockResolvedValue({});
    for (let index = 0; index < 25; index++) await retainedInspection(dataset, String(index), read);
    await retainedInspection(dataset, "0", read);
    expect(read).toHaveBeenCalledTimes(26);
  });
});
