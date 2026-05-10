<template>
  <div
    v-if="rect && guidance.activeGlow"
    class="guidance-glow"
    :style="glowStyle"
    aria-hidden="true"
  ></div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { findActionTarget } from "@/lib/actionTargets";
import { useGuidanceStore } from "@/stores/guidance";

interface GlowRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const guidance = useGuidanceStore();
const rect = ref<GlowRect | null>(null);
let fadeTimer: number | null = null;

const glowStyle = computed(() => {
  if (!rect.value) return {};
  return {
    top: `${rect.value.top - 5}px`,
    left: `${rect.value.left - 5}px`,
    width: `${rect.value.width + 10}px`,
    height: `${rect.value.height + 10}px`,
  };
});

function clearFadeTimer(): void {
  if (fadeTimer !== null) {
    window.clearTimeout(fadeTimer);
    fadeTimer = null;
  }
}

function positionGlow(): void {
  const target = findActionTarget(guidance.activeGlow?.action_id);
  if (!target) {
    rect.value = null;
    return;
  }
  const bounds = target.getBoundingClientRect();
  if (bounds.width <= 0 || bounds.height <= 0) {
    rect.value = null;
    return;
  }
  rect.value = {
    top: bounds.top,
    left: bounds.left,
    width: bounds.width,
    height: bounds.height,
  };
}

function startFadeTimer(notificationId: number): void {
  clearFadeTimer();
  fadeTimer = window.setTimeout(() => {
    guidance.clearGlow(notificationId);
  }, 10_000);
}

watch(
  () => guidance.activeGlow,
  async (event) => {
    clearFadeTimer();
    rect.value = null;
    if (!event) return;
    await nextTick();
    positionGlow();
    if (!rect.value) {
      guidance.clearGlow(event.notification_id);
      return;
    }
    startFadeTimer(event.notification_id);
  },
  { immediate: true }
);

window.addEventListener("resize", positionGlow);
window.addEventListener("scroll", positionGlow, true);

onBeforeUnmount(() => {
  clearFadeTimer();
  window.removeEventListener("resize", positionGlow);
  window.removeEventListener("scroll", positionGlow, true);
});
</script>

<style scoped>
.guidance-glow {
  position: fixed;
  z-index: 9550;
  pointer-events: none;
  border: 2px solid #7c3aed;
  border-radius: 10px;
  box-shadow:
    0 0 0 4px rgba(124, 58, 237, 0.14),
    0 0 22px rgba(124, 58, 237, 0.28);
  animation: guidance-glow-pulse 2s ease-in-out infinite;
}

@keyframes guidance-glow-pulse {
  0%,
  100% {
    opacity: 0.7;
    transform: scale(1);
  }
  50% {
    opacity: 1;
    transform: scale(1.015);
  }
}

@media (prefers-reduced-motion: reduce) {
  .guidance-glow {
    animation: none;
  }
}
</style>
