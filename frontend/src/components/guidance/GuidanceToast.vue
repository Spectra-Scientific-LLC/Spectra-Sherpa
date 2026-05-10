<template>
  <Transition name="guidance-toast">
    <aside v-if="toast" class="guidance-toast" role="status" aria-live="polite">
      <div class="guidance-toast__chips">
        <div class="guidance-toast__chip">Guidance</div>
        <div v-if="toast.source === 'llm'" class="guidance-toast__chip guidance-toast__chip--ai">
          AI
        </div>
      </div>
      <button class="guidance-toast__close" type="button" aria-label="Dismiss" @click="guidance.dismiss">
        ×
      </button>
      <h2>{{ toast.title }}</h2>
      <p v-if="toast.body">{{ toast.body }}</p>
      <div class="guidance-toast__actions">
        <button
          v-if="actionLabel"
          class="guidance-toast__primary"
          type="button"
          @click="guidance.clickAction"
        >
          {{ actionLabel }}
        </button>
        <button class="guidance-toast__quiet" type="button" @click="guidance.dontShowAgain">
          Don't show again
        </button>
      </div>
    </aside>
  </Transition>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { resolveGuidanceAction } from "@/lib/actionOntology";
import { useGuidanceStore } from "@/stores/guidance";

const guidance = useGuidanceStore();
const toast = computed(() => guidance.activeToast);
const actionLabel = computed(() => {
  const action = resolveGuidanceAction(toast.value?.action_id);
  return action?.label ?? null;
});
</script>

<style scoped>
.guidance-toast {
  position: fixed;
  right: calc(var(--chat-width, 0px) + 24px);
  bottom: 24px;
  z-index: 9600;
  width: min(360px, calc(100vw - var(--chat-width, 0px) - 48px));
  padding: 16px;
  border: 1px solid rgba(124, 58, 237, 0.35);
  border-radius: 8px;
  background: #ffffff;
  color: #1f2937;
  box-shadow: 0 16px 40px rgba(31, 41, 55, 0.18);
}

.guidance-toast__chips {
  display: flex;
  align-items: center;
  gap: 6px;
}

.guidance-toast__chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 3px 8px;
  border-radius: 999px;
  background: #ede9fe;
  color: #6d28d9;
  font-size: 12px;
  font-weight: 700;
}

.guidance-toast__chip--ai {
  background: #f5f3ff;
  color: #4c1d95;
}

.guidance-toast__close {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #6b7280;
  cursor: pointer;
  font-size: 20px;
}

.guidance-toast__close:hover {
  background: #f3f4f6;
}

.guidance-toast h2 {
  margin: 12px 24px 6px 0;
  font-size: 16px;
  line-height: 1.3;
}

.guidance-toast p {
  margin: 0;
  color: #4b5563;
  font-size: 14px;
  line-height: 1.45;
}

.guidance-toast__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 14px;
}

.guidance-toast__primary,
.guidance-toast__quiet {
  min-height: 34px;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.guidance-toast__primary {
  padding: 0 12px;
  border: 1px solid #7c3aed;
  background: #7c3aed;
  color: white;
}

.guidance-toast__quiet {
  padding: 0 8px;
  border: 1px solid transparent;
  background: transparent;
  color: #6b7280;
}

.guidance-toast__quiet:hover {
  background: #f5f3ff;
  color: #5b21b6;
}

.guidance-toast-enter-active,
.guidance-toast-leave-active {
  transition:
    opacity 160ms ease,
    transform 160ms ease;
}

.guidance-toast-enter-from,
.guidance-toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (max-width: 720px) {
  .guidance-toast {
    right: 16px;
    bottom: 16px;
    width: calc(100vw - 32px);
  }
}
</style>
