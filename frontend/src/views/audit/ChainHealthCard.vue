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
  border: 1px solid #e2e8f0;
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
  color: #64748b;
  font-size: 0.76rem;
  font-weight: 700;
  margin: 0;
  text-transform: uppercase;
}

.ghost-action {
  align-items: center;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #0f172a;
  cursor: pointer;
  display: inline-flex;
  font-weight: 700;
  gap: 8px;
  min-height: 40px;
  padding: 0 14px;
}

.ghost-action:disabled {
  background: #e2e8f0;
  color: #64748b;
  cursor: not-allowed;
}
</style>
