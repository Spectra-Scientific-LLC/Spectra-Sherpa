<template>
  <div class="search-tab">
    <!-- Search Panel -->
    <div class="tab-section search-panel">
      <div class="field">
        <label>Search Compounds</label>
        <AutoComplete
          v-model="searchQuery"
          :suggestions="suggestions"
          :completeMethod="onComplete"
          placeholder="Search by compound name"
          class="w-full"
        />
      </div>
      <Button label="Search" icon="pi pi-search" @click="runSearch" />
    </div>

    <!-- Results and Queue Layout -->
    <div class="section-two-column">
      <!-- Search Results (Left 70%) -->
      <div class="tab-section">
        <h3>Search Results</h3>
        <DataTable
          :value="store.searchResults"
          stripedRows
          responsiveLayout="scroll"
        >
          <Column field="name" header="Compound" />
          <Column field="cas_number" header="CAS" />
          <Column header="Resolution">
            <template #body>
              <div class="resolution-tags">
                <span class="pill">Standard</span>
                <span class="pill">0.125 cm^-1</span>
              </div>
            </template>
          </Column>
          <Column header="Actions">
            <template #body="slotProps">
              <Button
                label="Download"
                icon="pi pi-download"
                class="p-button-sm"
                @click="downloadStandard(slotProps.data)"
              />
              <Button
                label="High-Res"
                icon="pi pi-cloud-download"
                class="p-button-sm p-button-secondary ml-2"
                @click="downloadHighRes(slotProps.data)"
              />
            </template>
          </Column>
        </DataTable>
      </div>

      <!-- Download Queue (Right 30%) -->
      <div class="tab-section">
        <h3>Download Queue</h3>
        <div v-if="downloadQueue.length" class="stack">
          <div v-for="item in downloadQueue" :key="item.jobId" class="queue-row">
            <div>
              <strong>{{ item.compoundName }}</strong>
              <div class="muted-text">Job #{{ item.jobId }}</div>
            </div>
            <JobProgressBar
              v-if="item.job"
              :progress="item.job.progress"
              :status="item.job.status"
              :message="item.job.progress_message"
            />
            <div v-else class="muted-text">Queued...</div>
          </div>
        </div>
        <div v-else class="empty-state">
          <p class="muted-text">No active downloads</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import AutoComplete from "primevue/autocomplete";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import { useToast } from "primevue/usetoast";
import { useNistStore } from "@/stores/nist";
import { useJobStore } from "@/stores/job";
import JobProgressBar from "@/components/JobProgressBar.vue";
import type { NistSearchResult } from "@/types";

const store = useNistStore();
const jobStore = useJobStore();
const toast = useToast();

const searchQuery = ref("");
const suggestions = ref<string[]>([]);

const downloadQueue = computed(() =>
  store.downloads.map((item) => ({
    ...item,
    job: jobStore.jobs.find((job) => job.id === item.jobId) || null,
  }))
);

const runSearch = async () => {
  try {
    await store.search(searchQuery.value);
    suggestions.value = store.searchResults.map((item) => item.name);
  } catch {
    toast.add({
      severity: "error",
      summary: "Search failed",
      detail: "Unable to reach NIST.",
      life: 3000,
    });
  }
};

const onComplete = async (event: { query: string }) => {
  try {
    await store.search(event.query);
    suggestions.value = store.searchResults.map((item) => item.name);
  } catch {
    toast.add({
      severity: "error",
      summary: "Search failed",
      detail: "Unable to reach NIST.",
      life: 3000,
    });
  }
};

const downloadStandard = async (result: NistSearchResult) => {
  try {
    await store.download({
      cas_number: result.cas_number || result.nist_id,
      compound_name: result.name,
      resolution: "standard",
      index: 0,
    });
    toast.add({
      severity: "info",
      summary: "Download queued",
      detail: `Downloading ${result.name}`,
      life: 3000,
    });
  } catch {
    toast.add({
      severity: "error",
      summary: "Download failed",
      detail: "Unable to queue download.",
      life: 3000,
    });
  }
};

const downloadHighRes = async (result: NistSearchResult) => {
  try {
    await store.download({
      cas_number: result.cas_number || result.nist_id,
      compound_name: result.name,
      resolution: "0.125",
      index: 1,
    });
    toast.add({
      severity: "info",
      summary: "Download queued",
      detail: `Downloading ${result.name} (0.125 cm^-1)`,
      life: 3000,
    });
  } catch {
    toast.add({
      severity: "error",
      summary: "Download failed",
      detail: "Unable to queue download.",
      life: 3000,
    });
  }
};

// Watch for completed jobs and refresh library
watch(
  () => jobStore.jobs,
  () => {
    const completed = store.downloads.filter((item) => {
      const job = jobStore.jobs.find((job) => job.id === item.jobId);
      return job && job.status === "completed";
    });
    if (completed.length > 0) {
      store.fetchLibrary();
      completed.forEach((item) => store.clearDownload(item.jobId));
    }
  },
  { deep: true }
);

// WebSocket status notifications
const hadRealtime = ref(false);
watch(
  () => jobStore.connectionStatus,
  (status, prev) => {
    if (prev === "connected" && status === "disconnected") {
      toast.add({
        severity: "warn",
        summary: "Realtime disconnected",
        detail: jobStore.lastError || "Trying to reconnect...",
        life: 4000,
      });
    }
    if (status === "connected") {
      if (hadRealtime.value && prev === "disconnected") {
        toast.add({
          severity: "success",
          summary: "Realtime restored",
          detail: "Job progress updates are back online.",
          life: 2500,
        });
      }
      hadRealtime.value = true;
    }
  }
);
</script>

<style scoped>
.search-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.search-panel {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  align-items: end;
}

.resolution-tags {
  display: flex;
  gap: 6px;
}

.queue-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 0;
  border-bottom: 1px solid #e2e8f0;
}

.queue-row:last-child {
  border-bottom: none;
}

.empty-state {
  padding: 20px;
  text-align: center;
}

.w-full {
  width: 100%;
}

.ml-2 {
  margin-left: 8px;
}
</style>
