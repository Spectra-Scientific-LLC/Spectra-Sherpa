export const ADVISOR_PROMPT_REQUEST_EVENT = "advisor-prompt-request";

export interface AdvisorPromptRequestDetail {
  prompt: string;
  autoSend: boolean;
}

export function requestAdvisorPrompt(prompt: string, options?: { autoSend?: boolean }): void {
  const normalized = prompt.trim();
  if (!normalized) return;

  window.dispatchEvent(
    new CustomEvent<AdvisorPromptRequestDetail>(ADVISOR_PROMPT_REQUEST_EVENT, {
      detail: {
        prompt: normalized,
        autoSend: options?.autoSend ?? true,
      },
    }),
  );
}
