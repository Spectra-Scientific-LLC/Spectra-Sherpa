import { ref } from "vue";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";

/** Explicit user selection supersedes route/bootstrap restoration, even A → B → A. */
export function useDatasetNavigation(identity: () => readonly ScopeIdentity[]) {
  const intent = ref(0);
  const scopedIdentity = () => [...identity(), intent.value];
  const bootstrap = useScopedRequest(scopedIdentity);
  const route = useScopedRequest(scopedIdentity);
  const focus = useScopedRequest(scopedIdentity);
  function choose(): void { intent.value += 1; }
  return { intent, bootstrap, route, focus, choose };
}
