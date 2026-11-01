// Display adapter for the backend's bounded read-only projection. This is a
// view model, not a second inclusion authority or a copy of the source rows.
export function retainedPopulationView(value: unknown, runId: number): {
  rows: Array<{ label: string; value: string }>;
  sources: Array<{ nodeId: string; available: boolean; sourceCount: number | null; usedCount: number | null; excludedCount: number | null }>;
} | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  if (record.schema_version !== 'spectrasherpa-retained-population-summary/1'
    || record.run_id !== runId || !Array.isArray(record.rows) || !Array.isArray(record.sources)
    || record.sources.length > 32 || record.rows.length > 68) return null;
  const rows: Array<{ label: string; value: string }> = [];
  const sources: Array<{ nodeId: string; available: boolean; sourceCount: number | null; usedCount: number | null; excludedCount: number | null }> = [];
  for (const row of record.rows) {
    if (!row || typeof row.label !== 'string' || typeof row.value !== 'string') return null;
    rows.push({ label: row.label, value: row.value });
  }
  for (const source of record.sources) {
    if (!source || typeof source.node_id !== 'string' || source.port !== 'exclusions'
      || !['available', 'unavailable'].includes(source.availability)) return null;
    const available = source.availability === 'available';
    if (available && (![source.source_count, source.active_count, source.excluded_count].every(
      count => Number.isSafeInteger(count) && count >= 0,
    ) || source.active_count + source.excluded_count !== source.source_count)) return null;
    sources.push({ nodeId: source.node_id, available,
      sourceCount: available ? source.source_count : null,
      usedCount: available ? source.active_count : null,
      excludedCount: available ? source.excluded_count : null });
  }
  return { rows, sources };
}
