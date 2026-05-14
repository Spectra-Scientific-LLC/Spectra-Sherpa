<template>
  <div class="capability-strip" aria-label="Audit capabilities">
    <span :class="['capability', { enabled: canQuery }]">Query</span>
    <span :class="['capability', { enabled: caps?.fullPipeline }]">Chain</span>
    <span :class="['capability', { enabled: caps?.reportPack }]">Pack</span>
    <span :class="['capability', { enabled: caps?.exportAudited }]">Export</span>
  </div>
</template>

<script setup lang="ts">
import type { AuditCapabilities } from "./types";

defineProps<{
  caps: AuditCapabilities | undefined;
  canQuery: boolean;
}>();
</script>

<style scoped>
.capability-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.capability {
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  color: #64748b;
  font-size: 0.82rem;
  font-weight: 700;
  padding: 6px 10px;
}

.capability.enabled {
  background: #dcfce7;
  border-color: #86efac;
  color: #166534;
}
</style>
