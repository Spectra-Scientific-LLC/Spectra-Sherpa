import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { useLlmStore } from "@/stores/llm";
import { resolveGuidanceAction } from "@/lib/actionOntology";
import {
  acknowledgeGuidanceNotification,
  fetchGuidanceSettings,
  patchGuidanceSettings,
  type GuidanceAckKind,
  type GuidanceSettings,
  type GuidanceSettingsPatch,
} from "@/lib/guidanceAdapter";

export interface GuidanceEvent {
  type: "guidance.event";
  notification_id: number;
  kind: "toast";
  title: string;
  body?: string | null;
  action_id?: string | null;
  action_version?: number | null;
  rule_id: string;
  confidence: number;
  expires_at: string;
  source: "rule";
}

const defaultSettings: GuidanceSettings = {
  guidance_enabled: false,
  toast_enabled: true,
  glow_enabled: true,
};

export const useGuidanceStore = defineStore("guidance", () => {
  const router = useRouter();
  const settings = ref<GuidanceSettings>(defaultSettings);
  const activeToast = ref<GuidanceEvent | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const isEnabled = computed(() => settings.value.guidance_enabled && settings.value.toast_enabled);

  function _sendWsAck(notificationId: number, ackKind: GuidanceAckKind): void {
    const llmStore = useLlmStore();
    const ws = llmStore.wsRef;
    if (ws?.readyState !== WebSocket.OPEN) return;
    ws.send(
      JSON.stringify({
        action: "guidance.ack",
        payload: {
          notification_id: notificationId,
          ack_kind: ackKind,
          occurred_at: new Date().toISOString(),
        },
      })
    );
  }

  async function loadSettings(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      settings.value = await fetchGuidanceSettings();
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Failed to load guidance settings.";
    } finally {
      loading.value = false;
    }
  }

  async function updateSettings(patch: GuidanceSettingsPatch): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      settings.value = await patchGuidanceSettings(patch);
      if (!isEnabled.value) activeToast.value = null;
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Failed to update guidance settings.";
    } finally {
      loading.value = false;
    }
  }

  async function handleEvent(event: GuidanceEvent): Promise<void> {
    if (!isEnabled.value) return;
    if (event.kind !== "toast") return;
    activeToast.value = event;
    _sendWsAck(event.notification_id, "shown");
    try {
      await acknowledgeGuidanceNotification(event.notification_id, "shown");
    } catch {
      /* WebSocket ack already best-efforted; avoid hiding the useful nudge. */
    }
  }

  async function acknowledge(ackKind: GuidanceAckKind): Promise<void> {
    const toast = activeToast.value;
    if (!toast) return;
    activeToast.value = null;
    _sendWsAck(toast.notification_id, ackKind);
    try {
      await acknowledgeGuidanceNotification(toast.notification_id, ackKind);
    } catch {
      /* best-effort telemetry */
    }
  }

  async function dismiss(): Promise<void> {
    await acknowledge("dismissed");
  }

  async function dontShowAgain(): Promise<void> {
    await acknowledge("dont_show_again");
  }

  async function clickAction(): Promise<void> {
    const toast = activeToast.value;
    if (!toast) return;
    const action = resolveGuidanceAction(toast.action_id);
    await acknowledge("clicked");
    if (action?.route) {
      await router.push(action.route);
    }
  }

  return {
    settings,
    activeToast,
    loading,
    error,
    isEnabled,
    loadSettings,
    updateSettings,
    handleEvent,
    dismiss,
    dontShowAgain,
    clickAction,
  };
});
