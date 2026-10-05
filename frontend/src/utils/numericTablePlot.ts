/** Presentation only: no peak detection, consensus grouping, or imputation. */
export function numericTableColumns(value: unknown): string[] {
  const record = value as { data?: unknown; metadata?: Record<string, unknown> } | null;
  const rows = record?.data;
  if (!Array.isArray(rows) || !rows.length) return [];
  if (rows.every(row => row !== null && typeof row === "object" && !Array.isArray(row))) {
    const keys = [...new Set(rows.flatMap(row => Object.keys(row)))];
    return keys;
  }
  if (!Array.isArray(rows[0]) || !rows[0].length) return [];
  const width = rows[0].length;
  if (rows.some(row => !Array.isArray(row) || row.length !== width)) return [];
  const names = record?.metadata?.column_names;
  return Array.isArray(names) && names.length === width
    ? names.map(String) : Array.from({ length: width }, (_, i) => `Column ${i + 1}`);
}

export function numericTableColumnPlot(value: unknown, index: number) {
  const names = numericTableColumns(value);
  if (!Number.isInteger(index) || !names[index]) return null;
  const record = value as { data: ((number | null)[] | Record<string, unknown>)[]; metadata?: Record<string, unknown> };
  const labels = record.metadata?.sample_labels;
  const hasLabels = Array.isArray(labels) && labels.length === record.data.length;
  const units = record.metadata?.column_units as Record<string, string> | undefined;
  const title = names[index] + (units?.[names[index]] ? ` (${units[names[index]]})` : "");
  const values = record.data.map(row => Array.isArray(row) ? row[index] : row[names[index]]);
  const structured = values.some(cell => cell !== null && typeof cell === "object");
  const categorical = values.some(cell => typeof cell === "string" || typeof cell === "boolean");
  const y = values.map(cell => {
    if (cell == null || (typeof cell === "number" && !Number.isFinite(cell))) return null;
    if (structured) return null;
    return categorical ? String(cell) : cell;
  });
  const notice = structured ? "This column contains nested records or lists. Inspect it in Data View."
    : y.every(cell => cell === null) ? "No observed values in this column (all values are missing)." : null;
  return {
    data: [{ type: "scatter", mode: "markers", name: names[index],
      x: record.data.map((_, i) => i + 1), y,
      ...(hasLabels ? { text: labels } : {}),
      connectgaps: false, hovertemplate: `Row %{x}<br>${hasLabels ? "%{text}<br>" : ""}%{y}<extra>%{fullData.name}</extra>` }],
    layout: { xaxis: { title: "Row index" }, yaxis: { title, ...(categorical ? { type: "category" } : {}) }, title: { text: title },
      ...(notice ? { annotations: [{ text: notice, x: 0.5, y: 0.5, xref: "paper", yref: "paper", showarrow: false }] } : {}) },
  };
}
