/* eslint-disable @typescript-eslint/no-explicit-any -- canonical scientific payloads span heterogeneous node types. */
import { effectScope, nextTick, ref } from "vue";
import api from "@/api/client";
import { buildNodeOutput } from "./nodeOutput";
import { availableScientificPresentations, projectScientificPresentation } from "./scientificPresentation";
import { scientificPlotRefusal } from "./scientificPlotState";
import { useQuickPlotProjection } from "@/composables/useScientificPlotProjection";
import type { RunReportData } from "@/stores/report";
import type { ReportNodePlotSection } from "./reportNodePlots";

type RenderPlot = (data: any[], layout: Record<string, any>) => Promise<string>;
async function renderPlot(data: any[], layout: Record<string, any>): Promise<string> {
  const module = await import("plotly.js-cartesian-dist-min");
  const Plotly = ((module as any).default ?? module) as {
    newPlot: (element: HTMLElement, data: any[], layout: any, config: any) => Promise<unknown>;
    toImage: (element: HTMLElement, options: any) => Promise<string>;
    purge: (element: HTMLElement) => void;
  };
  const element = document.createElement("div");
  element.style.cssText = "position:fixed;left:-10000px;top:0;width:1000px;height:650px";
  document.body.appendChild(element);
  try {
    // Plotly mutates its inputs; never mutate the retained scientific projection.
    const clone = JSON.parse(JSON.stringify({ data, layout }));
    await Plotly.newPlot(element, clone.data, { ...clone.layout, width: 1000, height: 650, autosize: false }, { staticPlot: true });
    return await Plotly.toImage(element, { format: "png", width: 1000, height: 650, scale: 1.5 });
  } finally { Plotly.purge(element); element.remove(); }
}

