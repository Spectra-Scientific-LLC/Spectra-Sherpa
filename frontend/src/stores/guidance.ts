import { defineStore } from "pinia";
import { computed, nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useAdvisorStore } from "@/stores/advisor";
import { useLlmStore } from "@/stores/llm";
import { resolveGuidanceAction, type GuidanceActionMeta } from "@/lib/actionOntology";
import { waitForActionTarget } from "@/lib/actionTargets";
import { requestAdvisorPrompt } from "@/lib/advisorPromptActions";
import {
  acknowledgeGuidanceNotification,
  fetchGuidanceSettings,
  listGuidanceNotifications,
  patchGuidanceSettings,
  type GuidanceAckKind,
  type GuidanceNotification,
  type GuidanceSettings,
  type GuidanceSettingsPatch,
} from "@/lib/guidanceAdapter";

export interface GuidanceEvent {
  type: "guidance.event";
  notification_id: number;
  kind: "toast" | "glow" | "both";
  title: string;
  body?: string | null;
  action_id?: string | null;
  action_version?: number | null;
  rule_id: string;
  confidence: number;
  expires_at: string;
  source: "rule" | "llm";
}

export interface GuidanceUnavailableEvent {
  type: "guidance.unavailable";
  reason?: string | null;
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
  const activeGlow = ref<GuidanceEvent | null>(null);
  const notifications = ref<GuidanceNotification[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const canShowToast = computed(() => settings.value.guidance_enabled && settings.value.toast_enabled);
  const canShowGlow = computed(() => settings.value.guidance_enabled && settings.value.glow_enabled);
  const isEnabled = computed(() => canShowToast.value || canShowGlow.value);

  function _actionVersionMatches(event: GuidanceEvent): boolean {
    const action = resolveGuidanceAction(event.action_id);
    if (!action) return false;
    if (event.action_version == null) return true;
    return action.actionVersion === event.action_version;
  }

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

  // Returns true on success, false if the fetch failed.  Audit F2: the
  // failure must be observable to the caller — a transient 401 / startup
  // race used to leave settings at the disabled default with no retry,
  // silently freezing guidance off until a full reload.  Callers
  // (useGuidance.start) retry on a false return.
  async function loadSettings(): Promise<boolean> {
    loading.value = true;
    error.value = null;
    try {
      settings.value = await fetchGuidanceSettings();
      return true;
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Failed to load guidance settings.";
      return false;
    } finally {
      loading.value = false;
    }
  }

  async function updateSettings(patch: GuidanceSettingsPatch): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      settings.value = await patchGuidanceSettings(patch);
      if (!canShowToast.value) activeToast.value = null;
      if (!canShowGlow.value) activeGlow.value = null;
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Failed to update guidance settings.";
    } finally {
      loading.value = false;
    }
  }

  async function handleEvent(event: GuidanceEvent): Promise<void> {
    if (!settings.value.guidance_enabled) return;
    const shouldShowToast = canShowToast.value && (event.kind === "toast" || event.kind === "both");
    const shouldShowGlow =
      canShowGlow.value && (event.kind === "glow" || event.kind === "both") && _actionVersionMatches(event);
    if (!shouldShowToast && !shouldShowGlow) return;

    if (shouldShowToast) activeToast.value = event;
    if (shouldShowGlow) activeGlow.value = event;
    _upsertNotificationFromEvent(event);
    _sendWsAck(event.notification_id, "shown");
    try {
      await acknowledgeGuidanceNotification(event.notification_id, "shown");
    } catch {
      /* WebSocket ack already best-efforted; avoid hiding the useful nudge. */
    }
  }

  function markUnavailable(event?: GuidanceUnavailableEvent): void {
    settings.value = {
      ...settings.value,
      guidance_enabled: false,
    };
    activeToast.value = null;
    activeGlow.value = null;
    const reason = event?.reason === "entitlement_required" ? " Your plan does not include Guidance." : "";
    error.value = `Guidance is unavailable for this deployment.${reason}`;
  }

  function _clearActive(notificationId: number): void {
    if (activeToast.value?.notification_id === notificationId) {
      activeToast.value = null;
    }
    if (activeGlow.value?.notification_id === notificationId) {
      activeGlow.value = null;
    }
  }

  function clearGlow(notificationId?: number): void {
    if (notificationId == null || activeGlow.value?.notification_id === notificationId) {
      activeGlow.value = null;
    }
  }

  function _upsertNotificationFromEvent(event: GuidanceEvent): void {
    const existing = notifications.value.find((item) => item.id === event.notification_id);
    if (existing) {
      existing.shown_at = existing.shown_at ?? new Date().toISOString();
      return;
    }
    notifications.value.unshift({
      id: event.notification_id,
      project_id: null,
      advisor_node_id: null,
      rule_id: event.rule_id,
      kind: event.kind,
      title: event.title,
      body: event.body,
      action_id: event.action_id,
      action_version: event.action_version,
      confidence: event.confidence,
      source: event.source,
      created_at: new Date().toISOString(),
      expires_at: event.expires_at,
      shown_at: new Date().toISOString(),
      dismissed_at: null,
      clicked_at: null,
    });
  }

  function _mergeNotification(update: GuidanceNotification): void {
    const index = notifications.value.findIndex((item) => item.id === update.id);
    if (index >= 0) {
      notifications.value[index] = update;
    } else {
      notifications.value.unshift(update);
    }
  }

  async function acknowledgeNotification(notificationId: number, ackKind: GuidanceAckKind): Promise<void> {
    _clearActive(notificationId);
    _sendWsAck(notificationId, ackKind);
    try {
      const updated = await acknowledgeGuidanceNotification(notificationId, ackKind);
      _mergeNotification(updated);
    } catch {
      /* best-effort telemetry */
    }
  }

  async function acknowledge(ackKind: GuidanceAckKind): Promise<void> {
    const target = activeToast.value ?? activeGlow.value;
    if (!target) return;
    await acknowledgeNotification(target.notification_id, ackKind);
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
    await acknowledgeNotification(toast.notification_id, "clicked");
    await runGuidanceAction(action);
  }

  async function acknowledgeActionClick(actionId: string): Promise<void> {
    const target =
      activeGlow.value?.action_id === actionId
        ? activeGlow.value
        : activeToast.value?.action_id === actionId
          ? activeToast.value
          : null;
    if (!target) return;
    await acknowledgeNotification(target.notification_id, "clicked");
  }

  async function clickNotification(notification: GuidanceNotification): Promise<void> {
    const action = resolveGuidanceAction(notification.action_id);
    await acknowledgeNotification(notification.id, "clicked");
    await runGuidanceAction(action);
  }

  async function runGuidanceAction(action: ReturnType<typeof resolveGuidanceAction>): Promise<void> {
    if (!action) return;
    // Step order matters: navigate → wait for scope → click target
    // → fire prompt.  ``clickTarget`` and ``prompt`` are mutually
    // exclusive in practice (one opens a modal, the other talks to
    // the chat).  If both are set we run click first so the prompt
    // doesn't get visually obscured by the modal that follows.
    if (action.route) {
      await router.push(action.route);
      await nextTick();
    }
    if (action.expectedScope) {
      // PR5 race fix: notification-drawer clicks from another tab
      // race the destination view's onMounted ``switchScope``.
      // Wait up to 2s for advisor scope to settle on the expected
      // (tab, subscope) before firing any follow-on action so it
      // lands in the right topic.  Live in-tab toasts resolve
      // immediately because the scope is already correct.
      await _waitForAdvisorScope(action.expectedScope, 2000);
    }
    if (action.clickTarget) {
      // PR6: poll the DOM for ``[data-action="<clickTarget>"]`` and
      // click it once it appears.  Closes the deploy-CTA gap from
      // PR5 review — the toast CTA now actually opens the dialog
      // instead of routing to a page the user is already on.  No-op
      // on timeout so navigation still completes if the destination
      // view never mounts the target (route guard reject, error,
      // etc.).
      const target = await waitForActionTarget(action.clickTarget, 2000);
      target?.click();
    }
    if (action.prompt) {
      requestAdvisorPrompt(action.prompt);
    }
  }

  function _waitForAdvisorScope(
    target: NonNullable<GuidanceActionMeta["expectedScope"]>,
    timeoutMs: number,
  ): Promise<void> {
    const advisorStore = useAdvisorStore();
    const matches = (): boolean => {
      const node = advisorStore.activeNode;
      return node?.tab_key === target.tabKey && (target.subscopeKey == null || node?.subscope_key === target.subscopeKey);
    };
    if (matches()) return Promise.resolve();
    return new Promise<void>((resolve) => {
      const stop = watch(
        () => advisorStore.activeNode,
        () => {
          if (matches()) {
            stop();
            window.clearTimeout(timer);
            resolve();
          }
        },
      );
      const timer = window.setTimeout(() => {
        // Timeout — proceed anyway.  Worst case the prompt lands in
        // the prior topic; better than hanging the click forever if
        // the destination view never mounts (network error etc.).
        stop();
        resolve();
      }, timeoutMs);
    });
  }

  async function dismissNotification(notification: GuidanceNotification): Promise<void> {
    await acknowledgeNotification(notification.id, "dismissed");
  }

  async function loadNotifications(options?: {
    includeDismissed?: boolean;
    limit?: number;
  }): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      notifications.value = await listGuidanceNotifications(options);
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Failed to load guidance notifications.";
    } finally {
      loading.value = false;
    }
  }

  return {
    settings,
    activeToast,
    activeGlow,
    notifications,
    loading,
    error,
    isEnabled,
    canShowToast,
    canShowGlow,
    loadSettings,
    loadNotifications,
    updateSettings,
    handleEvent,
    markUnavailable,
    dismiss,
    dontShowAgain,
    clickAction,
    clearGlow,
    acknowledgeActionClick,
    clickNotification,
    dismissNotification,
  };
});
