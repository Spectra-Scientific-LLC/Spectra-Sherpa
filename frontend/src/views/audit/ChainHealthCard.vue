<template>
  <div class="chain-card">
    <div>
      <p class="eyebrow">Chain Health</p>
      <h2>{{ chainStatusLabel }}</h2>
    </div>
    <button
      class="ghost-action"
      type="button"
      data-testid="verify-chain"
      :disabled="isCheckingChain || !caps?.fullPipeline"
      @click="$emit('verify')"
    >
      <i class="pi pi-shield" aria-hidden="true"></i>
      <span>{{ isCheckingChain ? "Checking" : "Verify" }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import type { AuditCapabilities } from "./types";

defineProps<{
  caps: AuditCapabilities | undefined;
  isCheckingChain: boolean;
  chainStatusLabel: string;
}>();

defineEmits<{
  (e: "verify"): void;
}>();
</script>

<style scoped>
.chain-card {
  align-items: center;
  border: 1px solid var(--ss-border);
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  margin-bottom: 14px;
  padding: 12px;
}

.chain-card h2 {
  font-size: 1.1rem;
  letter-spacing: 0;
  margin: 2px 0 0;
}

.eyebrow {
  color: var(--ss-text-muted);
  font-size: 0.76rem;
  font-weight: 700;
  margin: 0;
  text-transform: uppercase;
}

.ghost-action {
  align-items: center;
  background: var(--ss-surface);
  border: 1px solid var(--ss-border-strong);
  border-radius: 8px;
  color: var(--ss-text-strong);
  cursor: pointer;
  display: inline-flex;
  font-weight: 700;
  gap: 8px;
  min-height: 40px;
  padding: 0 14px;
}

.ghost-action:disabled {
  background: var(--ss-border);
  color: var(--ss-text-muted);
  cursor: not-allowed;
}
</style>
