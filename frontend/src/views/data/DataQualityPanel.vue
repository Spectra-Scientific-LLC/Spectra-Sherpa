<template>
  <div class="dq-panel">
    <div class="dq-header">
      <i class="pi pi-check-circle"></i>
      <span>Data Quality Summary</span>
    </div>

    <div v-if="loading" class="dq-loading">
      <ProgressSpinner style="width: 28px; height: 28px" />
      <span>Analyzing file...</span>
    </div>

    <div v-else-if="!fileInfo" class="dq-empty">
      <i class="pi pi-info-circle"></i>
      <span>Select a file to view quality metrics</span>
    </div>

    <div v-else class="dq-content">
      <!-- Labels -->
      <div v-if="fileInfo.labels.length > 0" class="dq-labels">
        <span class="dq-range-label">
          Labels ({{ fileInfo.labels.length }})
        </span>
        <div class="dq-label-list" :class="{ 'dq-label-list--expanded': labelsExpanded }">
          <Tag
            v-for="label in visibleLabels"
            :key="label"
            :value="label"
            severity="info"
            class="dq-label-tag"
          />
          <span
            v-if="hiddenLabelCount > 0 && !labelsExpanded"
            class="dq-label-toggle"
            @click="labelsExpanded = true"
          >
            +{{ hiddenLabelCount }} more
          </span>
          <span
            v-if="labelsExpanded && fileInfo.labels.length > LABEL_PREVIEW_COUNT"
            class="dq-label-toggle"
            @click="labelsExpanded = false"
          >
            Show less
          </span>
        </div>
      </div>

      <!-- QC flags -->
      <div class="dq-flags">
        <span class="dq-range-label">QC Checks</span>
        <div class="dq-flag-list">
          <div
            v-for="flag in qcFlags"
            :key="flag.message"
            class="dq-flag"
          >
            <Tag
              :severity="flag.severity"
              :value="flag.severity === 'success' ? 'OK' : flag.severity === 'warning' ? 'WARN' : 'INFO'"
              class="dq-flag-badge"
            />
            <span class="dq-flag-message">{{ flag.message }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import Tag from "primevue/tag";
import ProgressSpinner from "primevue/progressspinner";
import type { FileInfoResponse } from "@/types";

const props = withDefaults(
  defineProps<{
    fileInfo: FileInfoResponse | null;
    loading?: boolean;
  }>(),
  { loading: false }
);

const labelsExpanded = ref(false);
const LABEL_PREVIEW_COUNT = 5;

const visibleLabels = computed(() => {
  if (!props.fileInfo) return [];
  if (labelsExpanded.value) return props.fileInfo.labels;
  return props.fileInfo.labels.slice(0, LABEL_PREVIEW_COUNT);
});

const hiddenLabelCount = computed(() => {
  if (!props.fileInfo) return 0;
  return Math.max(0, props.fileInfo.labels.length - LABEL_PREVIEW_COUNT);
});

interface QcFlag {
  severity: "success" | "warning" | "info";
  message: string;
}

const qcFlags = computed<QcFlag[]>(() => {
  if (!props.fileInfo) return [];
  const flags: QcFlag[] = [];
  const fi = props.fileInfo;

  // Spectra count
  if (fi.num_spectra >= 3) {
    flags.push({ severity: "success", message: "Multiple spectra loaded" });
  } else {
    flags.push({
      severity: "warning",
      message: "Very few spectra — statistical methods may be unreliable",
    });
  }

  // Wavenumber range
  if (
    fi.wavenumber_min !== null &&
    fi.wavenumber_max !== null &&
    fi.wavenumber_max - fi.wavenumber_min > 100
  ) {
    flags.push({ severity: "success", message: "Adequate spectral range" });
  } else if (fi.wavenumber_min !== null && fi.wavenumber_max !== null) {
    flags.push({ severity: "warning", message: "Narrow spectral range" });
  }

  // Absorbance issues
  if (fi.absorbance_min !== null && fi.absorbance_min < -0.1) {
    flags.push({
      severity: "warning",
      message: "Negative absorbance detected — check baseline",
    });
  }
  if (fi.absorbance_max !== null && fi.absorbance_max > 5.0) {
    flags.push({
      severity: "warning",
      message: "High absorbance — possible saturation",
    });
  }

  // Labels
  if (fi.labels.length === 0) {
    flags.push({ severity: "info", message: "No sample labels detected" });
  }

  return flags;
});
</script>

<style scoped>
.dq-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px;
}

.dq-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 0.95rem;
  color: #1e293b;
  margin-bottom: 16px;
}

.dq-header i {
  color: #3b82f6;
}

.dq-loading,
.dq-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px;
  color: #94a3b8;
  text-align: center;
  font-size: 0.9rem;
}

.dq-empty i {
  font-size: 1.5rem;
}

.dq-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dq-range-label {
  font-size: 0.8rem;
  color: #64748b;
  font-weight: 500;
}

.dq-range-value {
  font-size: 0.9rem;
  color: #334155;
  font-weight: 500;
}

.dq-labels {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dq-label-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.dq-label-list--expanded {
  max-height: 160px;
  overflow-y: auto;
}

.dq-label-tag {
  font-size: 0.75rem;
}

.dq-label-toggle {
  font-size: 0.75rem;
  color: #3b82f6;
  cursor: pointer;
  font-weight: 500;
  padding: 2px 6px;
}

.dq-label-toggle:hover {
  text-decoration: underline;
}

.dq-flags {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dq-flag-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dq-flag {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dq-flag-badge {
  font-size: 0.65rem;
  min-width: 40px;
  text-align: center;
}

.dq-flag-message {
  font-size: 0.85rem;
  color: #475569;
}
</style>
