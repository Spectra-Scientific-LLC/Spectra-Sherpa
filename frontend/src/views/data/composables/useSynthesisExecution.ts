import { ref } from "vue";
import api from "@/api/client";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";
import type { SynthesisResult } from "@/stores/synthesis";

export interface SynthesisSaveItem {
  name: string;
  payload: Record<string, unknown>;
}
export interface SynthesisSaveOutcome {
  status: "complete" | "partial" | "unknown";
  result?: SynthesisResult;
  file_path?: string;
  count: number;
  requested: number;
  error?: unknown;
}
type SynthesisSaveResponse = {
  result: SynthesisResult;
  file_path?: string;
  experiment_id: number;
};

/** Transport orchestration only. Payload construction and spectra remain with their authorities. */
export function useSynthesisPreview(identity: () => readonly ScopeIdentity[]) {
  const previewing = ref(false);
  const previews = useScopedRequest(identity, () => { previewing.value = false; });

  async function preview(payload: Record<string, unknown>): Promise<SynthesisResult | undefined> {
    const snapshot = JSON.parse(JSON.stringify(payload)) as Record<string, unknown>;
    const ticket = previews.begin();
    previewing.value = true;
    try {
      const response = await api.post<SynthesisResult>("/synthesis/preview", snapshot,
        { signal: ticket.signal });
      return ticket.isCurrent() ? response.data : undefined;
    } catch (error) {
      if (ticket.isCurrent()) throw error;
    } finally {
      if (ticket.isCurrent()) previewing.value = false;
    }
  }
  return { preview, previewing, invalidatePreview: previews.invalidate };
}

/** Store-owned writes survive form edits and component unmounts. */
export function useSynthesisSave(identity: () => readonly ScopeIdentity[]) {
  const saving = ref(false);
  const saves = useScopedRequest(identity, undefined, { abortOnInvalidate: false });
  async function save(projectId: number | null, items: readonly SynthesisSaveItem[]): Promise<SynthesisSaveOutcome> {
    if (saving.value) throw new Error("A synthesis save is already in progress.");
    if (!items.length) throw new Error("There are no synthetic datasets to save.");
    // Freeze the entire bundle, including its destination, before any request.
    // Accepted writes remain in that project; invalidation prevents later writes.
    const snapshot = JSON.parse(JSON.stringify(items)) as SynthesisSaveItem[];
    const ticket = saves.begin();
    saving.value = true;
    let experimentId: number | null = null;
    const outcome: SynthesisSaveOutcome = { status: "partial", count: 0, requested: snapshot.length };
    try {
      for (const item of snapshot) {
        if (!ticket.isCurrent()) return outcome;
        const response: { data: SynthesisSaveResponse } = await api.post<SynthesisSaveResponse>("/synthesis/save", {
          ...item.payload, name: item.name, experiment_id: experimentId, project_id: projectId,
        }, { signal: ticket.signal });
        experimentId = response.data.experiment_id;
        outcome.result = response.data.result;
        outcome.file_path = response.data.file_path;
        outcome.count += 1;
      }
      outcome.status = "complete";
      return outcome;
    } catch (error) {
      // A dropped acknowledgement cannot prove the last file was not saved.
      return { ...outcome, status: "unknown", error };
    } finally {
      saving.value = false;
    }
  }
  return { save, saving };
}
