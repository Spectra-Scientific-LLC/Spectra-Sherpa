import type { DisplayPreferences } from "@/composables/useDisplayPreferences";
import { themedPlotLayout, themedPlotTrace, type PlotSurface } from "@/theme/plotTheme";

type Trace = Record<string, unknown>;
type Layout = Record<string, unknown>;

/** Old saved runs can retain plot-layout prose from earlier releases. Keep the
 * scientific payload intact, but give every rendered/exported graph one title. */
function cleanPlotLayout(layout: Layout): Layout {
  const title = layout.title;
  const oneLine = (value: string) => value.split(/<br\s*\/?\s*>/i, 1)[0];
  const cleanTitle = typeof title === "string"
    ? oneLine(title)
    : title && typeof title === "object" && typeof (title as Layout).text === "string"
      ? { ...(title as Layout), text: oneLine((title as Layout).text as string) }
      : title;
  const annotations = Array.isArray(layout.annotations)
    ? layout.annotations.flatMap((raw: unknown) => {
        if (!raw || typeof raw !== "object") return [raw];
        const annotation = raw as Layout;
        const text = typeof annotation.text === "string" ? annotation.text : "";
        if (annotation.xref !== "paper" || annotation.yref !== "paper" || annotation.showarrow !== false)
          return [raw];
        if (/^<b>(Original|Preprocessed)/i.test(text))
          return [{ ...annotation, text: /^<b>Original/i.test(text) ? "Original" : "Preprocessed" }];
        // Only remove prose emitted by earlier plot builders. Other paper-space
        // annotations can carry scientific information (for example a limit).
        if (/^(?:Equal axis units|Component signs are fit-specific|Loading vectors are scaled|Point estimates shown|VIP point estimates|Display preview:|Active cohort:|Symmetric color limits|Sequential color scale|RMSE(?:C|CV|P)?\b)/i.test(text))
          return [];
        return [raw];
      })
    : layout.annotations;
  return {
    ...layout,
    ...(cleanTitle !== undefined ? { title: cleanTitle } : {}),
    ...(annotations !== undefined ? { annotations } : {}),
  };
}

function sampled(trace: Trace, maxRows: number, priorityIds: ReadonlySet<string>): Trace {
  const length = Array.isArray(trace.x) ? trace.x.length : Array.isArray(trace.y) ? trace.y.length : 0;
  const meta = trace.meta as Record<string, unknown> | undefined;
  const refs = meta?.workflow_observation_refs;
  const included = meta?.workflow_included;
  const priority = Array.isArray(trace.customdata) && trace.customdata.length === length
    ? trace.customdata.flatMap((id, index) =>
        typeof id === "string" && priorityIds.has(id) ? [index] : [])
    : [];
  if (Array.isArray(refs) && refs.length === length) refs.forEach((ref, i) => {
    if ((typeof ref === "string" && priorityIds.has(ref)) || (Array.isArray(included) && included[i] === false)) priority.push(i);
  });
  const indexes = Array.from({ length: maxRows }, (_, index) =>
    maxRows === 1 ? 0 : Math.floor(index * (length - 1) / (maxRows - 1)));
  if (priority.length) {
    const retained = new Set(priority.slice(0, maxRows));
    const included = new Set(indexes);
    for (const wanted of retained) {
      if (included.has(wanted)) continue;
      let victim = indexes.length - 1;
      while (victim >= 0 && retained.has(indexes[victim])) victim -= 1;
      if (victim < 0) break;
      included.delete(indexes[victim]);
      indexes[victim] = wanted;
      included.add(wanted);
    }
    indexes.sort((a, b) => a - b);
  }
  const result = { ...trace };
  if (Array.isArray(trace.selectedpoints)) {
    const selected = new Set(trace.selectedpoints);
    result.selectedpoints = indexes.flatMap((original, displayed) => selected.has(original) ? [displayed] : []);
  }
  if (meta) {
    result.meta = { ...meta };
    for (const key of ["workflow_observation_refs", "workflow_included"]) {
      if (Array.isArray(meta[key]) && meta[key].length === length)
        (result.meta as Record<string, unknown>)[key] = indexes.map(i => (meta[key] as unknown[])[i]);
    }
  }
  for (const key of ["x", "y", "customdata", "text", "hovertext", "ids"]) {
    if (Array.isArray(trace[key]) && trace[key].length === length)
      result[key] = indexes.map((index) => (trace[key] as unknown[])[index]);
  }
  const marker = trace.marker as Record<string, unknown> | undefined;
  if (marker) {
    result.marker = { ...marker };
    for (const key of ["color", "size", "symbol", "opacity"]) {
      if (Array.isArray(marker[key]) && marker[key].length === length)
        (result.marker as Record<string, unknown>)[key] = indexes.map((index) => (marker[key] as unknown[])[index]);
    }
  }
  return result;
}

