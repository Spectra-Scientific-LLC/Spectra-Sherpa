import { defineStore } from "pinia";
import { ref } from "vue";
import api from "@/api/client";
import { getErrorMessage } from "@/utils/errors";

export type ProvenanceState = "healthy" | "missing" | "faulty";
export type ProvenanceKind =
  | "source" | "dataset" | "workflow" | "run" | "environment" | "model" | "campaign" | "package";

export interface ProjectProvenanceRecord {
  kind: ProvenanceKind;
  label: string;
  state: ProvenanceState;
  availability?: { state: ProvenanceState; detail: string };
  name: string | null;
  digest: string | null;
  record_id: number | string | null;
  detail: string;
  destination: string;
  experiment_id?: number;
  dataset_view_id?: number | null;
  workflow_id?: number;
  source_run_id?: number;
  packages?: Record<string, string>;
}

/** Older servers have no availability contract; never call provenance failure availability failure. */
export function availabilityState(record: ProjectProvenanceRecord): ProvenanceState {
  return record.availability?.state ?? "missing";
}

export function availabilityDetail(record: ProjectProvenanceRecord): string {
  return record.availability?.detail ?? "Availability not checked; see provenance details.";
}

export interface ProjectProvenanceResponse {
  project_id: number;
  project_name: string;
  verified_at: string;
  records: ProjectProvenanceRecord[];
  choice_event_ids: Record<string, number>;
}

export const useProjectProvenanceStore = defineStore("projectProvenance", () => {
  const projectId = ref<number | null>(null);
  const summary = ref<ProjectProvenanceResponse | null>(null);
  const error = ref<string | null>(null);
  const loading = ref(false);
  let requestGeneration = 0;
  let lastFetchedAt = 0;
  let inFlight: { id: number; force: boolean; promise: Promise<void> } | null = null;

  async function refresh(id: number | null, force = true): Promise<void> {
    if (id != null && inFlight?.id === id) {
      if (!force || inFlight.force) return inFlight.promise;
      await inFlight.promise;
      // A project switch may have happened while the cached request finished.
      if (projectId.value !== id) return;
    }
    if (!force && id != null && id === projectId.value && summary.value && Date.now() - lastFetchedAt < 15_000) return;
    const generation = ++requestGeneration;
    projectId.value = id;
    summary.value = null;
    error.value = null;
    if (id === null) {
      lastFetchedAt = 0;
      loading.value = false;
      return;
    }
    loading.value = true;
    const request = (async () => {
      try {
        const response = await api.get<ProjectProvenanceResponse>(`/projects/${id}/provenance`, {
          params: force ? undefined : { summary: true },
        });
        if (generation === requestGeneration && projectId.value === id) {
          summary.value = response.data;
          lastFetchedAt = Date.now();
        }
      } catch (cause) {
        if (generation === requestGeneration) error.value = getErrorMessage(cause, "Project provenance is unavailable.");
      } finally {
        if (generation === requestGeneration) loading.value = false;
      }
    })();
    inFlight = { id, force, promise: request };
    try {
      await request;
    } finally {
      if (inFlight?.promise === request) inFlight = null;
    }
  }

  return { projectId, summary, error, loading, refresh };
});
