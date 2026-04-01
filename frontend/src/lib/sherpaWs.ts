export const SHERPA_WS_ACTION = {
  sync: "sherpa_sync",
  chat: "sherpa_chat",
  chatWithTools: "sherpa_chat_with_tools",
  writeReport: "sherpa_write_report",
  dataStory: "sherpa_data_story",
} as const;

export const SHERPA_WS_EVENT = {
  recommendations: "sherpa_recommendations",
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
