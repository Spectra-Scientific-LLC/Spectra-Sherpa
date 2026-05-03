import { onBeforeUnmount, onMounted, ref } from "vue";

export const NARROW_BREAKPOINT_PX = 768;

export function useViewport(query = `(max-width: ${NARROW_BREAKPOINT_PX}px)`) {
  const mql = typeof window !== "undefined" ? window.matchMedia(query) : null;
  const isNarrow = ref(mql?.matches ?? false);

  const handleChange = (event: MediaQueryListEvent) => {
    isNarrow.value = event.matches;
  };

  onMounted(() => {
    if (!mql) return;
    mql.addEventListener("change", handleChange);
  });

  onBeforeUnmount(() => {
    if (!mql) return;
    mql.removeEventListener("change", handleChange);
  });

  return { isNarrow };
}
