import { downloadText } from "@/utils/download";

const EXPORT_ARTIFACT_SCHEMA = "spectrasherpa-export-artifact/1";
const MAX_EXPORT_BYTES = 32 * 1024 * 1024;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const FORMAT_CONTRACT = {
  csv: { suffix: ".csv", mediaType: "text/csv;charset=utf-8" },
  json: { suffix: ".json", mediaType: "application/json" },
  jdx: { suffix: ".jdx", mediaType: "chemical/x-jcamp-dx" },
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

export interface ExportArtifact {
  schema_version: typeof EXPORT_ARTIFACT_SCHEMA;
  filename: string;
  format: ExportFormat;
  media_type: string;
  content_encoding: "utf-8";
  content: string;
  content_sha256: string;
  byte_length: number;
  source_digest: string;
  shape: [number, number];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

const safeFilename = (filename: unknown, format: ExportFormat): filename is string => {
  if (typeof filename !== "string" || filename.length === 0 || filename.trim() !== filename)
    return false;
  if (filename.length > 128 || filename === "." || filename === "..") return false;
  if (filename.includes("/") || filename.includes("\\") || filename.includes("\0")) return false;
  return filename.toLowerCase().endsWith(FORMAT_CONTRACT[format].suffix);
};

const sha256Hex = async (content: string): Promise<string> => {
  if (!globalThis.crypto?.subtle) {
    throw new Error("This browser cannot verify SHA-256 export evidence");
  }
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(content),
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
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
  if (value.schema_version !== EXPORT_ARTIFACT_SCHEMA)
    throw new Error("Prepared export schema is unsupported");
  if (typeof value.format !== "string" || !(value.format in FORMAT_CONTRACT)) {
    throw new Error("Prepared export format is invalid");
  }
  const format = value.format as ExportFormat;
  if (!safeFilename(value.filename, format))
    throw new Error("Prepared export filename is unsafe or mismatched");
  if (
    value.media_type !== FORMAT_CONTRACT[format].mediaType ||
    value.content_encoding !== "utf-8"
  ) {
    throw new Error("Prepared export media contract is invalid");
  }
  if (typeof value.content !== "string")
    throw new Error("Prepared export content must be UTF-8 text");
  const bytes = new TextEncoder().encode(value.content);
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
    value.content_sha256 !== (await sha256Hex(value.content))
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

export const downloadExportArtifact = async (value: unknown): Promise<ExportArtifact> => {
  const artifact = await verifyExportArtifact(value);
  downloadText(artifact.content, artifact.filename, artifact.media_type);
  return artifact;
};
