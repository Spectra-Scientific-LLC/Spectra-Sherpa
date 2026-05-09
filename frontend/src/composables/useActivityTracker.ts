import { onBeforeUnmount, watch } from "vue";
import { useRoute } from "vue-router";
import { useAppConfig } from "@/composables/useAppConfig";
import { useAdvisorStore } from "@/stores/advisor";
import { useGuidanceStore } from "@/stores/guidance";
import { useLlmStore } from "@/stores/llm";
import { useProjectStore } from "@/stores/project";

type GuidanceActivityKind = "route_change" | "scope_switch" | "action_click" | "idle_tick";

interface ActivityPayload {
  kind: GuidanceActivityKind;
  route: string;
  target?: string;
  project_id?: number;
  scope_node_id?: number;
  idle_seconds?: number;
  occurred_at: string;
}

export function useActivityTracker() {
  const route = useRoute();
  const { appMode, isFeatureEnabled } = useAppConfig();
  const guidanceStore = useGuidanceStore();
  const llmStore = useLlmStore();
  const projectStore = useProjectStore();
  const advisorStore = useAdvisorStore();
  let idleTimer: number | null = null;
  let unwatchRoute: (() => void) | null = null;
  let unwatchScope: (() => void) | null = null;
  let lastActivityAt = Date.now();

  function canTrack(): boolean {
    return appMode.value !== "local" && isFeatureEnabled("sherpaGuidance") && guidanceStore.isEnabled;
  }

  function send(kind: GuidanceActivityKind, extras: Partial<ActivityPayload> = {}): void {
    if (!canTrack()) return;
    const ws = llmStore.wsRef;
    if (ws?.readyState !== WebSocket.OPEN) return;
    const projectId = projectStore.currentProjectId ?? undefined;
    const scopeNodeId = advisorStore.activeNodeId ?? undefined;
    const payload: ActivityPayload = {
      kind,
      route: route.path,
      project_id: projectId,
      scope_node_id: scopeNodeId,
      occurred_at: new Date().toISOString(),
      ...extras,
    };
    ws.send(JSON.stringify({ action: "guidance.activity", payload }));
  }

  function noteActivity(): void {
    lastActivityAt = Date.now();
  }

  function onClick(event: MouseEvent): void {
    noteActivity();
    const target = event.target instanceof Element ? event.target.closest("[data-action]") : null;
    const actionId = target?.getAttribute("data-action")?.trim();
    if (actionId) {
      send("action_click", { target: actionId });
    }
  }

  function start(): void {
    if (appMode.value === "local" || !isFeatureEnabled("sherpaGuidance")) {
      return;
    }
    document.addEventListener("click", onClick, { capture: true });
    document.addEventListener("keydown", noteActivity, { capture: true });
    unwatchRoute = watch(
      () => route.fullPath,
      () => {
        noteActivity();
        send("route_change", { route: route.path });
      },
      { immediate: true }
    );
    unwatchScope = watch(
      () => advisorStore.activeNodeId,
      () => {
        send("scope_switch");
      }
    );
    idleTimer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      const idleSeconds = Math.floor((Date.now() - lastActivityAt) / 1000);
      if (idleSeconds >= 30) {
        send("idle_tick", { idle_seconds: idleSeconds });
      }
    }, 30_000);
  }

  function stop(): void {
    document.removeEventListener("click", onClick, { capture: true });
    document.removeEventListener("keydown", noteActivity, { capture: true });
    unwatchRoute?.();
    unwatchScope?.();
    unwatchRoute = null;
    unwatchScope = null;
    if (idleTimer !== null) {
      window.clearInterval(idleTimer);
      idleTimer = null;
    }
  }

  onBeforeUnmount(stop);

  return { start, stop };
}
