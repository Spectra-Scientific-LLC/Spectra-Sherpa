import { createHash } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { downloadText } from "@/utils/download";
import {
  downloadExportArtifact,
  extractExportArtifact,
  verifyExportArtifact,
} from "@/utils/exportArtifact";
import { buildNodeOutput } from "@/utils/nodeOutput";

vi.mock("@/utils/download", () => ({ downloadText: vi.fn() }));

const content = "sample,1000,1001\nsample-1,1,2\n";
const artifact = {
  schema_version: "spectrasherpa-export-artifact/1",
  filename: "spectra.csv",
  format: "csv",
  media_type: "text/csv;charset=utf-8",
  content_encoding: "utf-8",
  content,
  content_sha256: createHash("sha256").update(content).digest("hex"),
  byte_length: new TextEncoder().encode(content).byteLength,
  source_digest: "1".repeat(64),
  shape: [1, 2],
};

describe("canonical export artifacts", () => {
  beforeEach(() => vi.mocked(downloadText).mockClear());

  it("extracts the prepared artifact from the typed output port", () => {
    const output = buildNodeOutput({ artifact }, [
      {
        name: "artifact",
        type_ref: "spectrasherpa://types/ExportArtifact/1.0",
        required: true,
        label: "Prepared Export",
        variadic: false,
      },
    ]);

    expect(extractExportArtifact(output)).toBe(artifact);
    expect(output.ports?.artifact.metadata).not.toHaveProperty("content");
    expect(output.ports?.artifact.metadata.content_sha256).toBe(artifact.content_sha256);
  });

  it("verifies the exact digest before downloading the prepared bytes", async () => {
    await expect(downloadExportArtifact(artifact)).resolves.toEqual(artifact);
    expect(downloadText).toHaveBeenCalledWith(content, "spectra.csv", "text/csv;charset=utf-8");
  });

  it.each([
    ["tampered content", { ...artifact, content: `${content}forged` }],
    ["unsafe filename", { ...artifact, filename: "../spectra.csv" }],
    ["unknown field", { ...artifact, claimed_verified: true }],
    ["wrong format suffix", { ...artifact, filename: "spectra.json" }],
    ["false byte length", { ...artifact, byte_length: 1 }],
    ["false source digest", { ...artifact, source_digest: "unbound" }],
  ])("rejects %s", async (_label, forged) => {
    await expect(verifyExportArtifact(forged)).rejects.toThrow();
    expect(downloadText).not.toHaveBeenCalled();
  });
});
