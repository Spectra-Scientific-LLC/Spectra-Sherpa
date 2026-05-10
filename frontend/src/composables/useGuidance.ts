import { onBeforeUnmount } from "vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { subscribeSherpaEvents } from "@/lib/sherpaEvents";
import {
  useGuidanceStore,
  type GuidanceEvent,
  type GuidanceUnavailableEvent,
} from "@/stores/guidance";

export function useGuidance() {
  const { appMode, isFeatureEnabled } = useAppConfig();
  const guidanceStore = useGuidanceStore();
  let unsubscribe: (() => void) | null = null;

  async function start(): Promise<void> {
    if (appMode.value === "local" || !isFeatureEnabled("sherpaGuidance")) {
      return;
    }
    await guidanceStore.loadSettings();
    if (!unsubscribe) {
      unsubscribe = subscribeSherpaEvents(
        (payload) => {
          if (payload.type === "guidance.event") {
            void guidanceStore.handleEvent(payload as unknown as GuidanceEvent);
            return;
          }
          if (payload.type === "guidance.unavailable") {
            guidanceStore.markUnavailable(payload as unknown as GuidanceUnavailableEvent);
          }
        },
        { types: ["guidance.event", "guidance.unavailable"] }
      );
    }
  }

  function stop(): void {
    unsubscribe?.();
    unsubscribe = null;
  }

  onBeforeUnmount(stop);

  return { start, stop };
}
