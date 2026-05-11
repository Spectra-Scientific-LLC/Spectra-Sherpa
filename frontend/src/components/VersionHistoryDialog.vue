<template>
  <Dialog
    v-model:visible="visible"
    modal
    :draggable="false"
    :style="{ width: '560px' }"
    header="Version history"
    class="version-history-dialog"
  >
    <div v-if="!workflowId" class="vh-empty">
      Save this workflow first to start a version history.
    </div>
    <div v-else-if="loading" class="vh-loading">
      <i class="pi pi-spin pi-spinner"></i> Loading versions…
    </div>
    <div v-else-if="loadError" class="vh-error">
      <i class="pi pi-exclamation-triangle"></i>
      {{ loadError }}
    </div>
    <div v-else-if="versions.length === 0" class="vh-empty">
      No saved versions yet. Click <strong>Save version</strong> in the toolbar
      to create a checkpoint.
    </div>
    <ul v-else class="vh-list">
      <li v-for="v in versions" :key="v.id" class="vh-row">
        <div class="vh-row-main">
          <div class="vh-row-title">
            <span class="vh-version-tag">v{{ v.version_number }}</span>
            <span class="vh-version-time" :title="formatFullTimestamp(v.created_at)">
              {{ formatRelative(v.created_at) }}
            </span>
          </div>
          <div v-if="v.change_description" class="vh-row-description">
            {{ v.change_description }}
          </div>
        </div>
        <Button
          :label="opening === v.id ? 'Opening…' : 'Open as new sheet'"
          icon="pi pi-external-link"
          class="p-button-sm p-button-text"
          :disabled="opening !== null"
          :loading="opening === v.id"
          @click="onOpenAsNewSheet(v.id)"
        />
      </li>
    </ul>

    <template #footer>
      <Button label="Close" icon="pi pi-times" @click="visible = false" autofocus />
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Dialog from "primevue/dialog";
import Button from "primevue/button";
import { useToast } from "primevue/usetoast";
import { useWorkbookStore } from "@/stores/workbook";
import { api } from "@/api";
import { getErrorMessage } from "@/utils/errors";

interface VersionSummary {
  id: number;
  workflow_id: number;
  version_number: number;
  created_at: string;
  created_by: number;
  change_description: string | null;
}

const props = defineProps<{ workflowId: number | null }>();
const visible = defineModel<boolean>("visible", { default: false });

const workbookStore = useWorkbookStore();
const toast = useToast();

const versions = ref<VersionSummary[]>([]);
const loading = ref(false);
const loadError = ref<string | null>(null);
const opening = ref<number | null>(null);

const workflowId = computed(() => props.workflowId);

const loadVersions = async () => {
  if (!workflowId.value) {
    versions.value = [];
    return;
  }
  loading.value = true;
  loadError.value = null;
  try {
    const response = await api.get<{ versions: VersionSummary[]; total: number }>(
      `/workflows/${workflowId.value}/versions`,
    );
    versions.value = response.data.versions;
  } catch (err) {
    loadError.value = getErrorMessage(err, "Failed to load version history.");
    versions.value = [];
  } finally {
    loading.value = false;
  }
};

// Refresh whenever the dialog opens (covers the common case where the user
// saved a version, closed the dialog, saved again, and reopens).
watch(visible, (next) => {
  if (next) {
    void loadVersions();
  }
});

const onOpenAsNewSheet = async (versionId: number) => {
  if (!workflowId.value) return;
  opening.value = versionId;
  try {
    const sheet = await workbookStore.openVersionAsSheet(workflowId.value, versionId);
    toast.add({
      severity: "success",
      summary: "Opened as new sheet",
      detail: `"${sheet.name}" is now active in the workbook.`,
      life: 2500,
    });
    visible.value = false;
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Could not open version",
      detail: getErrorMessage(err, "Open-as-new-sheet failed."),
      life: 4000,
    });
  } finally {
    opening.value = null;
  }
};

// Display helpers — relative time for the row, full timestamp on hover.
const RELATIVE_THRESHOLDS: Array<[number, Intl.RelativeTimeFormatUnit]> = [
  [60, "second"],
  [60 * 60, "minute"],
  [60 * 60 * 24, "hour"],
  [60 * 60 * 24 * 30, "day"],
  [60 * 60 * 24 * 365, "month"],
];

const formatRelative = (iso: string): string => {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffSec = Math.round((then - now) / 1000);
  const absSec = Math.abs(diffSec);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  let previousDivisor = 1;
  for (const [divisor, unit] of RELATIVE_THRESHOLDS) {
    if (absSec < divisor) {
      return rtf.format(Math.round(diffSec / previousDivisor), unit);
    }
    previousDivisor = divisor;
  }
  return rtf.format(Math.round(diffSec / (60 * 60 * 24 * 365)), "year");
};

const formatFullTimestamp = (iso: string): string => new Date(iso).toLocaleString();
</script>

<style scoped>
.vh-loading,
.vh-error,
.vh-empty {
  padding: 24px 8px;
  text-align: center;
  color: #6b7280;
  font-size: 0.9rem;
}

.vh-error {
  color: #b91c1c;
}

.vh-loading i {
  margin-right: 8px;
}

.vh-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 60vh;
  overflow-y: auto;
}

.vh-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 4px;
  border-bottom: 1px solid #f3f4f6;
}

.vh-row:last-child {
  border-bottom: none;
}

.vh-row-main {
  flex: 1;
  min-width: 0;
}

.vh-row-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.vh-version-tag {
  font-family: "SF Mono", "Monaco", "Menlo", "Courier New", monospace;
  background: #eef2ff;
  color: #3730a3;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 600;
}

.vh-version-time {
  font-size: 0.85rem;
  color: #6b7280;
}

.vh-row-description {
  margin-top: 4px;
  font-size: 0.85rem;
  color: #374151;
  word-break: break-word;
}
</style>
