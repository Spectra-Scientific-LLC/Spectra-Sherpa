import { ref, watch } from "vue";
import { activeProjectScope } from "@/stores/projectScopeRegistry";

export type SherpaWindow = "dashboard" | "data" | "workflow" | "results" | "optimization" | "project" | "deploy" | "settings" | "unknown";
export interface ActiveAttention {
  window: SherpaWindow;
  surface: "window" | "plot" | "table" | "inspector";
  plot_id?: string;
  node_id?: string;
  plot_key?: string;
  section?: string;
  campaign_id?: string;
  candidate_id?: string;
}
const active = ref<ActiveAttention>({ window: "unknown", surface: "window" });
// Navigation does not necessarily change when the scientist switches projects.
// Clear the old plot/node before any new-project request can snapshot attention.
watch(activeProjectScope, () => {
  active.value = { window: active.value.window, surface: "window" };
}, { flush: "sync" });
let sequence = 0;
export function nextPlotAttentionId(): string { return `plot-${++sequence}`; }
export function attentionSnapshot(): ActiveAttention { return { ...active.value }; }
export function setAttentionWindow(path = ""): void {
  const section = path.split(/[?#]/)[0].split("/")[1];
  const window: SherpaWindow = ["runs", "report", "models"].includes(section) ? "results" : section === "harness" || section === "campaigns" ? "optimization"
    : ["dashboard", "data", "workflow", "results", "optimization", "project", "deploy", "settings"].includes(section)
      ? section as SherpaWindow : "unknown";
  active.value = { window, surface: "window" };
}
export function focusPlot(plot_id: string, node_id?: string, plot_key?: string): void {
  active.value = { ...windowContext(), surface: "plot", plot_id, ...(node_id ? { node_id } : {}), ...(plot_key ? { plot_key } : {}) };
}
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
/** Optimize focus: identifiers only; the hosted Advisor resolves them under server authority. */
export function focusOptimization(campaignId: string | null, candidateId?: string | null): void {
  const section = active.value.window === "optimization" && active.value.section ? { section: active.value.section } : {};
  if (!campaignId || !IDENTIFIER.test(campaignId) || campaignId.length > 64) {
    active.value = { window: "optimization", surface: "window", ...section };
    return;
  }
  const candidate = candidateId && IDENTIFIER.test(candidateId) ? { candidate_id: candidateId } : {};
  active.value = { window: "optimization", surface: "window", campaign_id: campaignId, ...candidate, ...section };
}
function windowContext(): ActiveAttention {
  const { plot_id: _plot, node_id: _node, plot_key: _key, ...context } = active.value;
  return { ...context, surface: "window" };
}
/** Section is ephemeral attention; changing it never creates a conversation. */
export function focusSection(section: string): void {
  if (!IDENTIFIER.test(section) || section.length > 64) return;
  active.value = { ...windowContext(), section };
}
export function releasePlot(plotId: string): void {
  if (active.value.plot_id === plotId) active.value = windowContext();
}
