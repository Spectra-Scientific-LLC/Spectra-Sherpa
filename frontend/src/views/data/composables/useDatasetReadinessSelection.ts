import { ref } from "vue";
import api from "@/api/client";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";
import type { DatasetAnalysisReadiness } from "@/types";

export interface AnalysisChoice {
  target: string;
  targetType: "categorical" | "continuous" | null;
  targetUnits: string | null;
  sourceDigest: string | null;
  group: string;
  readiness: DatasetAnalysisReadiness | null;
}

const emptyChoice = (): AnalysisChoice => ({
  target: "", targetType: null, targetUnits: null, sourceDigest: null, group: "", readiness: null,
});
const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
const text = (value: unknown): string => typeof value === "string" ? value : "";

/** Owns the saved target/group choice, never computes scientific readiness. */
export function useDatasetReadinessSelection(identity: () => readonly ScopeIdentity[]) {
  const metadata = ref<Record<string, unknown> | null>(null);
  const choice = ref<AnalysisChoice>(emptyChoice());
  const requested = ref({ target: "", group: "" });
  const hydrated = ref(false);
  const status = ref<"loading" | "idle" | "saving" | "saved" | "error">("loading");
  const requests = useScopedRequest(identity, reset);

  function reset(): void {
    metadata.value = null;
    choice.value = emptyChoice();
    requested.value = { target: "", group: "" };
    hydrated.value = false;
    status.value = "loading";
  }

  function setChoice(value: AnalysisChoice): void {
    choice.value = value;
    requested.value = { target: value.target, group: value.group };
  }

  async function refresh(experimentId: number | null, sheetChoice?: AnalysisChoice): Promise<void> {
    const ticket = requests.begin();
    reset();
    if (experimentId == null || sheetChoice) {
      if (sheetChoice) setChoice(sheetChoice);
      hydrated.value = true;
      status.value = "idle";
      return;
    }
    try {
      const response = await api.get(`/experiments/${experimentId}`, { signal: ticket.signal });
      if (!ticket.isCurrent()) return;
      metadata.value = record(response.data?.metadata) ?? {};
      const saved = record(metadata.value.analysis_selection);
      const target = text(saved?.selected_target);
      const type = saved?.target_type === "categorical" || saved?.target_type === "continuous"
        ? saved.target_type : null;
      setChoice({
        target: target && type ? target : "",
        targetType: target && type ? type : null,
        targetUnits: null,
        sourceDigest: text(saved?.source_digest) || null,
        group: target && type ? text(saved?.group_column) : "",
        readiness: null,
      });
      status.value = saved ? "saved" : "idle";
    } catch {
      if (ticket.isCurrent()) {
        metadata.value = null;
        status.value = "error";
      }
    } finally {
      if (ticket.isCurrent()) hydrated.value = true;
    }
  }

  async function save(experimentId: number, value: AnalysisChoice): Promise<void> {
    const ticket = requests.begin();
    setChoice(value);
    status.value = "saving";
    try {
      const response = await api.put(`/experiments/${experimentId}/analysis-selection`, {
        selected_target: value.target || null,
        target_type: value.target ? value.targetType : null,
        group_column: value.target && value.group ? value.group : null,
        source_digest: value.sourceDigest,
      }, { signal: ticket.signal });
      if (!ticket.isCurrent()) return;
      metadata.value = { ...(metadata.value ?? {}), analysis_selection: response.data };
      status.value = "saved";
    } catch (error) {
      if (ticket.isCurrent()) {
        status.value = "error";
        throw error;
      }
    }
  }

  return { metadata, choice, requested, hydrated, status, refresh, save,
    // Superseding a read with a saved definition preserves source metadata.
    invalidate: () => { requests.begin(); },
  };
}
