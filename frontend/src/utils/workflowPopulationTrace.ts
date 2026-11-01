import { SCIENTIFIC_COLORS } from "@/theme/plotTheme";
import type { WorkflowPopulationActions } from "@/utils/workflowPopulation";

type Trace = Record<string, unknown>;
/** A scalar identifies the whole observed spectrum, not a particular wavelength. */
export function compactObservationRef(trace: Trace): string | null {
  const meta = trace.meta as Record<string, unknown> | undefined;
  const ref = meta?.workflow_observation_ref;
  return typeof ref === "string" && ref.length > 0 && ref === ref.trim()
    && !Object.prototype.hasOwnProperty.call(meta, "workflow_observation_refs")
    && typeof meta?.workflow_included === "boolean"
    && (trace.type === "scatter" || trace.type === "bar")
    && Array.isArray(trace.x) && Array.isArray(trace.y) && trace.x.length === trace.y.length ? ref : null;
}

export function traceObservationRefs(trace: Trace): string[] {
  const meta = trace.meta as Record<string, unknown> | undefined;
  if (meta && Object.prototype.hasOwnProperty.call(meta, "workflow_observation_ref")) {
    const ref = compactObservationRef(trace);
    return ref === null ? [] : Array((trace.x as unknown[]).length).fill(ref);
  }
  const refs = meta?.workflow_observation_refs;
  return Array.isArray(refs) && refs.every(ref => typeof ref === "string") ? refs : [];
}

export function traceObservationIncluded(trace: Trace, index: number): boolean | undefined {
  const meta = trace.meta as Record<string, unknown> | undefined;
  const included = compactObservationRef(trace) !== null ? meta?.workflow_included
    : Array.isArray(meta?.workflow_included) ? meta.workflow_included[index] : undefined;
  return typeof included === "boolean" ? included : undefined;
}

/** Shared by every Plotly surface, including exports. Never changes values. */
export function displayObservationTraces(traces: Trace[], actions?: WorkflowPopulationActions | null,
  selected: ReadonlySet<string> = new Set()): Trace[] {
  let excluded = false;
  let excludedLines = false;
  let excludedPoints = false;
  const resolved = new Map<string, boolean>();
  const displayed = traces.map(trace => {
    const wholeReference = compactObservationRef(trace);
    if (wholeReference !== null && typeof trace.mode === "string" && trace.mode.split("+").includes("lines")) {
      // One spectrum is one observation. Keep its navigation compact and style
      // the curve once, rather than creating a marker at every wavelength.
      if (!resolved.has(wholeReference)) resolved.set(wholeReference, actions?.resolve(wholeReference)?.excluded === true);
      const selection = selected.size ? { opacity: selected.has(wholeReference) ? 1 : 0.35 } : {};
      if (!resolved.get(wholeReference) && traceObservationIncluded(trace, 0) !== false) return { ...trace, ...selection };
      excluded = true;
      excludedLines = true;
      return { ...trace, ...selection, mode: "lines",
        line: { ...(trace.line as Record<string, unknown> | undefined), color: SCIENTIFIC_COLORS.excluded, dash: "dot" } };
    }
    const refs = traceObservationRefs(trace);
    if (!refs.length) return trace;
    const flags = refs.map((ref, i) => {
      if (!resolved.has(ref)) resolved.set(ref, actions?.resolve(ref)?.excluded === true);
      return resolved.get(ref) || traceObservationIncluded(trace, i) === false;
    });
    const selection = selected.size ? { selectedpoints: refs.flatMap((ref, i) => selected.has(ref) ? [i] : []),
      selected: { marker: { opacity: 1 } }, unselected: { marker: { opacity: 0.35 } } } : {};
    if (!flags.some(Boolean)) return { ...trace, ...selection };
    excluded = true;
    excludedPoints = true;
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
  if (excluded) displayed.push({ type: "scatter", mode: excludedLines && !excludedPoints ? "lines" : "markers",
    x: [null], y: [null], name: "Excluded / not in fit", hoverinfo: "skip",
    ...(excludedLines && !excludedPoints ? { line: { color: SCIENTIFIC_COLORS.excluded, dash: "dot" } }
      : { marker: { symbol: "x-open", color: SCIENTIFIC_COLORS.excluded, size: 10 } }) });
  return displayed;
}
