import { describe, expect, it } from "vitest";
import { blobFromResponseData } from "@/utils/download";

describe("blobFromResponseData", () => {
  it("copies ArrayBufferView slices before creating the Blob", async () => {
    const source = new Uint8Array([0, 1, 2, 3, 4, 5]);
    const slice = source.subarray(2, 5);

    const blob = blobFromResponseData(slice, "application/octet-stream");
    source.fill(9);

    expect(blob.type).toBe("application/octet-stream");
    expect(Array.from(new Uint8Array(await blob.arrayBuffer()))).toEqual([2, 3, 4]);
  });
});
