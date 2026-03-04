import { defineStore } from "pinia";
import { ref } from "vue";
import type { LlmMessage } from "@/types";
import { useLlmStore } from "@/stores/llm";

interface ToolProgress {
  tool_name: string;
  status: "running" | "done" | "error";
  summary?: string;
}

export const useDataImportStore = defineStore("dataImport", () => {
  const messages = ref<LlmMessage[]>([]);
  const activeTools = ref<ToolProgress[]>([]);
  const loading = ref(false);
  const streaming = ref(false);
  const sessionComplete = ref(false);
  let streamingIndex: number | null = null;

  // ── Event bus listener ────────────────────────────────────

  function _onImportEvent(e: Event) {
    const payload = (e as CustomEvent).detail;
    if (!payload || !payload.type) return;

    if (payload.type === "import_start") {
      streamingIndex = messages.value.length;
      messages.value.push({ role: "assistant", content: "" });
      streaming.value = true;
      activeTools.value = [];
    } else if (payload.type === "import_chunk") {
      if (streamingIndex !== null) {
        messages.value[streamingIndex].content += payload.chunk;
      }
    } else if (payload.type === "import_tool_start") {
      activeTools.value.push({
        tool_name: payload.tool_name,
        status: "running",
      });
    } else if (payload.type === "import_tool_result") {
      let idx = -1;
      for (let i = activeTools.value.length - 1; i >= 0; i--) {
        if (
          activeTools.value[i].tool_name === payload.tool_name &&
          activeTools.value[i].status === "running"
        ) {
          idx = i;
          break;
        }
      }
      if (idx >= 0) {
        activeTools.value[idx] = {
          ...activeTools.value[idx],
          status: payload.success ? "done" : "error",
          summary: payload.summary,
        };
      }
    } else if (payload.type === "import_error") {
      streaming.value = false;
      loading.value = false;
      streamingIndex = null;
      messages.value.push({
        role: "assistant",
        content: payload.detail || "Import request failed.",
      });
    } else if (payload.type === "import_done") {
      streaming.value = false;
      loading.value = false;
      streamingIndex = null;
      sessionComplete.value = true;
      messages.value.push({
        role: "system",
        content:
          "Job done. Please click the LLM Data Import tab again to start another session.",
      });
    }
  }

  function init() {
    window.addEventListener("import-ws-message", _onImportEvent);
  }

  function dispose() {
    window.removeEventListener("import-ws-message", _onImportEvent);
  }

  // ── Actions ───────────────────────────────────────────────

  async function sendMessage(message: string, metadata?: Record<string, unknown>) {
    if (!message.trim() || sessionComplete.value) return;

    const llmStore = useLlmStore();
    try {
      await llmStore.connect();
    } catch {
      messages.value.push({
        role: "assistant",
        content: "Unable to connect. Check the API key and try again.",
      });
      return;
    }

    loading.value = true;
    activeTools.value = [];
    messages.value.push({ role: "user", content: message });
    llmStore.wsRef?.send(
      JSON.stringify({
        action: "llm_data_import",
        message,
        metadata: metadata ?? null,
      })
    );
  }

  function resetSession() {
    messages.value = [];
    activeTools.value = [];
    loading.value = false;
    streaming.value = false;
    sessionComplete.value = false;
    streamingIndex = null;
  }

  return {
    messages,
    activeTools,
    loading,
    streaming,
    sessionComplete,
    init,
    dispose,
    sendMessage,
    resetSession,
  };
});
