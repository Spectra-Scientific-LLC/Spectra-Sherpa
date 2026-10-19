import type { DisplayPreferences } from "@/composables/useDisplayPreferences";

type Trace = Record<string, unknown>;
type Layout = Record<string, unknown>;

const palettes: Record<DisplayPreferences["palette"], string[] | undefined> = {
  default: undefined,
  colorblind: ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"],
  "high-contrast": ["#002B7F", "#B62020", "#006B45", "#671094", "#A05500", "#006D83"],
};

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
  const priority = Array.isArray(trace.customdata) && trace.customdata.length === length
    ? trace.customdata.flatMap((id, index) =>
        typeof id === "string" && priorityIds.has(id) ? [index] : [])
    : [];
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
) {
  let omitted = 0;
  let omittedTraces = 0;
  let shown = data;
  const allSpectralLines = data.length > prefs.maxRows && data.every((trace) =>
    trace.type === "scatter" && String(trace.mode || "").includes("lines") &&
    !String(trace.mode || "").includes("markers"));
  if (allSpectralLines) {
    omitted = data.length - prefs.maxRows;
    omittedTraces = omitted;
    shown = Array.from({ length: prefs.maxRows }, (_, index) =>
      data[Math.floor(index * (data.length - 1) / (prefs.maxRows - 1))]);
  }
  const markerCounts = shown.map((trace) => trace.type === "scatter" &&
    String(trace.mode || "").includes("markers") && !String(trace.mode || "").includes("lines")
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
    return copy;
  }).filter((trace, index) => {
    if (!markerCounts[index] || markerBudgets[index]) return true;
    omitted += markerCounts[index];
    return false;
  });
  const colorway = palettes[prefs.palette];
  const baseLayout: Layout = cleanPlotLayout(colorway ? { ...layout, colorway } : layout);
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
