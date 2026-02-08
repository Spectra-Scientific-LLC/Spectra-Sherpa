<template>
  <div class="blend-tab">
    <div class="blend-container">
      <!-- Instructions -->
      <div class="section instructions">
        <h3>
          <i class="pi pi-info-circle"></i>
          Blend NIST Reference Data with Experimental Spectra
        </h3>
        <p class="help-text">
          Mix NIST library spectra with your experimental data to create synthetic validation datasets
          or "spike" experiments with known compounds.
        </p>
      </div>

      <!-- Two-Column Layout -->
      <div class="blend-grid">
        <!-- Left: NIST Selection -->
        <div class="section">
          <div class="section-header">
            <h4>
              <i class="pi pi-database"></i>
              NIST Library Spectra
            </h4>
          </div>

          <DataTable
            v-model:selection="selectedNistSpectra"
            :value="nistStore.library"
            dataKey="id"
            :paginator="true"
            :rows="8"
            stripedRows
            class="spectra-table"
          >
            <Column selectionMode="multiple" style="width: 3em" />
            <Column field="compound_name" header="Compound" sortable />
            <Column field="resolution" header="Resolution" style="width: 120px">
              <template #body="slotProps">
                <Tag :value="slotProps.data.resolution" severity="info" />
              </template>
            </Column>
          </DataTable>

          <div class="selection-summary">
            <strong>{{ selectedNistSpectra.length }}</strong> NIST spectra selected
          </div>
        </div>

        <!-- Right: Experiment Selection -->
        <div class="section">
          <div class="section-header">
            <h4>
              <i class="pi pi-flask"></i>
              Experimental Data
            </h4>
          </div>

          <DataTable
            v-model:selection="selectedExperiments"
            :value="experimentStore.experiments"
            dataKey="id"
            :paginator="true"
            :rows="8"
            stripedRows
            class="spectra-table"
          >
            <Column selectionMode="multiple" style="width: 3em" />
            <Column field="name" header="Experiment" sortable />
            <Column header="Files" style="width: 80px">
              <template #body="slotProps">
                <Tag :value="slotProps.data.file_count || 0" severity="success" />
              </template>
            </Column>
          </DataTable>

          <div class="selection-summary">
            <strong>{{ selectedExperiments.length }}</strong> experiment(s) selected
          </div>
        </div>
      </div>

      <!-- Blending Controls -->
      <div class="section controls-section">
        <div class="section-header">
          <h4>
            <i class="pi pi-sliders-h"></i>
            Blending Controls
          </h4>
        </div>

        <div class="controls-grid">
          <div class="control-group">
            <label>Blending Mode</label>
            <Dropdown
              v-model="blendingMode"
              :options="blendingModes"
              optionLabel="label"
              optionValue="value"
              placeholder="Select blending mode"
            />
            <small class="help-text">
              {{ blendingModeDescription }}
            </small>
          </div>

          <div class="control-group">
            <label>NIST Weight</label>
            <div class="slider-with-value">
              <Slider v-model="nistWeight" :min="0" :max="100" :step="1" />
              <InputNumber
                v-model="nistWeight"
                :min="0"
                :max="100"
                suffix="%"
                class="weight-input"
              />
            </div>
            <small class="help-text">
              Experimental weight: {{ 100 - nistWeight }}%
            </small>
          </div>

          <div class="control-group">
            <label>Noise Level</label>
            <div class="slider-with-value">
              <Slider v-model="noiseLevel" :min="0" :max="10" :step="0.1" />
              <InputNumber
                v-model="noiseLevel"
                :min="0"
                :max="10"
                :step="0.1"
                suffix="%"
                class="weight-input"
              />
            </div>
            <small class="help-text">
              Add Gaussian noise to blended spectra
            </small>
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="actions-section">
        <Button
          label="Preview Blend"
          icon="pi pi-eye"
          class="p-button-outlined"
          :disabled="!canBlend"
          @click="previewBlend"
        />
        <Button
          label="Create Blended Dataset"
          icon="pi pi-check"
          :disabled="!canBlend"
          @click="createBlend"
        />
      </div>

      <!-- Results Preview -->
      <div v-if="blendResult" class="section results-section">
        <div class="section-header">
          <h4>
            <i class="pi pi-chart-line"></i>
            Blend Preview
          </h4>
        </div>

        <div class="result-info">
          <p><strong>Blended Dataset Created:</strong></p>
          <ul>
            <li>{{ blendResult.spectra_count }} spectra</li>
            <li>{{ blendResult.wavenumber_range }} cm<sup>-1</sup> range</li>
            <li>{{ blendResult.nist_components.length }} NIST components</li>
            <li>{{ blendResult.experimental_components.length }} experimental sources</li>
          </ul>
        </div>

        <div class="plot-container">
          <!-- TODO: Add Plotly chart showing blended spectra -->
          <div class="plot-placeholder">
            <i class="pi pi-chart-line"></i>
            <p>Spectral plot will be displayed here</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import { useToast } from 'primevue/usetoast';
