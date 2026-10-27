import { defineStore } from "pinia";
import { computed, nextTick, ref, watch } from "vue";
import { useRouter, isNavigationFailure, NavigationFailureType } from "vue-router";
import { useAdvisorStore } from "@/stores/advisor";
import { useLlmStore } from "@/stores/llm";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore } from "@/stores/workflow";
import { useNotifier } from "@/composables/useNotifier";
import { resolveGuidanceAction, type GuidanceActionMeta } from "@/lib/actionOntology";
import { findActionTarget, waitForActionTarget } from "@/lib/actionTargets";
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
      project_id: useProjectStore().currentProjectId,
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
    const projectId = notifications.value.find(item => item.id === toast.notification_id)?.project_id ?? useProjectStore().currentProjectId;
    await acknowledgeNotification(toast.notification_id, "clicked");
    await runGuidanceAction(action, projectId);
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
    await runGuidanceAction(action, notification.project_id);
  }

  function unavailable(message: string): false {
    error.value = message;
    useNotifier().notifySystemEvent({ severity: "warning", title: "Action unavailable", message });
    return false;
  }

  async function runGuidanceAction(action: ReturnType<typeof resolveGuidanceAction>, sourceProject = useProjectStore().currentProjectId): Promise<boolean> {
    if (!action) return false;
    const projectId = useProjectStore().currentProjectId;
    if (sourceProject != null && sourceProject !== projectId) return unavailable("This suggestion belongs to another project. Reopen that project first.");
    const sameProject = () => useProjectStore().currentProjectId === projectId;
    if (action.actionId === "open_analysis_starters") {
      // The Workflow route owns an exact, receipt-bound dataset selection.
      // Even a push to the same pathname can discard that query and broaden it
      // to the project collection. Invoke only the current page's guarded action.
      const target = findActionTarget("open_analysis_starters");
      if (router.currentRoute.value.path !== "/workflow" || !target || target.matches(":disabled, [aria-disabled='true']")) {
        return unavailable("Open the selected dataset in Workflow before choosing an Analysis Starter.");
      }
      target.click();
      return true;
    }
    if (["open_workflow", "add_preprocessing", "pick_template"].includes(action.actionId) && router.currentRoute.value.path === "/data") {
      // My Dataset owns selection, target authority and readiness. Invoke its
      // existing handoff rather than bypassing those guards with a bare route.
      const target = findActionTarget("open_workflow");
      if (!target || target.matches(":disabled, [aria-disabled='true']")) return unavailable("Select a ready dataset in My Dataset before opening its workflow.");
      target.click();
      return true;
    }
    // Step order matters: navigate → wait for scope → click target
    // → fire prompt.  ``clickTarget`` and ``prompt`` are mutually
    // exclusive in practice (one opens a modal, the other talks to
    // the chat).  If both are set we run click first so the prompt
    // doesn't get visually obscured by the modal that follows.
    if (action.route) {
      const query: Record<string, string> = { ...action.query };
      if (projectId != null) query[action.route === "/workflow" ? "project_id" : "project"] = String(projectId);
      if (action.route === "/workflow" && useWorkflowStore().workflowId != null) query.workflow_id = String(useWorkflowStore().workflowId);
      if (action.route === "/runs") query.tab = "run_history";
      if (action.route === "/report") {
        const workflow = useWorkflowStore();
        if (workflow.workflowId != null) query.workflow = String(workflow.workflowId);
        if (workflow.restoredRunId != null) query.run = String(workflow.restoredRunId);
      }
      let failed;
      try { failed = await router.push({ path: action.route, query, hash: action.hash }); }
      catch { return unavailable("The requested page could not be loaded. Please try again."); }
      await nextTick();
      if ((failed && !isNavigationFailure(failed, NavigationFailureType.duplicated)) || !sameProject() || router.currentRoute.value.path !== action.route) return unavailable("The requested page could not be opened in the current project.");
    }
    if (action.expectedScope) {
      // PR5 race fix: notification-drawer clicks from another tab
      // race the destination view's onMounted ``switchScope``.
      // Wait up to 2s for advisor scope to settle on the expected
      // (tab, subscope) before firing any follow-on action so it
      // lands in the right topic.  Live in-tab toasts resolve
      // immediately because the scope is already correct.
      if (!await _waitForAdvisorScope(action.expectedScope, 2000, projectId) || !sameProject()) return unavailable("The destination context is not ready. Please try again after it loads.");
    }
    if (action.clickTarget) {
      // Wait for the destination's own action. A missing or disabled
      // target is an explicit refusal, not a successful handoff.
      const target = await waitForActionTarget(action.clickTarget, 2000);
      if (!sameProject() || !target || target.matches(":disabled, [aria-disabled='true']")) return unavailable("This action is not available in the current context.");
      target.click();
    }
    if (action.prompt) {
      requestAdvisorPrompt(action.prompt);
    }
    return true;
  }

  /** Run a Guidance action by id, e.g. from a Starter step's Go button. */
  async function runAction(actionId: string): Promise<boolean> {
    const action = resolveGuidanceAction(actionId);
    if (!action) return false;
    return runGuidanceAction(action);
  }

  function _waitForAdvisorScope(
    target: NonNullable<GuidanceActionMeta["expectedScope"]>,
    timeoutMs: number,
    projectId: number | null,
  ): Promise<boolean> {
    const advisorStore = useAdvisorStore();
    const matches = (): boolean => {
      const node = advisorStore.activeNode;
      return node?.project_id === projectId && node?.tab_key === target.tabKey && (target.subscopeKey == null || node?.subscope_key === target.subscopeKey);
    };
    if (matches()) return Promise.resolve(true);
    return new Promise<boolean>((resolve) => {
      const stop = watch(
        () => advisorStore.activeNode,
        () => {
          if (matches()) {
            stop();
            window.clearTimeout(timer);
            resolve(true);
          }
        },
      );
      const timer = window.setTimeout(() => {
        // Never send a prompt into a prior project/topic after a timeout.
        stop();
        resolve(false);
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
    runAction,
  };
});
