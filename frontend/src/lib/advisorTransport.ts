/** Product-owned Advisor transport. No package discovery or mode-name dispatch. */
import { shallowRef } from "vue";

export interface AdvisorTransport {
  prepareContext(workflowId: number | null): Promise<Record<string, unknown> | null>;
  loadConversation(id: string): Promise<any>;
  deleteConversation(id: string): Promise<unknown>;
  confirmProposal(sourceWorkflowId: number, proposal: Record<string, any>): Promise<number>;
}

const installed = shallowRef<AdvisorTransport | null>(null);
export function installAdvisorTransport(transport: AdvisorTransport): () => void {
  installed.value = transport;
  return () => {
    if (installed.value === transport) installed.value = null;
  };
}
export function requireAdvisorTransport(): AdvisorTransport {
  if (!installed.value)
    throw new Error(
      "The product's Advisor transport is unavailable. Reload before sharing context.",
    );
  return installed.value;
}
