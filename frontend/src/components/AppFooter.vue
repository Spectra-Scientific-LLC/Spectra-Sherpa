<template>
  <footer class="app-footer" :class="{ 'app-footer-drift': versionDrift }">
    <span class="app-footer-brand">SpectraSherpa</span>
    <span class="app-footer-sep">·</span>
    <span class="app-footer-version" :title="versionTooltip">
      FE {{ frontendVersion }} · BE {{ backendVersion ?? "—" }}
    </span>
    <span v-if="versionDrift" class="app-footer-drift-badge" :title="driftTooltip">
      <i class="pi pi-exclamation-triangle"></i> bundle drift
    </span>
  </footer>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useAppVersion } from "@/composables/useAppVersion";

const { frontendVersion, backendVersion, versionDrift } = useAppVersion();

const versionTooltip = computed(() => {
  if (backendVersion.value === null) {
    return `Frontend bundle ${frontendVersion}; backend version unavailable.`;
  }
  return `Frontend bundle ${frontendVersion}; backend ${backendVersion.value}.`;
});

const driftTooltip = computed(
  () =>
    `Frontend bundle (${frontendVersion}) and backend (${backendVersion.value}) ` +
    `do not match. Hard-reload your browser to pick up the latest bundle.`,
);
</script>

<style scoped>
.app-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 16px;
  font-size: 0.75rem;
  color: #6b7280;
  background: #f9fafb;
  border-top: 1px solid #e5e7eb;
  flex: 0 0 auto;
  user-select: none;
}

.app-footer-brand {
  font-weight: 600;
  color: #4b5563;
}

.app-footer-sep {
  color: #d1d5db;
}

.app-footer-version {
  font-family: "SF Mono", "Monaco", "Menlo", "Courier New", monospace;
  font-size: 0.7rem;
}

.app-footer-drift {
  background: #fffbeb;
  color: #92400e;
  border-top-color: #fde68a;
}

.app-footer-drift .app-footer-brand,
.app-footer-drift .app-footer-sep {
  color: #92400e;
}

.app-footer-drift-badge {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
}

.app-footer-drift-badge i {
  font-size: 0.7rem;
}
</style>
