export const downloadBlob = (blob: Blob, filename: string): void => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};

export const blobFromResponseData = (
  data: Blob | ArrayBuffer | ArrayBufferView | string,
  mimeType?: string,
): Blob => {
  if (data instanceof Blob) {
    return data;
  }
  return new Blob([data], mimeType ? { type: mimeType } : undefined);
};

export const filenameFromContentDisposition = (
  disposition: string | undefined,
  fallback: string,
): string => {
  if (!disposition) return fallback;
  const encoded = disposition.match(/filename\*=UTF-8''([^;\r\n]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded).replace(/[\r\n]/g, "").trim() || fallback;
    } catch {
      return fallback;
    }
  }
  const quoted = disposition.match(/filename="([^"\r\n]*)"/i)?.[1];
  if (quoted) return quoted.trim() || fallback;
  const bare = disposition.match(/filename=([^;\r\n]*)/i)?.[1];
  return bare?.trim() || fallback;
};

export const downloadText = (
  text: string,
  filename: string,
  mimeType: string
): void => {
  downloadBlob(new Blob([text], { type: mimeType }), filename);
};

export const downloadJson = (data: unknown, filename: string): void => {
  const content = JSON.stringify(data, null, 2);
  downloadText(content, filename, "application/json");
};

const escapeCsvValue = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined) {
    return "";
  }
  const raw = String(value);
  if (raw.includes(",") || raw.includes("\n") || raw.includes('"')) {
    return `"${raw.replace(/"/g, '""')}"`;
  }
  return raw;
};

export const downloadCsv = (
  rows: Array<Array<string | number | null | undefined>>,
  filename: string
): void => {
  const lines = rows.map((row) => row.map(escapeCsvValue).join(","));
  downloadText(lines.join("\n"), filename, "text/csv");
};
