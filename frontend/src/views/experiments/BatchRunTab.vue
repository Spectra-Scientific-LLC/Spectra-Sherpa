<template>
  <div class="batch-run-tab">
    <div class="batch-form">
      <div class="form-field">
        <label for="batch-workflow">Workflow</label>
        <Dropdown
          id="batch-workflow"
          v-model="selectedWorkflowId"
          :options="workflows"
          optionLabel="name"
          optionValue="id"
          placeholder="Select a saved workflow"
          class="w-full"
          :loading="loadingWorkflows"
        />
      </div>

      <div class="form-field">
        <label for="batch-folder">Folder Path</label>
        <InputText
          id="batch-folder"
          v-model="folderPath"
          placeholder="/path/to/spectral/files"
          class="w-full"
        />
      </div>

      <div class="form-row">
        <div class="form-field">
          <label for="batch-pattern">File Pattern</label>
          <InputText
            id="batch-pattern"
            v-model="filePattern"
            placeholder="*.spa"
            class="w-full"
          />
        </div>
        <div class="form-field">
          <label for="batch-name">Run Name (optional)</label>
          <InputText
            id="batch-name"
            v-model="runName"
            :placeholder="suggestedName"
            class="w-full"
          />
        </div>
      </div>

      <div class="form-actions">
        <Button
          label="Start Batch"
          icon="pi pi-play"
          :loading="submitting"
          :disabled="!canSubmit"
          @click="handleSubmit"
        />
      </div>
    </div>

    <!-- Active job progress -->
    <div v-if="activeJob" class="progress-section">
      <div class="progress-header">
        <span class="progress-label">{{ activeJob.message || "Processing..." }}</span>
        <Tag
          :value="activeJob.status"
          :severity="activeJob.status === 'completed' ? 'success' : activeJob.status === 'failed' ? 'danger' : 'info'"
          class="progress-tag"
        />
      </div>
      <ProgressBar :value="activeJob.progress" :showValue="true" />
    </div>

    <!-- Empty state -->
    <div v-if="!activeJob" class="batch-info">
      <i class="pi pi-info-circle"></i>
      <p>
        Select a workflow and specify a folder path on the server containing
        spectral files. Each file will be processed through the workflow and
        results saved for comparison in the Run History tab.
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import Dropdown from "primevue/dropdown";
import InputText from "primevue/inputtext";
import Button from "primevue/button";
import ProgressBar from "primevue/progressbar";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";

import api from "@/api/client";
import { useRunsStore } from "@/stores/runs";
import { useWorkflowStore } from "@/stores/workflow";

interface WorkflowOption {
  id: number;
  name: string;
}

interface JobUpdate {
  status: string;
  progress: number;
  message: string | null;
}

const toast = useToast();
const runsStore = useRunsStore();
const workflowStore = useWorkflowStore();

const workflows = ref<WorkflowOption[]>([]);
const loadingWorkflows = ref(false);
const selectedWorkflowId = ref<number | null>(null);
const folderPath = ref("");
const filePattern = ref("*");
const runName = ref("");
const submitting = ref(false);
const activeJob = ref<JobUpdate | null>(null);

const suggestedName = computed(() => {
  const wf = workflows.value.find((w) => w.id === selectedWorkflowId.value);
  return wf ? `Batch: ${wf.name}` : "Batch prediction run";
});

const canSubmit = computed(
  () => selectedWorkflowId.value && folderPath.value.trim() && !submitting.value
);

onMounted(async () => {
  loadingWorkflows.value = true;
  try {
    const response = await api.get<WorkflowOption[]>("/workflows");
    workflows.value = response.data;
    // Pre-select current workflow if loaded
    if (workflowStore.workflowId) {
      selectedWorkflowId.value = workflowStore.workflowId;
    }
  } catch {
    workflows.value = [];
  } finally {
    loadingWorkflows.value = false;
  }
});

// Listen for job progress via WebSocket
function onJobUpdate(event: Event) {
  const detail = (event as CustomEvent).detail;
  if (!detail || !activeJobId.value) return;
  if (detail.job_id !== activeJobId.value) return;

  activeJob.value = {
    status: detail.status || activeJob.value?.status || "running",
    progress: detail.progress ?? activeJob.value?.progress ?? 0,
    message: detail.message ?? activeJob.value?.message ?? null,
  };

  if (detail.status === "completed" || detail.status === "failed") {
    if (detail.status === "completed") {
      toast.add({
        severity: "success",
        summary: "Batch Complete",
        detail: detail.message || "All files processed",
        life: 5000,
      });
      // Refresh runs list
      if (workflowStore.workflowId) {
        runsStore.fetchRuns(workflowStore.workflowId);
      }
    } else {
      toast.add({
        severity: "error",
        summary: "Batch Failed",
        detail: detail.message || "Batch prediction failed",
        life: 5000,
      });
    }
    // Clean up listener and clear active job after a delay
    window.removeEventListener("job-update", onJobUpdate);
    setTimeout(() => {
      activeJob.value = null;
      activeJobId.value = null;
    }, 3000);
  }
}

// Clean up event listener on component unmount to prevent memory leaks
onBeforeUnmount(() => {
  window.removeEventListener("job-update", onJobUpdate);
});

const activeJobId = ref<number | null>(null);

async function handleSubmit() {
  if (!selectedWorkflowId.value || !folderPath.value.trim()) return;
  submitting.value = true;

  try {
    const result = await runsStore.startBatchRun(selectedWorkflowId.value, {
      folder_path: folderPath.value.trim(),
      file_pattern: filePattern.value || "*",
      run_name: runName.value.trim() || undefined,
    });

    activeJobId.value = result.job_id;
    activeJob.value = {
      status: "running",
      progress: 0,
      message: result.message,
    };

    // Start listening for job updates
    window.addEventListener("job-update", onJobUpdate);

    toast.add({
      severity: "info",
      summary: "Batch Started",
      detail: result.message,
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Batch Failed",
      detail: error?.response?.data?.detail || error?.message || "Could not start batch",
      life: 5000,
    });
  } finally {
    submitting.value = false;
  }
}
</script>

<style scoped>
.batch-run-tab {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.batch-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 600px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-field label {
  font-size: 0.85rem;
  font-weight: 500;
  color: #475569;
}

.form-row {
  display: flex;
  gap: 12px;
}

.form-row .form-field {
  flex: 1;
}

.form-actions {
  display: flex;
  gap: 8px;
}

.progress-section {
  max-width: 600px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.progress-label {
  font-size: 0.85rem;
  color: #475569;
}

.progress-tag {
  font-size: 0.7rem;
  text-transform: uppercase;
}

.batch-info {
  display: flex;
  gap: 8px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  max-width: 600px;
  color: #64748b;
  font-size: 0.85rem;
  line-height: 1.5;
}

.batch-info i {
  flex-shrink: 0;
  margin-top: 2px;
}

.batch-info p {
  margin: 0;
}

.w-full {
  width: 100%;
}
</style>
