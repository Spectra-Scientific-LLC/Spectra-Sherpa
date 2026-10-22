import { defineStore } from "pinia";
import { ref } from "vue";
import api from "@/api/client";
import { getErrorMessage } from "@/utils/errors";
import { activeProjectScope, registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import { useAuthStore } from "@/stores/auth";
import { useScopedRequest, type ScopedRequestTicket } from "@/composables/useScopedRequest";

export type ProvenanceState = "healthy" | "missing" | "faulty";
export type ProvenanceKind =
  | "source" | "dataset" | "workflow" | "run" | "environment" | "model" | "campaign" | "package";

export interface ProjectProvenanceRecord {
  kind: ProvenanceKind;
  label: string;
  state: ProvenanceState;
  artifact_integrity?: { state: ProvenanceState; detail: string };
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
  let lastFetchedAt = 0;
  let inFlight: { id: number; force: boolean; promise: Promise<void>; ticket: ScopedRequestTicket } | null = null;
  const requestScope = useScopedRequest(
    () => [useAuthStore().user?.id, useAuthStore().sessionRevision, activeProjectScope.value, projectId.value],
    () => {
      summary.value = null;
      error.value = null;
      loading.value = false;
      lastFetchedAt = 0;
      inFlight = null;
    },
  );
  registerProjectScopeReset(() => {
    requestScope.invalidate();
    projectId.value = null;
  });

  async function refresh(id: number | null, force = true): Promise<void> {
    if (id != null && inFlight?.id === id) {
      if (!force || inFlight.force) return inFlight.promise;
      const previous = inFlight;
      await previous.promise;
      // A project switch may have happened while the cached request finished.
      if (!previous.ticket.isCurrent()) return;
    }
    if (!force && id != null && id === projectId.value && summary.value && Date.now() - lastFetchedAt < 15_000) return;
    projectId.value = id;
    const ticket = requestScope.begin();
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
          signal: ticket.signal,
        });
        if (ticket.isCurrent()) {
          summary.value = response.data;
          lastFetchedAt = Date.now();
        }
      } catch (cause) {
        if (ticket.isCurrent()) error.value = getErrorMessage(cause, "Project provenance is unavailable.");
      } finally {
        if (ticket.isCurrent()) loading.value = false;
      }
    })();
    inFlight = { id, force, promise: request, ticket };
    try {
      await request;
    } finally {
      if (inFlight?.promise === request) inFlight = null;
    }
  }

  return { projectId, summary, error, loading, refresh };
});
