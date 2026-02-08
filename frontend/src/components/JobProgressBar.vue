<template>
  <div class="job-progress">
    <div class="job-progress__meta">
      <span class="job-progress__status">{{ statusLabel }}</span>
      <span v-if="message" class="job-progress__message">{{ message }}</span>
      <span class="job-progress__percent">{{ progress }}%</span>
    </div>
    <div class="job-progress__track">
      <div class="job-progress__bar" :style="{ width: `${progress}%` }"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  progress: number;
  status?: string;
  message?: string | null;
}>();

const statusLabel = computed(() => {
  if (!props.status) {
    return "Queued";
  }
  const normalized = props.status.toLowerCase();
  if (normalized === "running") return "Running";
  if (normalized === "completed") return "Completed";
  if (normalized === "failed") return "Failed";
  if (normalized === "cancelled") return "Cancelled";
  return props.status;
});
</script>

<style scoped>
.job-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.job-progress__meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 0.85rem;
  color: #475569;
}

.job-progress__status {
  font-weight: 600;
}

.job-progress__message {
  flex: 1;
  text-align: center;
  color: #64748b;
}

.job-progress__percent {
  font-variant-numeric: tabular-nums;
}

.job-progress__track {
  height: 6px;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
}

.job-progress__bar {
  height: 100%;
  background: linear-gradient(90deg, #38bdf8, #2563eb);
  transition: width 0.2s ease;
}
</style>
