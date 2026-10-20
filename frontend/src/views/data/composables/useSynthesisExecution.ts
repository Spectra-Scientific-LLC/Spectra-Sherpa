import { ref } from "vue";
import api from "@/api/client";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";
import type { SynthesisResult } from "@/stores/synthesis";

export interface SynthesisSaveItem {
  name: string;
  payload: Record<string, unknown>;
}
export interface SynthesisSaveOutcome {
  result: SynthesisResult;
  file_path?: string;
  count: number;
}

/** Transport orchestration only. Payload construction and spectra remain with their authorities. */
export function useSynthesisExecution(identity: () => readonly ScopeIdentity[]) {
  const previewing = ref(false);
  const saving = ref(false);
  const previews = useScopedRequest(identity, () => { previewing.value = false; });
  const saves = useScopedRequest(identity, () => { saving.value = false; });

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

  async function save(projectId: number | null, items: readonly SynthesisSaveItem[]): Promise<SynthesisSaveOutcome | undefined> {
    // Freeze the entire bundle, including its destination, before any request.
    // Accepted writes remain in that project; invalidation prevents later writes.
    const snapshot = JSON.parse(JSON.stringify(items)) as SynthesisSaveItem[];
    const ticket = saves.begin();
    saving.value = true;
    let experimentId: number | null = null;
    let outcome: SynthesisSaveOutcome | undefined;
    try {
      for (const item of snapshot) {
        if (!ticket.isCurrent()) return;
        const response: { data: {
          experiment_id: number; result: SynthesisResult; file_path?: string;
        } } = await api.post<{
          experiment_id: number; result: SynthesisResult; file_path?: string;
        }>("/synthesis/save", {
          ...item.payload, name: item.name, experiment_id: experimentId, project_id: projectId,
        }, { signal: ticket.signal });
        if (!ticket.isCurrent()) return;
        experimentId = response.data.experiment_id;
        outcome = { result: response.data.result, file_path: response.data.file_path, count: snapshot.length };
      }
      return outcome;
    } catch (error) {
      if (ticket.isCurrent()) throw error;
    } finally {
      if (ticket.isCurrent()) saving.value = false;
    }
  }
  return { preview, save, previewing, saving, invalidatePreview: previews.invalidate };
}
