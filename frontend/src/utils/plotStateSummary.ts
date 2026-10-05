/** Advisor descriptions are projections of retained scientific evidence, never node-name guesses. */
import { effectScope, ref, shallowRef } from "vue";
import { useQuickPlotProjection } from "@/composables/useScientificPlotProjection";
import { buildNodeOutput } from "@/utils/nodeOutput";
import {
  availableScientificPresentations,
  projectScientificPresentation,
} from "@/utils/scientificPresentation";
import { scientificPlotRefusal } from "@/utils/scientificPlotState";
import type {
  ExecutedPresentationRecord,
  NodeScientificValueDescriptors,
} from "@/stores/workflow-types";

export interface PlotAxisSummary {
  title: string | null;
  units: string | null;
  reversed?: boolean;
}
export interface PlotStateSummary {
  plot: string;
  kind: string;
  x_axis: PlotAxisSummary | null;
  y_axis: PlotAxisSummary | null;
  traces: null;
  note: string;
  presentation_id?: string;
  presentation_kind?: string;
  contract_digest?: string;
  source_ports?: string[];
  view_scope: "retained_default_projection";
  refusal_reason: string | null;
  population: Record<string, number> | null;
  claim_scope: string | null;
}
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const axisSummary = (value: unknown): PlotAxisSummary | null => {
  const axis = record(value);
  const title = typeof axis.title === "string" ? axis.title : record(axis.title).text;
  const safeTitles = [
    "Feature",
    "Property",
    "Wavenumber",
    "Wavelength",
    "Loading",
    "Principal Component",
    "Variance (%)",
    "Sample",
    "T²",
    "Hotelling T²",
    "SPE (Q)",
    "Absorbance",
    "Intensity",
    "Reflectance",
    "VIP",
    "Observed",
    "Predicted",
    "Latent Variable",
    "Category",
    "Count",
  ];
  if (
    typeof title !== "string" ||
    !(
      safeTitles.includes(title) ||
      /^(?:PC|LV)[1-9][0-9]{0,2}(?: \(\d{1,3}(?:\.\d{1,2})?%\))?$/.test(title) ||
      /^(?:Wavenumber|Wavelength) \((?:cm-1|cm\^-1|nm|µm|um)\)$/.test(title)
    )
  )
    return null;
  return {
    title,
    units:
      typeof axis.units === "string" &&
      ["cm-1", "cm^-1", "nm", "µm", "um", "dimensionless", "%", "a.u.", "AU"].includes(axis.units)
        ? axis.units
        : null,
    reversed: axis.autorange === "reversed",
  };
};
const viewNote =
  "Retained evidence projected with default view selection; this is not the current open plot or live axis selection. The contract digest is a retained receipt, not independently reverified here. Trace counts are not sample counts. Population and units are unknown unless declared; do not infer them from array shape.";
const unavailable = (reason: string): PlotStateSummary[] => [
  {
    plot: "Scientific plots unavailable",
    kind: "unavailable",
    x_axis: null,
    y_axis: null,
    traces: null,
    note: `${viewNote} ${reason}`,
    view_scope: "retained_default_projection",
    refusal_reason: reason,
    population: null,
    claim_scope: null,
  },
];

