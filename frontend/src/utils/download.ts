export const downloadBlob = (blob: Blob, filename: string): void => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
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
  if (raw.includes(",") || raw.includes("\n") || raw.includes("\"")) {
    return `"${raw.replace(/\"/g, "\"\"")}"`;
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