/** Visual limits count traces or plotted observations, not unique samples.
 * The same sample can contribute multiple feature observations or panels. */
export function displayPlot(
  data: Trace[], layout: Layout, prefs: DisplayPreferences,
  priorityIds: ReadonlySet<string> = new Set(),
  surface: PlotSurface = "screen",
) {
  let omitted = 0;
  let omittedTraces = 0;
  let shown = data;
  const isLegend = (trace: Trace) => trace.showlegend !== false && Array.isArray(trace.x) &&
    trace.x.length === 1 && trace.x[0] === null && Array.isArray(trace.y) && trace.y[0] === null;
  const curves = data.filter(trace => !isLegend(trace));
  const allSpectralLines = curves.length > prefs.maxRows && curves.every((trace) =>
    trace.type === "scatter" && String(trace.mode || "").includes("lines") &&
    (!String(trace.mode || "").includes("markers") ||
      Array.isArray((trace.meta as Trace | undefined)?.workflow_observation_refs)));
  if (allSpectralLines) {
    const priority = curves.flatMap((trace, index) => {
      const meta = trace.meta as Trace | undefined;
      return Array.isArray(meta?.workflow_included) && meta.workflow_included.some(value => value === false)
        ? [index] : [];
    });
    // Excluded observations disclose context; they must not replace the
    // active population in a capped preview. Reserve at least half for it.
    const prioritySet = new Set(priority);
    const active = curves.flatMap((_, index) => prioritySet.has(index) ? [] : [index]);
    const excludedBudget = Math.min(priority.length, active.length ? Math.floor(prefs.maxRows / 2) : prefs.maxRows);
    const chosen = new Set(priority.slice(0, excludedBudget));
    const activeBudget = Math.min(active.length, prefs.maxRows - chosen.size);
    for (let index = 0; index < activeBudget; index += 1)
      chosen.add(active[activeBudget === 1 ? 0 : Math.floor(index * (active.length - 1) / (activeBudget - 1))]);
    omitted = curves.length - chosen.size;
    omittedTraces = omitted;
    shown = [...chosen].sort((a, b) => a - b).map(index => curves[index]).concat(data.filter(isLegend));
  }
  const markerCounts = shown.map((trace) => trace.type === "scatter" &&
    String(trace.mode || "").includes("markers") && !String(trace.mode || "").includes("lines") && !isLegend(trace)
    ? Array.isArray(trace.x) ? trace.x.length : Array.isArray(trace.y) ? trace.y.length : 0 : 0);
  const markerBudgets = markerCounts.map(() => 0);
  let remaining = prefs.maxRows;
  while (remaining > 0 && markerBudgets.some((budget, index) => budget < markerCounts[index])) {
    for (let index = 0; index < markerCounts.length && remaining > 0; index += 1) {
      if (markerBudgets[index] < markerCounts[index]) {
        markerBudgets[index] += 1;
        remaining -= 1;
      }
    }
  }
  shown = shown.map((trace, traceIndex) => {
    const copy: Trace = { ...trace };
    const mode = String(trace.mode || "");
    // Point-only scatter traces are plotted observations, not necessarily unique samples. Do not crop spectral curves,
    // lines, heatmap axes, grouped histograms, or scientific reference geometry.
    if (trace.type === "scatter" && mode.includes("markers") && !mode.includes("lines")) {
      const length = Array.isArray(trace.x) ? trace.x.length : Array.isArray(trace.y) ? trace.y.length : 0;
      const budget = markerBudgets[traceIndex];
      if (length > budget && budget > 0) {
        omitted += length - budget;
        Object.assign(copy, sampled(trace, budget, priorityIds));
      }
    }
    if (trace.line && typeof trace.line === "object") {
      const line = trace.line as Record<string, unknown>;
      copy.line = { ...line, width: Number(line.width ?? 2) * prefs.lineScale };
    }
    if (trace.marker && typeof trace.marker === "object") {
      const marker = copy.marker as Record<string, unknown>;
      copy.marker = {
        ...marker,
        size: typeof marker.size === "number" ? marker.size * prefs.markerScale
          : Array.isArray(marker.size) ? marker.size.map((value) => Number(value) * prefs.markerScale)
          : 6 * prefs.markerScale,
      };
    }
    return themedPlotTrace(copy, surface);
  }).filter((trace, index) => {
    if (!markerCounts[index] || markerBudgets[index]) return true;
    omitted += markerCounts[index];
    return false;
  });
  const baseLayout: Layout = cleanPlotLayout(themedPlotLayout(layout, prefs.palette, surface));
  return {
    data: shown,
    layout: baseLayout,
    omitted,
    omissionDescription: [
      omittedTraces ? `${omittedTraces} traces` : "",
      omitted > omittedTraces ? `${omitted - omittedTraces} plotted observations` : "",
    ].filter(Boolean).join(" and "),
  };
}
