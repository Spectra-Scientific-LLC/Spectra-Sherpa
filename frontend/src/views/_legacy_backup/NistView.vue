<template>
  <section class="card nist-view">
    <div class="section-header">
      <div>
        <h1>NIST Library</h1>
        <p class="section-subtitle">Search, download, and load spectral libraries.</p>
      </div>
      <div class="header-actions">
        <span
          v-if="jobStore.connectionStatus !== 'connected'"
          class="ws-status"
          :class="jobStore.connectionStatus"
        >
          {{
            jobStore.connectionStatus === "connecting"
              ? "Realtime reconnecting..."
              : "Realtime disconnected"
          }}
          <span v-if="jobStore.lastError">({{ jobStore.lastError }})</span>
        </span>
      </div>
    </div>

    <TabView v-model:activeIndex="activeTab" class="page-tabs">
      <TabPanel header="Search">
        <div class="panel search-panel">
          <div class="field">
            <label>Search</label>
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

        <DataTable
          :value="store.searchResults"
          stripedRows
          responsiveLayout="scroll"
          class="mt-3"
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
      </TabPanel>

      <TabPanel header="Queue">
        <div v-if="downloadQueue.length" class="panel">
          <h3>Download Queue</h3>
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
        <div v-else class="panel">
          <p class="muted-text">No active downloads yet.</p>
        </div>
      </TabPanel>

      <TabPanel header="Library">
        <div class="panel">
          <div class="section-header">
            <h3>Downloaded Library</h3>
            <div class="tab-actions">
              <Button
                label="Refresh Library"
                icon="pi pi-refresh"
                class="p-button-text"
                @click="store.fetchLibrary"
              />
              <Button label="Export CSV" class="p-button-text" @click="exportLibrary" />
            </div>
          </div>
          <DataTable :value="store.library" stripedRows :paginator="true" :rows="8">
            <Column field="compound_name" header="Compound" sortable />
            <Column field="cas_number" header="CAS" />
            <Column field="resolution" header="Resolution" />
            <Column field="downloaded_at" header="Downloaded">
              <template #body="slotProps">
                {{ formatDateTime(slotProps.data.downloaded_at) }}
              </template>
            </Column>
            <Column header="Actions">
              <template #body="slotProps">
                <Button
                  label="Preview"
                  class="p-button-text"
                  @click="openPreview(slotProps.data)"
                />
                <Button
                  label="Load"
                  class="p-button-text"
                  @click="loadToBuilder(slotProps.data)"
                />
              </template>
            </Column>
          </DataTable>
        </div>
      </TabPanel>
    </TabView>
  </section>

  <Dialog v-model:visible="previewVisible" header="Library Preview" :modal="true">
    <div v-if="previewEntry" class="stack">
      <p><strong>{{ previewEntry.compound_name }}</strong></p>
      <p class="muted-text">CAS: {{ previewEntry.cas_number }}</p>
      <p class="muted-text">Resolution: {{ previewEntry.resolution }}</p>
      <p class="muted-text">Path: {{ previewEntry.file_path }}</p>
    </div>
  </Dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import AutoComplete from "primevue/autocomplete";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dialog from "primevue/dialog";
import TabPanel from "primevue/tabpanel";
import TabView from "primevue/tabview";
import { useToast } from "primevue/usetoast";

import { useNistStore } from "@/stores/nist";
import { useJobStore } from "@/stores/job";
import { useBuilderStore } from "@/stores/builder";
import JobProgressBar from "@/components/JobProgressBar.vue";
import { downloadCsv } from "@/utils/download";
import { formatDateTime } from "@/utils/format";
import type { NistLibraryEntry, NistSearchResult } from "@/types";

const store = useNistStore();
const jobStore = useJobStore();
const builderStore = useBuilderStore();
const toast = useToast();

const activeTab = ref(0);
const searchQuery = ref("");
const suggestions = ref<string[]>([]);
const previewEntry = ref<NistLibraryEntry | null>(null);
const previewVisible = ref(false);
const hadRealtime = ref(false);

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
    activeTab.value = 1;
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
    activeTab.value = 1;
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

const exportLibrary = () => {
  downloadCsv(
    [
      ["compound_name", "cas_number", "resolution", "file_path", "downloaded_at"],
      ...store.library.map((entry) => [
        entry.compound_name,
        entry.cas_number,
        entry.resolution,
        entry.file_path,
        entry.downloaded_at,
      ]),
    ],
    "nist_library.csv"
  );
};

const openPreview = (entry: NistLibraryEntry) => {
  previewEntry.value = entry;
  previewVisible.value = true;
};

const loadToBuilder = (entry: NistLibraryEntry) => {
  builderStore.addLibraryEntry(entry);
  toast.add({
    severity: "success",
    summary: "Loaded",
    detail: `${entry.compound_name} added to builder.`,
    life: 3000,
  });
};

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

onMounted(() => {
  jobStore.connect();
  jobStore.fetchJobs();
  store.fetchLibrary();
});
</script>

<style scoped>
.nist-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.tab-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ws-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #fde047;
  background: #fefce8;
  color: #a16207;
  font-size: 0.85rem;
}

.ws-status.disconnected {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

.ws-status.connecting {
  border-color: #fde047;
  background: #fefce8;
  color: #a16207;
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
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid #e2e8f0;
}

.queue-row:last-child {
  border-bottom: none;
}

.mt-3 {
  margin-top: 16px;
}

.w-full {
  width: 100%;
}

.ml-2 {
  margin-left: 8px;
}
</style>
