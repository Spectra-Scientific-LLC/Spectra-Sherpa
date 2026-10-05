import { computed, ref, watch } from "vue";
import { api } from "@/api";
import { useAppConfig } from "@/composables/useAppConfig";
import { useProjectStore } from "@/stores/project";
import { useAuthStore } from "@/stores/auth";
interface Availability {
  read: boolean; write: boolean; execute: boolean; chat: boolean; export: boolean; delete: boolean;
  limitations: string; node_types: string[]; chat_privacy_configured: boolean; chat_configured: boolean;
}
export function useProjectAvailability() {
  const { appMode, siteProfile } = useAppConfig();
  const projects = useProjectStore();
  const auth = useAuthStore();
  const qualified = computed(() => appMode?.value === "enterprise" && siteProfile?.value === "pro");
  const availability = ref<Availability | null>(null);
  const error = ref("");
  const loading = ref(false);
  let generation = 0;
  async function refresh() {
    const enabled = qualified.value;
    const projectId = projects.currentProjectId;
    const request = ++generation;
    availability.value = null;
    error.value = "";
    loading.value = false;
    if (!enabled || projectId == null) return;
    loading.value = true;
    try {
      const { data } = await api.get<Availability>(`/commercial/projects/${projectId}/availability`);
      if (request === generation) availability.value = data;
    } catch {
      if (request === generation) error.value = "Could not check project access. Retry, or sign in again if your session has expired.";
    } finally {
      if (request === generation) loading.value = false;
    }
  }
  watch([qualified, () => projects.currentProjectId, () => auth.user?.id], refresh, { immediate: true });
  return { qualified, availability, error, loading, refresh };
}
