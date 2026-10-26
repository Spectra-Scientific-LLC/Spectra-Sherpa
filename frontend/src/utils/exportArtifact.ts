import { blobFromResponseData, downloadBlob, downloadText } from "@/utils/download";

const EXPORT_ARTIFACT_SCHEMA = "spectrasherpa-export-artifact/1";
const ZIP_EXPORT_ARTIFACT_SCHEMA = "spectrasherpa-export-artifact/2";
const MAX_EXPORT_BYTES = 32 * 1024 * 1024;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const FORMAT_CONTRACT = {
  csv: { suffix: ".csv", mediaType: "text/csv;charset=utf-8" },
  plain_csv: { suffix: ".csv", mediaType: "text/csv;charset=utf-8" },
  portable_csv: { suffix: ".csv", mediaType: "text/csv;charset=utf-8" },
  json: { suffix: ".json", mediaType: "application/json" },
  jdx: { suffix: ".zip", mediaType: "application/zip" },
} as const;
const ARTIFACT_FIELDS = new Set([
  "schema_version",
  "filename",
  "format",
  "media_type",
  "content_encoding",
  "content",
  "content_sha256",
  "byte_length",
  "source_digest",
  "shape",
]);

type ExportFormat = keyof typeof FORMAT_CONTRACT;
export const EXPORT_FORMAT_LABELS: Record<ExportFormat, string> = { plain_csv: "CSV (plain)", csv: "CSV (legacy; choose format)", portable_csv: "CSV (portable)", json: "JSON", jdx: "JCAMP-DX (ZIP)" };

/** Summary only; downloads still verify the complete closed artifact and digest. */
export function exportArtifactSummary(value: unknown): { label: string; rows: number; cols: number } | null {
  if (!isRecord(value) || ![EXPORT_ARTIFACT_SCHEMA, ZIP_EXPORT_ARTIFACT_SCHEMA].includes(String(value.schema_version)) ||
      typeof value.filename !== "string" || !Array.isArray(value.shape) || value.shape.length !== 2 ||
      !value.shape.every(n => Number.isSafeInteger(n) && n > 0)) return null;
  return { label: `Prepared file: ${value.filename}`, rows: value.shape[0], cols: value.shape[1] };
}

/** Update only the filename suffix when the user explicitly changes format. */
export function exportFilenameForFormat(filename: unknown, format: unknown): string | null {
  if (typeof filename !== "string" || typeof format !== "string" || !(format in FORMAT_CONTRACT)) return null;
  const suffix = FORMAT_CONTRACT[format as ExportFormat].suffix;
  if (filename.toLowerCase().endsWith(suffix)) return filename;
  return filename.replace(/\.[^./\\]+$/, "") + suffix;
}

/** Retained bytes are never reformatted or renamed by the download surface. */
export function exportDownloadReason(value: unknown, params: Record<string, unknown>): string {
  if (!isRecord(value)) return "Run this node to prepare a file.";
  if (params.format === "plain_csv" && typeof value.content === "string" && value.content.startsWith("#spectrasherpa-portable-csv/")) {
    return "Run this node to prepare plain CSV. The retained file uses the older portable CSV format.";
  }
  const filename = value.schema_version === ZIP_EXPORT_ARTIFACT_SCHEMA && params.format === "jdx"
    ? (typeof params.filename === "string" && /\.(zip|jdx)$/i.test(params.filename)
      ? params.filename.replace(/\.(zip|jdx)$/i, ".zip") : null) : params.filename;
  if (value.format !== params.format || value.filename !== filename) {
    return "Export settings changed. Run this node to prepare the selected file.";
  }
  return "";
}

