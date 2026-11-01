import { observationAxisRefs, populationPlotOutput, type WorkflowPopulation } from "@/utils/workflowPopulation";
import type { NodeOutput } from "@/utils/nodeOutput";
import { observationOutputAxis, observationOutputRowCount } from "@/utils/observationOutputMembership";

type TableRow = Record<string, unknown>;

/** Add inspectable excluded identities to the existing table, never numerical
 * predictions or fitted values. The declared display cohort bounds branch scope. */
export function tableExclusionRows(output: NodeOutput, rows: TableRow[], refs: string[],
  membership: ReadonlyMap<string, boolean>, populations: WorkflowPopulation[], limit: number, offset = 0): TableRow[] {
  const sourceRows = new Map(populations.flatMap(population => population.rows.map(row => [row.observation_ref, row] as const)));
  const computedRows = rows.map((row, index) => ({ ...row, _observation_ref: refs[index + offset],
    _label_full: row._label_full || sourceRows.get(refs[index + offset])?.sample_label || "",
    _usedInResult: membership.get(refs[index + offset]), _source_row: sourceRows.get(refs[index + offset])?.source_row }));
  if (offset > 0) return computedRows;
  const display = populationPlotOutput(output);
  const displayRefs = observationAxisRefs(observationOutputAxis(display), observationOutputRowCount(display));
  // A partial or unrelated display projection cannot establish omitted rows.
  const displaySet = new Set(displayRefs ?? []);
  if (!displayRefs || refs.some(reference => !displaySet.has(reference))) return computedRows;
  const missing: TableRow[] = [];
  const excludedBudget = limit > 0 && computedRows.length ? Math.max(1, Math.floor(limit / 3)) : limit;
  const numericKeys = Object.keys(rows[0] ?? {}).filter(key => key.startsWith("col_") || key === "value");
  for (const reference of displayRefs) {
    const source = sourceRows.get(reference);
    if (membership.has(reference) || !source || source.included) continue;
    missing.push({
      _index: null, _label_full: source.sample_label ?? source.sample_id ?? "", _label: source.sample_label ?? source.sample_id ?? "",
      _label_0: source.sample_label ?? source.sample_id ?? "", _observation_ref: reference,
      _usedInResult: false, _source_row: source.source_row,
      ...(typeof rows[0]?.Sample === "string" ? { Sample: source.sample_label ?? source.sample_id ?? "" } : {}),
      ...(typeof rows[0]?.sample === "string" ? { sample: source.sample_label ?? source.sample_id ?? "" } : {}),
      ...Object.fromEntries(numericKeys.map(key => [key, null])),
    });
    if (excludedBudget > 0 && missing.length >= excludedBudget) break;
  }
  const displayed = [...missing, ...computedRows];
  return limit > 0 ? displayed.slice(0, limit) : displayed;
}
