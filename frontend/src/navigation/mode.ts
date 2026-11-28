// Keeps desktop and browser navigation on the same workspace routes.
import { computed, ref } from "vue";

type NavigationMode = "menu-bar" | "sidebar";
const storageKey = "sherpa-navigation-mode";

export const hasNativeNavigation = typeof window !== "undefined"
  && typeof window.spectraDesktop?.publishNavigation === "function"
  && typeof window.spectraDesktop?.onNavigationCommand === "function";

function initialMode(): NavigationMode {
  if (!hasNativeNavigation) return "sidebar";
  try {
    return localStorage.getItem(storageKey) === "sidebar" ? "sidebar" : "menu-bar";
  } catch {
    return "menu-bar";
  }
}
const preference = ref<NavigationMode>(initialMode());
export const navigationMode = computed(() => preference.value);
export const menuNavigation = computed(() => preference.value === "menu-bar" && hasNativeNavigation);

export function setNavigationMode(mode: NavigationMode): void {
  if (mode === "menu-bar" && !hasNativeNavigation) return;
  preference.value = mode;
  try {
    localStorage.setItem(storageKey, mode);
  } catch {
    // The selected mode still applies to this window.
  }
}
