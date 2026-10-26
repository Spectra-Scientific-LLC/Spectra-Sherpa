import { createHash } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { downloadBlob, downloadText } from "@/utils/download";
import {
  downloadExportArtifact,
  extractExportArtifact,
  verifyExportArtifact,
  exportFilenameForFormat,
  exportDownloadReason,
  exportArtifactSummary,
} from "@/utils/exportArtifact";
import { buildNodeOutput } from "@/utils/nodeOutput";

vi.mock("@/utils/download", async (original) => ({ ...await original<typeof import("@/utils/download")>(), downloadText: vi.fn(), downloadBlob: vi.fn() }));

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
  beforeEach(() => vi.clearAllMocks());

  it("distinguishes plain and portable CSV, including historical prepared files", async () => {
    expect(exportFilenameForFormat("prepared.json", "portable_csv")).toBe("prepared.csv");
    expect(exportDownloadReason({ ...artifact, content: "#spectrasherpa-portable-csv/2 header" }, { format: "plain_csv", filename: "spectra.csv" })).toContain("plain CSV");
    expect(exportDownloadReason({ ...artifact, content: "#spectrasherpa-portable-csv/2 header" }, { format: "csv", filename: "spectra.csv" })).toBe("");
    await downloadExportArtifact({ ...artifact, format: "portable_csv" }, { format: "portable_csv", filename: "spectra.csv" });
    expect(downloadText).toHaveBeenCalledWith(content, "spectra.csv", "text/csv;charset=utf-8");
    expect(exportArtifactSummary(artifact)).toEqual({ label: "Prepared file: spectra.csv", rows: 1, cols: 2 });
    expect(exportArtifactSummary({ ...artifact, shape: [0, 1] })).toBeNull();
  });

  it.each(["csv", "json", "jdx"])("updates the filename to %s without changing the stem", (format) => {
    const suffix = format === "jdx" ? "zip" : format;
    expect(exportFilenameForFormat("my.preprocessed.csv", format)).toBe(`my.preprocessed.${suffix}`);
    expect(exportFilenameForFormat("preprocessed", format)).toBe(`preprocessed.${suffix}`);
  });

  it.each([
    { format: "json", filename: "spectra.json" },
    { format: "jdx", filename: "spectra.jdx" },
    { format: "csv", filename: "renamed.csv" },
  ])("refuses stale prepared bytes for changed settings %j", async (params) => {
    expect(exportDownloadReason(artifact, params)).toContain("Run this node");
    await expect(downloadExportArtifact(artifact, params)).rejects.toThrow("Export settings changed");
    expect(downloadText).not.toHaveBeenCalled();
  });

  it.each([
    ["csv", "text/csv;charset=utf-8", content],
    ["json", "application/json", '{"dataset":{"data":[[1,2]]}}'],
    ["jdx", "chemical/x-jcamp-dx", "##TITLE=Spectrum\n##JCAMP-DX=5.01\n##END=\n"],
  ])("downloads verified %s bytes with their matching filename and MIME type", async (format, mediaType, text) => {
    const prepared = { ...artifact, format, filename: `spectra.${format}`, media_type: mediaType,
      content: text, content_sha256: createHash("sha256").update(text).digest("hex"),
      byte_length: new TextEncoder().encode(text).byteLength };
    await downloadExportArtifact(prepared, { format, filename: prepared.filename });
    expect(downloadText).toHaveBeenCalledWith(text, prepared.filename, mediaType);
  });

  it("downloads binary JDX ZIP bytes, including when rerunning a legacy .jdx filename", async () => {
    const bytes = Buffer.from([80, 75, 3, 4, 0, 255, 128, 13, 10]);
    const zipped = { ...artifact, schema_version: "spectrasherpa-export-artifact/2",
      format: "jdx", filename: "spectra.zip", media_type: "application/zip", content_encoding: "base64",
      content: bytes.toString("base64"), byte_length: bytes.length,
      content_sha256: createHash("sha256").update(bytes).digest("hex"), shape: [3, 2] };
    const output = buildNodeOutput({ artifact: zipped }, [{ name: "artifact", type_ref: "spectrasherpa://types/ExportArtifact/1.0", required: true, label: "Prepared Export", variadic: false }]);
    expect(extractExportArtifact(output)).toBe(zipped);
    expect(output.ports?.artifact.metadata).not.toHaveProperty("content");
    await downloadExportArtifact(zipped, { format: "jdx", filename: "spectra.jdx" });
    const [blob, filename] = vi.mocked(downloadBlob).mock.calls[0]!;
    expect(filename).toBe("spectra.zip");
    expect(blob.type).toBe("application/zip");
    const read = new FileReader();
    const decoded = new Promise<ArrayBuffer>(resolve => { read.onload = () => resolve(read.result as ArrayBuffer); });
    read.readAsArrayBuffer(blob);
    expect(new Uint8Array(await decoded)).toEqual(new Uint8Array(bytes));
    expect(downloadText).not.toHaveBeenCalled();
    expect(exportDownloadReason(zipped, { format: "jdx", filename: "spectra.ZIP" })).toBe("");
    expect(exportDownloadReason(zipped, { format: "jdx", filename: "spectra.JDX" })).toBe("");
    expect(exportDownloadReason(zipped, { format: "jdx", filename: "spectra.csv" })).toContain("Run this node");
    for (const changes of [{ content: "!!" }, { content_sha256: "0".repeat(64) }, { byte_length: 1 },
      { content_encoding: "utf-8" }, { filename: "../spectra.zip" }, { schema_version: "spectrasherpa-export-artifact/1" }]) {
      await expect(verifyExportArtifact({ ...zipped, ...changes })).rejects.toThrow();
    }
  });

  it("verifies multi-megabyte binary content without overflowing the regexp stack", async () => {
    const bytes = Buffer.alloc(8_081_851, 171);
    const zipped = { ...artifact, schema_version: "spectrasherpa-export-artifact/2",
      format: "jdx", filename: "spectra.zip", media_type: "application/zip", content_encoding: "base64",
      content: bytes.toString("base64"), byte_length: bytes.length,
      content_sha256: createHash("sha256").update(bytes).digest("hex"), shape: [100, 2000] };
    await expect(verifyExportArtifact(zipped)).resolves.toEqual(zipped);
  });

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
