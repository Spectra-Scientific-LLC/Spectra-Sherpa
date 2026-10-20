<template>
  <Transition name="guidance-toast">
    <aside v-if="toast" class="guidance-toast" role="status" aria-live="polite">
      <div class="guidance-toast__chips">
        <div class="guidance-toast__chip">Guidance</div>
        <div v-if="toast.source === 'llm'" class="guidance-toast__chip guidance-toast__chip--ai">
          AI
        </div>
      </div>
      <button class="guidance-toast__close" type="button" aria-label="Dismiss" @click="dismiss">
        ×
      </button>
      <h2>{{ toast.title }}</h2>
      <p v-if="toast.body">{{ toast.body }}</p>
      <div class="guidance-toast__actions">
        <button
          v-if="actionLabel"
          class="guidance-toast__primary"
          type="button"
          @click="clickAction"
        >
          {{ actionLabel }}
        </button>
        <button v-if="!scientificQuerySuggestion" class="guidance-toast__quiet" type="button" @click="guidance.dontShowAgain">
          Don't show again
        </button>
      </div>
    </aside>
  </Transition>
</template>

<script setup lang="ts">
import { scientificQuerySuggestion } from "@/lib/scientificQueryGuidance";
import { requestAdvisorPrompt } from "@/lib/advisorPromptActions";
import { computed } from "vue";
import { resolveGuidanceAction } from "@/lib/actionOntology";
import { useGuidanceStore } from "@/stores/guidance";

const guidance = useGuidanceStore();
const toast = computed(() => scientificQuerySuggestion.value
  ? { title: "Sherpa Advisor Guidance", body: `Try: ${scientificQuerySuggestion.value}`, source: "rule", action_id: null }
  : guidance.activeToast);
function dismiss(): void {
  if (scientificQuerySuggestion.value) scientificQuerySuggestion.value = null;
  else guidance.dismiss();
}
function clickAction(): void {
  if (scientificQuerySuggestion.value) requestAdvisorPrompt(scientificQuerySuggestion.value, { autoSend: false });
  else void guidance.clickAction();
}
const actionLabel = computed(() => {
  if (scientificQuerySuggestion.value) return "Ask Sherpa";
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
  border: 1px solid color-mix(in srgb, var(--ss-accent) 35%, transparent);
  border-radius: 8px;
  background: var(--ss-surface);
  color: var(--ss-text-strong);
  box-shadow: 0 16px 40px color-mix(in srgb, var(--ss-shadow-color) 18%, transparent);
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
  background: var(--ss-accent-faint);
  color: var(--ss-accent);
  font-size: 12px;
  font-weight: 700;
}

.guidance-toast__chip--ai {
  background: var(--ss-accent-faint);
  color: var(--ss-accent);
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
  color: var(--ss-text-muted);
  cursor: pointer;
  font-size: 20px;
}

.guidance-toast__close:hover {
  background: var(--ss-surface-subtle);
}

.guidance-toast h2 {
  margin: 12px 24px 6px 0;
  font-size: 16px;
  line-height: 1.3;
}

.guidance-toast p {
  margin: 0;
  color: var(--ss-text-body);
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
  border: 1px solid var(--ss-accent);
  background: var(--ss-accent);
  color: var(--ss-on-action);
}

.guidance-toast__quiet {
  padding: 0 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--ss-text-muted);
}

.guidance-toast__quiet:hover {
  background: var(--ss-accent-faint);
  color: var(--ss-accent);
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