/** Same retained evidence and presentation facade as Runs/Quick Plot; no workflow execution. */
export async function captureReportPlots(run: RunReportData, projectId: number, current: () => boolean, render: RenderPlot = renderPlot): Promise<ReportNodePlotSection[]> {
  const sections: ReportNodePlotSection[] = [];
  const unavailable = (message: string): ReportNodePlotSection[] => [{ node_id: "run", label: "Saved-run plots", node_type: "", notices: [message], plots: [] }];
  if (!run.saved_definition) return unavailable("Saved workflow definition unavailable; current canvas plots were not substituted.");
  let outputs: Record<string, Record<string, any>>;
  try { outputs = (await api.get(`/runs/${run.id}/evidence`, { params: { project_id: projectId } })).data.evidence.outputs; }
  catch { return unavailable("Retained plot evidence could not be loaded. Inspect the saved run for recovery details."); }
  const cache = new Map<string, Promise<any>>();
  let bytes = 0;
  let images = 0;
  const read = (node: string, port: string): Promise<any> => {
    if (!current()) throw new Error("Report selection changed; capture cancelled.");
    const key = `${node}/${port}`;
    if (cache.has(key)) return cache.get(key)!;
    const item = outputs[node]?.[port];
    if (item?.state !== "exact" || !item.storage) throw new Error(`${key}: exact retained output unavailable.`);
    if (!Number.isFinite(item.byte_count) || bytes + item.byte_count > 32 * 1024 * 1024) throw new Error(`${key}: exceeds the 32 MiB per-run plot read budget.`);
    bytes += item.byte_count;
    const promise = api.get(`/runs/${run.id}/outputs/${encodeURIComponent(node)}/${encodeURIComponent(port)}`, { params: { project_id: projectId } }).then(response => response.data.value);
    cache.set(key, promise);
    return promise;
  };
  const optional = async (port: string) => outputs.__diagnostics__?.[port] ? await read("__diagnostics__", port) : null;
  let descriptors: any, presentations: any;
  try { descriptors = await optional("_scientific_values"); presentations = await optional("_scientific_presentations"); }
  catch { return unavailable("Saved scientific presentation metadata could not be verified; no current definitions substituted."); }
  for (const node of run.saved_definition.nodes) {
    if (!current()) return [];
    const section: ReportNodePlotSection = { node_id: node.node_id, node_type: node.node_type, label: node.label || node.node_id, notices: [], plots: [] };
    sections.push(section);
    try {
    const values: Record<string, any> = {}, inputs: Record<string, any> = {};
    for (const port of Object.keys(outputs[node.node_id] ?? {})) {
      if (/^(?:fitted_state|model|artifact)/.test(port)) continue;
      try { values[port] = await read(node.node_id, port); }
      catch (error) { section.notices.push(String(error)); }
    }
    for (const edge of run.saved_definition.edges ?? []) {
      if (edge.to_node_id !== node.node_id) continue;
      if (/^(?:fitted_state|model|artifact)/.test(edge.from_output)) continue;
      try { inputs[edge.to_input] = await read(edge.from_node_id, edge.from_output); }
      catch (error) { section.notices.push(`Input unavailable: ${String(error)}`); }
    }
    const saved = presentations?.[node.node_id];
    const contract = saved ? { digest: saved.contract_digest, payload: saved.contract } : undefined;
    const raw = buildNodeOutput(values, undefined, run.diagnostics?.[node.node_id], descriptors?.[node.node_id], contract);
    const choices = availableScientificPresentations(undefined, raw).filter(item => item.presentation.modes.includes("plot"));
    for (const declared of contract?.payload.presentations ?? []) {
      if (declared.modes.includes("plot") && !choices.some(item => item.presentation.presentation_id === declared.presentation_id)) {
        section.notices.push(`${declared.label}: required retained output is unavailable.`);
      }
    }
    const projections = contract ? choices.map(item => ({ label: item.presentation.label, output: projectScientificPresentation(raw, item) })) : [{ label: "", output: raw }];
    for (const projection of projections) {
      const scope = effectScope();
      try {
        const plots = scope.run(() => useQuickPlotProjection(ref(projection.output), ref(node.node_type), ref(Object.values(inputs)[0]), ref(inputs)))!;
        await nextTick();
        for (const option of [...plots.availablePlots.value]) {
          plots.selectedPlotKey.value = option.key;
          await nextTick();
          const targets = plots.showRegressionTargetControl.value ? [...plots.regressionTargetOptions.value] : [{ value: plots.regressionTargetIdx.value, label: "" }];
          for (const target of targets) {
            if (!current()) return [];
            plots.regressionTargetIdx.value = target.value;
            await nextTick();
            const title = [projection.label, option.label, target.label].filter(Boolean).join(" — ");
            const refusal = scientificPlotRefusal(plots.plotLayout.value);
            if (refusal || !plots.plotData.value.length) { section.plots.push({ title, notice: refusal || "No plottable retained data for this view." }); continue; }
            if (images >= 200) { section.plots.push({ title, notice: "200-image per-run export limit reached; view remaining plots in Runs." }); continue; }
            images++;
            const meta = plots.plotLayout.value.meta ?? {};
            const notice = ["Saved-run projection; default displayed axes. No fitting or validation is rerun.",
              meta.display_population ? `Display population: ${JSON.stringify(meta.display_population)}` : "",
              meta.comparison_scale_notice ?? "", ...(meta.comparison_notices ?? [])].filter(Boolean).join(" ");
            try { section.plots.push({ title, image: await render(plots.plotData.value, plots.plotLayout.value), notice }); }
            catch { section.plots.push({ title, notice: "Plot rendering failed; inspect this node in Runs." }); }
          }
        }
      } catch (error) { section.notices.push(`Plot unavailable: ${String(error)}`); }
      finally { scope.stop(); }
    }
    if (!section.plots.length) section.notices.push("No plottable presentation retained for this node; tabular results remain in the report.");
    } catch (error) {
      section.notices.push(`Node plots unavailable: ${String(error)}`);
    }
  }
  return sections;
}
