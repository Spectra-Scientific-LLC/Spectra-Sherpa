import { onBeforeUnmount } from "vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { subscribeSherpaEvents } from "@/lib/sherpaEvents";
import { useGuidanceStore, type GuidanceEvent } from "@/stores/guidance";

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
          void guidanceStore.handleEvent(payload as unknown as GuidanceEvent);
        },
        { types: ["guidance.event"] }
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
