<template>
  <div class="library-tab">
    <div class="tab-section">
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

      <DataTable :value="store.library" stripedRows :paginator="true" :rows="10">
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
  </div>

  <!-- Preview Dialog with Plot -->
  <Dialog
    v-model:visible="previewVisible"
    :header="`Spectrum: ${previewEntry?.compound_name || ''}`"
    :modal="true"
    style="width: min(900px, 90vw)"
  >
    <div v-if="previewEntry" class="preview-content">
      <div class="metadata-row">
        <div class="metadata-item">
          <label>CAS Number:</label>
          <span>{{ previewEntry.cas_number }}</span>
        </div>
        <div class="metadata-item">
          <label>Resolution:</label>
          <span>{{ previewEntry.resolution }} cm⁻¹</span>
        </div>
        <div class="metadata-item">
          <label>Data Points:</label>
          <span>{{ spectrumData?.num_points || '-' }}</span>
        </div>
      </div>

      <div v-if="loadingSpectrum" class="loading-state">
        <ProgressSpinner />
        <p>Loading spectrum data...</p>
      </div>

      <div v-else-if="spectrumData" class="plot-container">
        <PlotlyChart :data="plotData" :layout="plotLayout" />
      </div>

      <div v-else class="error-state">
        <p>Unable to load spectrum data</p>
      </div>
    </div>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dialog from "primevue/dialog";
import ProgressSpinner from "primevue/progressspinner";
import { useToast } from "primevue/usetoast";
import { useNistStore } from "@/stores/nist";
import { useBuilderStore } from "@/stores/builder";
import { downloadCsv } from "@/utils/download";
import { formatDateTime } from "@/utils/format";
import PlotlyChart from "@/components/PlotlyChart.vue";
import type { NistLibraryEntry } from "@/types";
import api from "@/api/client";

const store = useNistStore();
const builderStore = useBuilderStore();
const toast = useToast();

const previewEntry = ref<NistLibraryEntry | null>(null);
const previewVisible = ref(false);
const spectrumData = ref<any>(null);
const loadingSpectrum = ref(false);

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

const plotData = computed(() => {
  if (!spectrumData.value) return [];

  return [
    {
      x: spectrumData.value.wavenumbers,
      y: spectrumData.value.intensities,
      type: 'scatter',
      mode: 'lines',
      name: spectrumData.value.compound_name,
      line: { color: '#3b82f6', width: 1.5 },
      hovertemplate:
        '<b>%{fullData.name}</b><br>' +
        'Wavenumber: %{x:.1f} cm⁻¹<br>' +
        'Intensity: %{y:.6f}<br>' +
        '<extra></extra>',
    },
  ];
});

const plotLayout = computed(() => ({
  title: {
    text: `FTIR Spectrum: ${spectrumData.value?.compound_name || ''}`,
    font: { size: 16 },
  },
  xaxis: {
    title: 'Wavenumber (cm⁻¹)',
    autorange: 'reversed', // FTIR convention: high to low
    showgrid: true,
    gridcolor: '#e2e8f0',
  },
  yaxis: {
    title: 'Absorption Coefficient',
    showgrid: true,
    gridcolor: '#e2e8f0',
  },
  hovermode: 'closest',
  template: 'plotly_white',
  height: 500,
  margin: { l: 60, r: 40, t: 60, b: 60 },
}));

const fetchSpectrumData = async (libraryId: number) => {
  loadingSpectrum.value = true;
  spectrumData.value = null;

  try {
    const response = await api.get(`/api/v1/nist/library/${libraryId}/spectrum`);
    spectrumData.value = response.data;
  } catch (error) {
    console.error('Failed to load spectrum data:', error);
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to load spectrum data',
      life: 3000,
    });
  } finally {
    loadingSpectrum.value = false;
  }
};

const openPreview = async (entry: NistLibraryEntry) => {
  previewEntry.value = entry;
  previewVisible.value = true;
  await fetchSpectrumData(entry.id);
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

// Watch for dialog close to reset spectrum data
watch(previewVisible, (newVal) => {
  if (!newVal) {
    spectrumData.value = null;
    previewEntry.value = null;
  }
});

onMounted(() => {
  store.fetchLibrary();
});
</script>

<style scoped>
.library-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tab-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