export interface ExportArtifact {
  schema_version: typeof EXPORT_ARTIFACT_SCHEMA | typeof ZIP_EXPORT_ARTIFACT_SCHEMA;
  filename: string;
  format: ExportFormat;
  media_type: string;
  content_encoding: "utf-8" | "base64";
  content: string;
  content_sha256: string;
  byte_length: number;
  source_digest: string;
  shape: [number, number];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

const safeFilename = (filename: unknown, suffix: string): filename is string => {
  if (typeof filename !== "string" || filename.length === 0 || filename.trim() !== filename)
    return false;
  if (filename.length > 128 || filename === "." || filename === "..") return false;
  if (filename.includes("/") || filename.includes("\\") || filename.includes("\0")) return false;
  return filename.toLowerCase().endsWith(suffix);
};

const sha256Hex = async (bytes: Uint8Array): Promise<string> => {
  if (!globalThis.crypto?.subtle) {
    throw new Error("This browser cannot verify SHA-256 export evidence");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new Uint8Array(bytes).buffer,
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
};

const artifactBytes = (content: string, zipped: boolean): Uint8Array => {
  if (!zipped) return new TextEncoder().encode(content);
  if (content.length > 4 * Math.ceil(MAX_EXPORT_BYTES / 3) ||
      content.length % 4 !== 0 || /[^A-Za-z0-9+/=]/.test(content)) {
    throw new Error("Prepared export base64 is invalid or too large");
  }
  // atob validates padding without a repeated-group regex that overflows the
  // browser's regexp stack on valid multi-megabyte archives.
  return Uint8Array.from(atob(content), (character) => character.charCodeAt(0));
};

export const extractExportArtifact = (nodeOutput: unknown): unknown => {
  if (!isRecord(nodeOutput)) return null;
  const ports = nodeOutput.ports;
  if (isRecord(ports) && isRecord(ports.artifact) && "value" in ports.artifact) {
    return ports.artifact.value;
  }
  if (isRecord(nodeOutput.artifact)) return nodeOutput.artifact;
  return null;
};

export const verifyExportArtifact = async (value: unknown): Promise<ExportArtifact> => {
  if (!isRecord(value) || Object.keys(value).length !== ARTIFACT_FIELDS.size) {
    throw new Error("Prepared export does not use the closed artifact schema");
  }
  for (const field of Object.keys(value)) {
    if (!ARTIFACT_FIELDS.has(field)) throw new Error("Prepared export contains an unknown field");
  }
  if (value.schema_version !== EXPORT_ARTIFACT_SCHEMA && value.schema_version !== ZIP_EXPORT_ARTIFACT_SCHEMA)
    throw new Error("Prepared export schema is unsupported");
  if (typeof value.format !== "string" || !(value.format in FORMAT_CONTRACT)) {
    throw new Error("Prepared export format is invalid");
  }
  const format = value.format as ExportFormat;
  const zipped = value.schema_version === ZIP_EXPORT_ARTIFACT_SCHEMA;
  if (zipped && format !== "jdx") throw new Error("ZIP export requires JCAMP-DX format");
  const suffix = format === "jdx" && !zipped ? ".jdx" : FORMAT_CONTRACT[format].suffix;
  const mediaType = format === "jdx" && !zipped ? "chemical/x-jcamp-dx" : FORMAT_CONTRACT[format].mediaType;
  if (!safeFilename(value.filename, suffix))
    throw new Error("Prepared export filename is unsafe or mismatched");
  if (
    value.media_type !== mediaType ||
    value.content_encoding !== (zipped ? "base64" : "utf-8")
  ) {
    throw new Error("Prepared export media contract is invalid");
  }
  if (typeof value.content !== "string")
    throw new Error("Prepared export content must be UTF-8 text");
  const bytes = artifactBytes(value.content, zipped);
  if (
    bytes.byteLength > MAX_EXPORT_BYTES ||
    typeof value.byte_length !== "number" ||
    !Number.isInteger(value.byte_length) ||
    value.byte_length !== bytes.byteLength
  ) {
    throw new Error("Prepared export byte length is invalid");
  }
  if (
    typeof value.content_sha256 !== "string" ||
    !SHA256_PATTERN.test(value.content_sha256) ||
    value.content_sha256 !== (await sha256Hex(bytes))
  ) {
    throw new Error("Prepared export content digest does not match");
  }
  if (typeof value.source_digest !== "string" || !SHA256_PATTERN.test(value.source_digest)) {
    throw new Error("Prepared export source digest is invalid");
  }
  if (
    !Array.isArray(value.shape) ||
    value.shape.length !== 2 ||
    !value.shape.every((size) => typeof size === "number" && Number.isInteger(size) && size > 0)
  ) {
    throw new Error("Prepared export shape is invalid");
  }
  return value as unknown as ExportArtifact;
};

export const downloadExportArtifact = async (value: unknown, params?: Record<string, unknown>): Promise<ExportArtifact> => {
  if (params) {
    const reason = exportDownloadReason(value, params);
    if (reason) throw new Error(reason);
  }
  const artifact = await verifyExportArtifact(value);
  if (artifact.content_encoding === "base64") {
    downloadBlob(blobFromResponseData(artifactBytes(artifact.content, true), artifact.media_type), artifact.filename);
  } else {
    downloadText(artifact.content, artifact.filename, artifact.media_type);
  }
  return artifact;
};
