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

    <div v-else-if="!datasetDict" class="dq-empty">
      <i class="pi pi-info-circle"></i>
      <span>Select a file to view quality metrics</span>
    </div>

    <div v-else class="dq-content">
      <!-- Labels -->
      <div v-if="sampleLabels.length > 0" class="dq-labels">
        <span class="dq-range-label">
          Labels ({{ sampleLabels.length }})
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
            v-if="labelsExpanded && sampleLabels.length > LABEL_PREVIEW_COUNT"
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
import type { SherpaDatasetDict } from "@/types";

const props = withDefaults(
  defineProps<{
    datasetDict: SherpaDatasetDict | null;
    loading?: boolean;
  }>(),
  { loading: false }
);

const labelsExpanded = ref(false);
const LABEL_PREVIEW_COUNT = 5;

const meta = computed(() => {
  const m = props.datasetDict?.metadata as Record<string, unknown> | undefined;
  return {
    labels: (m?.labels ?? m?.sample_labels ?? []) as string[],
    wavenumbers: (m?.wavenumbers ?? []) as number[],
    is_spectra: (m?.is_spectra ?? false) as boolean,
    spectral_technique: (m?.spectral_technique ?? null) as string | null,
  };
});

const sampleLabels = computed(() => meta.value.labels);

const visibleLabels = computed(() => {
  if (labelsExpanded.value) return sampleLabels.value;
  return sampleLabels.value.slice(0, LABEL_PREVIEW_COUNT);
});

const hiddenLabelCount = computed(() =>
  Math.max(0, sampleLabels.value.length - LABEL_PREVIEW_COUNT)
);

interface QcFlag {
  severity: "success" | "warning" | "info";
  message: string;
}

const qcFlags = computed<QcFlag[]>(() => {
  const sd = props.datasetDict;
  if (!sd) return [];
  const flags: QcFlag[] = [];

  // Spectra count
  if (sd.n_samples >= 3) {
    flags.push({ severity: "success", message: "Multiple spectra loaded" });
  } else {
    flags.push({
      severity: "warning",
      message: "Very few spectra — statistical methods may be unreliable",
    });
  }

  // Spectral range (only if numeric feature axis)
  const wn = meta.value.wavenumbers;
  if (wn.length > 1) {
    const range = Math.abs(wn[wn.length - 1] - wn[0]);
    if (range > 100) {
      flags.push({ severity: "success", message: "Adequate spectral range" });
    } else {
      flags.push({ severity: "warning", message: "Narrow spectral range" });
    }
  }

  // Labels
  if (sampleLabels.value.length === 0) {
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
