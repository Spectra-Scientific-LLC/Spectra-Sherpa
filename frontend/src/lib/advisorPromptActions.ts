import { copyDiagnosticScope, type DiagnosticScope } from "@/utils/diagnosticAdvisor";
export const ADVISOR_PROMPT_REQUEST_EVENT = "advisor-prompt-request";

export interface AdvisorPromptRequestDetail {
  prompt: string;
  autoSend: boolean;
  diagnosticScope?: DiagnosticScope;
}

export function requestAdvisorPrompt(
  prompt: string,
  options?: { autoSend?: boolean; diagnosticScope?: DiagnosticScope },
): void {
  const normalized = prompt.trim();
  if (!normalized) return;

  window.dispatchEvent(
    new CustomEvent<AdvisorPromptRequestDetail>(ADVISOR_PROMPT_REQUEST_EVENT, {
      detail: {
        prompt: normalized,
        ...(options?.diagnosticScope
          ? { diagnosticScope: copyDiagnosticScope(options.diagnosticScope)! }
          : {}),
        autoSend: options?.autoSend ?? true,
      },
    }),
  );
}
