import { ref } from "vue";
import api from "@/api/client";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";
import { getErrorMessage } from "@/utils/errors";

export type DatasetView = {
  id: number;
  name: string;
  selection_sha256: string;
  selection: {
    schema_version?: string;
    included_count?: number;
    selected_file_ids: number[] | null;
    stage: "raw" | "preprocessed" | "synthetic";
    asset_id: string | null;
    target_authority: {
      column: string;
      target_type: "categorical" | "continuous";
      units: string | null;
      source_digest: string;
    } | null;
    group_column: string | null;
    source_manifest_sha256: string;
    collection_definition_sha256: string | null;
    scientific_collection_sha256: string | null;
  };
};

/** Saved-definition state is scoped independently of the live inspection. */
export function useDatasetDefinitions(identity: () => readonly ScopeIdentity[]) {
  const views = ref<DatasetView[]>([]);
  const selected = ref<DatasetView | null>(null);
  const error = ref<string | null>(null);
  const busy = ref(false);
  const name = ref("");
  const listing = useScopedRequest(identity, () => { views.value = []; });
  const operations = useScopedRequest(identity, () => {
    selected.value = null;
    error.value = null;
    busy.value = false;
    name.value = "";
  });

  async function refresh(experimentId: number | null, isCurrent = () => true): Promise<void> {
    const ticket = listing.begin();
    views.value = [];
    error.value = null;
    if (experimentId == null) return;
    try {
      const response = await api.get<DatasetView[]>(`/experiments/${experimentId}/dataset-views`,
        { signal: ticket.signal });
      if (ticket.isCurrent() && isCurrent())
        views.value = Array.isArray(response.data) ? response.data : [];
    } catch (cause) {
      if (ticket.isCurrent() && isCurrent())
        error.value = getErrorMessage(cause, "Saved definitions are unavailable.");
    }
  }

  async function remove(experimentId: number, viewId: number, confirm: () => Promise<boolean>) {
    const ticket = operations.begin();
    const accepted = await confirm();
    if (!accepted || !ticket.isCurrent()) return;
    busy.value = true;
    error.value = null;
    try {
      await api.delete(`/experiments/${experimentId}/dataset-views/${viewId}`,
        { signal: ticket.signal });
      if (!ticket.isCurrent()) return;
      if (selected.value?.id === viewId) selected.value = null;
      await refresh(experimentId, ticket.isCurrent);
    } catch (cause) {
      if (ticket.isCurrent()) error.value = getErrorMessage(cause, "Could not delete this definition.");
    } finally {
      if (ticket.isCurrent()) busy.value = false;
    }
  }

  function begin() {
    const ticket = operations.begin();
    // A superseded operation cannot clear busy in its finally block.
    busy.value = false;
    return ticket;
  }
  return { views, selected, error, busy, name, refresh, remove, begin };
}
