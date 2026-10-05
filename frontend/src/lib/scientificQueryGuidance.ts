import { ref } from "vue";
import { useNotificationStore } from "@/stores/notification";
import { attentionSnapshot } from "@/lib/sherpaAttention";

export const SCIENTIFIC_QUERY_REFUSAL = "Spectra Sherpa is a scientific data analysis platform. Adjust your query.";
export const scientificQuerySuggestion = ref<string | null>(null);
let rejected = 0;
export function resetScientificQueryGuidance(): void { rejected = 0; scientificQuerySuggestion.value = null; }
export function recordScientificQueryOutcome(accepted: boolean): void {
  if (accepted) { resetScientificQueryGuidance(); return; }
  rejected += 1;
  if (rejected < 2) return;
  const focus = attentionSnapshot();
  const suggestions = focus.surface === "plot"
    ? ["Explain the axes and population in this plot.", "Which diagnostics should I inspect before interpreting this result?"]
    : focus.window === "optimization"
      ? ["Suggest a model improvement using development data only.", "Explain this campaign's validation strategy."]
      : focus.window === "data"
        ? ["Check this dataset's sample, feature, and target roles.", "How should I handle missing observations?"]
        : ["Help me choose a scientific analysis workflow.", "Explain the current model's validation results."];
  scientificQuerySuggestion.value = suggestions[(rejected - 2) % suggestions.length];
  useNotificationStore().add({ source: "sherpa", severity: "info", title: "Sherpa Advisor Guidance",
    message: suggestions[(rejected - 2) % suggestions.length],
    detail: "Try this scientific question, or describe the analysis you want to perform. Your query has not been executed." });
}
export function observeQueryFilterEvent(payload: Record<string, any>): void {
  if (payload.query_filter?.code === "scientific_query_rejected" || payload.code === "scientific_query_rejected") recordScientificQueryOutcome(false);
  else if (payload.stage === "scientific_query_accepted" || payload.payload?.stage === "scientific_query_accepted") recordScientificQueryOutcome(true);
}
