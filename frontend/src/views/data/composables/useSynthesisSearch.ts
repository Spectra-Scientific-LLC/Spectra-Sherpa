import { ref } from "vue";
import api from "@/api/client";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";
import type { ComponentSummary } from "@/stores/synthesis";

export type ComponentSearchRow = ComponentSummary & { selected_xsec_option: number };

export function useSynthesisSearch(
  identity: () => readonly ScopeIdentity[],
  criteria: () => { source: string; query: string },
) {
  const results = ref<ComponentSearchRow[]>([]);
  const searching = ref(false);
  const requests = useScopedRequest(() => [...identity(), criteria().source, criteria().query], () => {
    results.value = [];
    searching.value = false;
  });
  async function search(): Promise<void> {
    const { source, query } = criteria();
    const ticket = requests.begin();
    searching.value = true;
    try {
      const response = await api.get("/synthesis/search", {
        params: { source, query, limit: 1000 }, signal: ticket.signal,
      });
      if (!ticket.isCurrent()) return;
      results.value = ((response.data.components || []) as ComponentSummary[]).map((component) => ({
        ...component, selected_xsec_option: 0,
      }));
    } catch (error) {
      if (ticket.isCurrent()) throw error;
    } finally {
      if (ticket.isCurrent()) searching.value = false;
    }
  }
  return { results, searching, search };
}