import Button from 'primevue/button';
import Column from 'primevue/column';
import DataTable from 'primevue/datatable';
import Dropdown from 'primevue/dropdown';
import InputNumber from 'primevue/inputnumber';
import Slider from 'primevue/slider';
import Tag from 'primevue/tag';

import { useNistStore } from '@/stores/nist';
import { useExperimentStore } from '@/stores/experiment';

const nistStore = useNistStore();
const experimentStore = useExperimentStore();
const toast = useToast();

const selectedNistSpectra = ref([]);
const selectedExperiments = ref([]);
const blendingMode = ref('additive');
const nistWeight = ref(50);
const noiseLevel = ref(0);
const blendResult = ref(null);

const blendingModes = [
  {
    label: 'Additive',
    value: 'additive',
    description: 'Add NIST spectra to experimental data (Beer\'s Law superposition)'
  },
  {
    label: 'Interpolative',
    value: 'interpolative',
    description: 'Weighted average between NIST and experimental spectra'
  },
  {
    label: 'Spiked',
    value: 'spiked',
    description: 'Add NIST peaks at specific concentrations to experimental baseline'
  },
];

const blendingModeDescription = computed(() => {
  const mode = blendingModes.find(m => m.value === blendingMode.value);
  return mode?.description || '';
});

const canBlend = computed(() => {
  return selectedNistSpectra.value.length > 0 && selectedExperiments.value.length > 0;
});

onMounted(() => {
  nistStore.fetchLibrary();
  experimentStore.fetchExperiments();
});

const previewBlend = () => {
  if (!canBlend.value) {
    return;
  }

  toast.add({
    severity: 'info',
    summary: 'Preview',
    detail: 'Generating blend preview...',
    life: 3000,
  });

  // TODO: Call backend API to generate blend preview
  blendResult.value = {
    spectra_count: selectedNistSpectra.value.length + selectedExperiments.value.length,
    wavenumber_range: '4000 - 400',
    nist_components: selectedNistSpectra.value.map(s => s.compound_name),
    experimental_components: selectedExperiments.value.map(e => e.name),
  };
};

const createBlend = async () => {
  if (!canBlend.value) {
    return;
  }

  try {
    // TODO: Implement blend creation API call
    toast.add({
      severity: 'success',
      summary: 'Blend Created',
      detail: 'Blended dataset created successfully. You can now use it in Analysis.',
      life: 4000,
    });

    // Reset selections
    selectedNistSpectra.value = [];
    selectedExperiments.value = [];
    blendResult.value = null;
  } catch {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to create blended dataset',
      life: 3000,
    });
  }
};
</script>

<style scoped>
.blend-tab {
  background: #f8fafc;
}

.blend-container {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section {
  background: #ffffff;
  border-radius: 8px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.instructions {
  background: #eff6ff;
  border-left: 4px solid #3b82f6;
}

.instructions h3 {
  margin: 0 0 12px 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: #1e40af;
  display: flex;
  align-items: center;
  gap: 8px;
}

.instructions .help-text {
  margin: 0;
  color: #1e40af;
  font-size: 0.9375rem;
}

.section-header {
  margin-bottom: 16px;
}

.section-header h4 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-header h4 i {
  color: #3b82f6;
}

.blend-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.spectra-table {
  margin-bottom: 12px;
}

.selection-summary {
  padding: 12px;
  background: #f8fafc;
  border-radius: 6px;
  text-align: center;
  font-size: 0.9375rem;
  color: #64748b;
}

.selection-summary strong {
  color: #1e293b;
}

.controls-section {
  background: #fefce8;
  border-left: 4px solid #eab308;
}

.controls-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 24px;
}

.control-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.control-group label {
  font-weight: 500;
  font-size: 0.875rem;
  color: #334155;
}

.slider-with-value {
  display: grid;
  grid-template-columns: 1fr 120px;
  gap: 12px;
  align-items: center;
}

.weight-input {
  width: 100%;
}

.help-text {
  font-size: 0.8125rem;
  color: #64748b;
  font-style: italic;
}

.actions-section {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 20px 24px;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.results-section {
  background: #f0fdf4;
  border-left: 4px solid #22c55e;
}

.result-info {
  margin-bottom: 20px;
}

.result-info p {
  margin: 0 0 8px 0;
  font-weight: 600;
  color: #166534;
}

.result-info ul {
  margin: 0;
  padding-left: 20px;
  color: #166534;
}

.result-info li {
  margin: 4px 0;
}

.plot-container {
  min-height: 300px;
  background: #ffffff;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.plot-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
  color: #94a3b8;
}

.plot-placeholder i {
  font-size: 3rem;
  margin-bottom: 12px;
  opacity: 0.5;
}

.plot-placeholder p {
  margin: 0;
  font-size: 0.9375rem;
}

@media (max-width: 1024px) {
  .blend-grid {
    grid-template-columns: 1fr;
  }

  .controls-grid {
    grid-template-columns: 1fr;
  }
}
</style>
