/**
 * WebSocket action and event constants for the Sherpa Advisor.
 *
 * These must stay in sync with the Python-side definitions:
 *   - Actions: src/spectra_sherpa/app/ws_actions.py
 *   - Events:  src/spectra_sherpa/app/ws_events.py
 *
 * The contract test `tests/test_ws_contract.py` validates this file against
 * the Python constants. It will fail if they diverge.
 */
export const SHERPA_WS_ACTION = {
  sync: "sherpa_sync",
  decide: "sherpa_decide",
  chat: "sherpa_chat",
  identifyPeaks: "sherpa_identify_peaks",
  generateCode: "sherpa_generate_code",
  chatWithTools: "sherpa_chat_with_tools",
  writeReport: "sherpa_write_report",
  dataStory: "sherpa_data_story",
} as const;

export const SHERPA_WS_EVENT = {
  recommendations: "sherpa_recommendations",
  decisionAck: "sherpa_decision_ack",
  chatStart: "sherpa_chat_start",
  chatChunk: "sherpa_chat_chunk",
  chatDone: "sherpa_chat_done",
  status: "sherpa_status",
  peaksResult: "sherpa_peaks_result",
  peaksError: "sherpa_peaks_error",
  codeResult: "sherpa_code_result",
  codeError: "sherpa_code_error",
  toolStart: "sherpa_tool_start",
  toolResult: "sherpa_tool_result",
  subscriptionRequired: "sherpa_subscription_required",
  error: "sherpa_error",
  reportResult: "sherpa_report_result",
  reportError: "sherpa_report_error",
  dataStoryChunk: "sherpa_data_story_chunk",
  dataStoryResult: "sherpa_data_story_result",
  dataStoryError: "sherpa_data_story_error",
} as const;

export function getSherpaChatAction(useTools: boolean): string {
  return useTools ? SHERPA_WS_ACTION.chatWithTools : SHERPA_WS_ACTION.chat;
}