/** Only execution-time contracts are accepted. Legacy results get an explicit qualification. */
export function summarizeNodePlots(
  rawResult: unknown,
  execution?: ExecutedPresentationRecord | null,
  descriptors?: NodeScientificValueDescriptors | null,
): PlotStateSummary[] {
  if (!execution)
    return unavailable(
      "The saved execution has no presentation contract; plot interpretation is unavailable.",
    );
  if (
    execution.schema_version !== "spectrasherpa-executed-presentation/1" ||
    !/^[a-f0-9]{64}$/.test(execution.contract_digest) ||
    execution.contract?.schema_version !== "spectrasherpa-node-presentation/1" ||
    !Array.isArray(execution.presentations)
  )
    return unavailable("The retained execution presentation record is invalid.");
  const scope = effectScope();
  try {
    return scope.run(() => {
      const output = buildNodeOutput(rawResult, undefined, null, descriptors, {
        digest: execution.contract_digest,
        payload: execution.contract,
      });
      const summaries: PlotStateSummary[] = [];
      for (const resolved of availableScientificPresentations(null, output)) {
        if (!resolved.presentation.modes.includes("plot")) continue;
        const materialized = execution.presentations.find(
          (item) => item.presentation_id === resolved.presentation.presentation_id,
        );
        if (
          !materialized ||
          materialized.kind !== resolved.presentation.kind ||
          JSON.stringify(materialized.source_ports) !== JSON.stringify(resolved.sourcePorts) ||
          JSON.stringify(materialized.modes) !== JSON.stringify(resolved.presentation.modes)
        )
          continue;
        const projected = projectScientificPresentation(output, resolved);
        const plot = useQuickPlotProjection(shallowRef(projected), ref(""));
        for (const option of plot.availablePlots.value) {
          plot.selectedPlotKey.value = option.key;
          const layout = record(plot.plotLayout.value);
          const data = plot.plotData.value;
          const meta = record(layout.meta);
          const declaredPopulation = record(meta.display_population);
          // Allowlist aggregate counts only: never send row indices, sample/class labels,
          // raw values, hover text or trace names to the advisor.
          const counts = Object.fromEntries(
            ["shown", "total", "available", "excluded"].flatMap((key) =>
              typeof declaredPopulation[key] === "number" &&
              Number.isFinite(declaredPopulation[key])
                ? [[key, declaredPopulation[key] as number]]
                : [],
            ),
          );
          const validCounts =
            ["shown", "total", "available", "excluded"].every(
              (key) => Number.isInteger(counts[key]) && counts[key] >= 0,
            ) &&
            counts.shown <= counts.total &&
            counts.total <= counts.available &&
            counts.total + counts.excluded === counts.available;
          const population =
            resolved.presentation.kind === "spectral_dataset" && validCounts ? counts : null;
          const refusal = scientificPlotRefusal(layout)
            ? "The projection refused this result; inspect the local plot for details."
            : data.length
              ? null
              : "No renderable traces are retained for this presentation.";
          const claim =
            resolved.presentation.kind === "out_of_fold_evidence" &&
            meta.claim_scope === "out_of_fold"
              ? "out_of_fold"
              : null;
          const kinds =
            [
              ...new Set(
                data.map((trace) => {
                  const t = record(trace);
                  return t.type === "scatter" &&
                    typeof t.mode === "string" &&
                    t.mode.includes("lines")
                    ? "line"
                    : [
                          "scatter",
                          "scattergl",
                          "bar",
                          "heatmap",
                          "box",
                          "histogram",
                          "contour",
                        ].includes(String(t.type))
                      ? String(t.type)
                      : "unknown";
                }),
              ),
            ].join("+") || "unavailable";
          summaries.push({
            plot: option.label,
            kind: kinds,
            x_axis: axisSummary(layout.xaxis),
            y_axis: axisSummary(layout.yaxis),
            traces: null,
            presentation_id: resolved.presentation.presentation_id,
            presentation_kind: resolved.presentation.kind,
            contract_digest: resolved.contractDigest,
            source_ports: resolved.sourcePorts,
            view_scope: "retained_default_projection",
            refusal_reason: refusal,
            population,
            claim_scope: claim,
            note: `${viewNote}${population ? ` Declared display population: ${JSON.stringify(population)}.` : ""}${claim ? ` Claim scope: ${claim}.` : ""}${refusal ? ` Refused: ${refusal}` : ""}`,
          });
        }
      }
      return summaries.length
        ? summaries
        : unavailable("The saved presentation has no available plot source ports.");
    })!;
  } catch {
    return unavailable(
      "The retained presentation cannot be projected; its contract or source values are invalid.",
    );
  } finally {
    scope.stop();
  }
}
