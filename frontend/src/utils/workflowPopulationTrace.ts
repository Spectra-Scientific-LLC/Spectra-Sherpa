import { SCIENTIFIC_COLORS } from "@/theme/plotTheme";
import type { WorkflowPopulationActions } from "@/utils/workflowPopulation";

type Trace = Record<string, unknown>;
export function traceObservationRefs(trace: Trace): string[] {
  const refs = (trace.meta as Record<string, unknown> | undefined)?.workflow_observation_refs;
  return Array.isArray(refs) && refs.every(ref => typeof ref === "string") ? refs : [];
}

/** Shared by every Plotly surface, including exports. Never changes values. */
export function displayObservationTraces(traces: Trace[], actions?: WorkflowPopulationActions | null,
  selected: ReadonlySet<string> = new Set()): Trace[] {
  let excluded = false;
  const resolved = new Map<string, boolean>();
  const displayed = traces.map(trace => {
    const refs = traceObservationRefs(trace);
    if (!refs.length) return trace;
    const retained = (trace.meta as Record<string, unknown>).workflow_included as boolean[];
    const flags = refs.map((ref, i) => {
      if (!resolved.has(ref)) resolved.set(ref, actions?.resolve(ref)?.excluded === true);
      return resolved.get(ref) || retained?.[i] === false;
    });
    const selection = selected.size ? { selectedpoints: refs.flatMap((ref, i) => selected.has(ref) ? [i] : []),
      selected: { marker: { opacity: 1 } }, unselected: { marker: { opacity: 0.35 } } } : {};
    if (!flags.some(Boolean)) return { ...trace, ...selection };
    excluded = true;
    const marker = (trace.marker ?? {}) as Record<string, unknown>;
    const original = (value: unknown, i: number, fallback: unknown) => Array.isArray(value) ? value[i] : value ?? fallback;
    const line = trace.line as Record<string, unknown> | undefined;
    const allExcluded = flags.every(Boolean);
    // Numeric colors are measurements, not categorical style names. Keep the
    // scale and hover values intact; the open cross identifies exclusion.
    const numericColor = typeof marker.color === "number" || (Array.isArray(marker.color)
      && marker.color.some(value => typeof value === "number"));
    return { ...trace, ...selection,
      mode: allExcluded && trace.mode === "lines" ? "lines+markers" : trace.mode,
      marker: { ...marker,
        symbol: flags.map((flag, i) => flag ? "x-open" : original(marker.symbol, i, "circle")),
        color: numericColor ? marker.color
          : flags.map((flag, i) => flag ? SCIENTIFIC_COLORS.excluded : original(marker.color, i, SCIENTIFIC_COLORS.observation)),
      },
      ...(line && allExcluded ? { line: { ...line, color: SCIENTIFIC_COLORS.excluded, dash: "dot" } } : {}),
    };
  });
  if (excluded) displayed.push({ type: "scatter", mode: "markers", x: [null], y: [null],
    name: "Excluded / not in fit", hoverinfo: "skip", marker: { symbol: "x-open", color: SCIENTIFIC_COLORS.excluded, size: 10 } });
  return displayed;
}
