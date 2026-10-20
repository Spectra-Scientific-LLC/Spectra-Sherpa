import { ref } from "vue";
import api from "@/api/client";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";
import { retainedInspection } from "@/utils/retainedInspection";
import { getErrorMessage } from "@/utils/errors";
import type { DatasetAnalysisReadiness, SherpaDatasetDict } from "@/types";

/** Fetches the backend's decision; never derives admission rules in the browser. */
export function useDatasetReadinessPreview(identity: () => readonly ScopeIdentity[]) {
  const readiness = ref<DatasetAnalysisReadiness | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const requests = useScopedRequest(identity, () => {
    readiness.value = null; loading.value = false; error.value = null;
  });
  function setBase(value: DatasetAnalysisReadiness | null): void {
    requests.begin();
    readiness.value = value; loading.value = false; error.value = null;
  }
  async function load(dataset: SherpaDatasetDict | null, payload: Record<string, unknown>): Promise<void> {
    const ticket = requests.begin();
    readiness.value = null; loading.value = true; error.value = null;
    try {
      // Shared retained reads are not aborted: other consumers may still own them.
      const read = async () => (await api.post<DatasetAnalysisReadiness>(
        "/workflow-templates/compatibility-preview", payload,
      )).data;
      const result = dataset
        ? await retainedInspection(dataset, `readiness:${JSON.stringify(payload)}`, read)
        : await read();
      if (ticket.isCurrent()) readiness.value = result;
    } catch (cause) {
      if (ticket.isCurrent())
        error.value = getErrorMessage(cause, "Compatibility could not be recomputed for this target.");
    } finally {
      if (ticket.isCurrent()) loading.value = false;
    }
  }
  return { readiness, loading, error, load, setBase };
}
