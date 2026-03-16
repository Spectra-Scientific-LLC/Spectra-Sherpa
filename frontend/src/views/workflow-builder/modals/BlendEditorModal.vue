<template>
  <Dialog
    v-model:visible="visible"
    header="Blend Configuration"
    :style="{ width: '90vw', maxWidth: '1400px' }"
    modal
    :draggable="false"
    class="blend-editor-modal"
  >
    <div class="blend-editor-container">
      <!-- Left Panel: Species Selection -->
      <div class="species-panel">
        <div class="panel-header">
          <h3>Species (Input Spectra)</h3>
          <small>Select upstream spectra to blend</small>
        </div>

        <div class="species-list">
          <div
            v-for="(species, index) in selectedSpecies"
            :key="index"
            class="species-item"
            :class="{ active: activeSpeciesIndex === index }"
            @click="activeSpeciesIndex = index"
          >
            <div class="species-header">
              <span class="species-color" :style="{ background: speciesColors[index] }" />
              <span class="species-name">{{ species.name }}</span>
            </div>
            <div class="species-actions">
              <Button
                icon="pi pi-times"
                class="p-button-text p-button-sm p-button-danger"
                @click.stop="removeSpecies(index)"
              />
            </div>
          </div>

          <Button
            label="Add Species"
            icon="pi pi-plus"
            class="p-button-outlined p-button-sm add-species-btn"
            @click="showSpeciesSelector = true"
          />
        </div>
      </div>

      <!-- Center Panel: Curve Designer -->
      <div class="curve-panel">
        <div class="panel-header">
          <h3>Concentration Curves</h3>
          <div class="curve-controls">
            <span class="time-info">{{ blendConfig.n_timepoints }} time points</span>
            <InputNumber
              v-model="blendConfig.n_timepoints"
              :min="10"
              :max="1000"
              :step="10"
              class="timepoints-input"
            />
          </div>
        </div>

        <div class="curve-editor">
          <!-- Curve Type Selector -->
          <div v-if="activeSpecies" class="curve-type-section">
            <label>Curve Type for {{ activeSpecies.name }}</label>
            <div class="curve-type-buttons">
              <Button
                v-for="curveType in curveTypes"
                :key="curveType.value"
                :label="curveType.label"
                :class="['p-button-sm', { 'p-button-outlined': activeSpecies.curveType !== curveType.value }]"
                @click="activeSpecies.curveType = curveType.value; updateCurvePreview()"
              />
            </div>
          </div>

          <!-- Curve Parameters -->
          <div v-if="activeSpecies" class="curve-params">
            <div class="param-group">
              <label>Max Concentration</label>
              <InputNumber
                v-model="activeSpecies.maxConcentration"
                :min="0"
                :max="100"
                :step="0.1"
                @update:model-value="updateCurvePreview"
              />
            </div>

            <template v-if="['sigmoid', 'gaussian'].includes(activeSpecies.curveType)">
              <div class="param-group">
                <label>Center (0-1)</label>
                <Slider
                  v-model="activeSpecies.center"
                  :min="0"
                  :max="1"
                  :step="0.01"
                  @change="updateCurvePreview"
                />
                <span class="param-value">{{ activeSpecies.center.toFixed(2) }}</span>
              </div>

              <div class="param-group">
                <label>Width</label>
                <Slider
                  v-model="activeSpecies.width"
                  :min="0.01"
                  :max="0.5"
                  :step="0.01"
                  @change="updateCurvePreview"
                />
                <span class="param-value">{{ activeSpecies.width.toFixed(2) }}</span>
              </div>
            </template>

            <template v-if="activeSpecies.curveType === 'step'">
              <div class="param-group">
                <label>Step Position (0-1)</label>
                <Slider
                  v-model="activeSpecies.center"
                  :min="0"
                  :max="1"
                  :step="0.01"
                  @change="updateCurvePreview"
                />
                <span class="param-value">{{ activeSpecies.center.toFixed(2) }}</span>
              </div>
            </template>
          </div>

          <!-- Curve Preview Chart -->
          <div class="curve-preview">
            <PlotlyChart
              v-if="curvePreviewData.length > 0"
              :data="curvePreviewData"
              :layout="curvePreviewLayout"
              :config="{ responsive: true, displayModeBar: false }"
            />
            <div v-else class="empty-preview">
              <p>Add species to see concentration curves</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Panel: Blend Settings -->
      <div class="settings-panel">
        <div class="panel-header">
          <h3>Blend Settings</h3>
        </div>

        <div class="settings-form">
          <div class="field">
            <label>Model Type</label>
            <Dropdown
              v-model="blendConfig.modelType"
              :options="modelTypes"
              optionLabel="label"
              optionValue="value"
            />
          </div>

          <div class="field">
            <label>Pathlength (m)</label>
            <InputNumber
              v-model="blendConfig.pathlength"
              :min="0.001"
              :max="1"
              :step="0.001"
              :minFractionDigits="3"
            />
          </div>

          <div class="field">
            <label>Noise Level</label>
            <Slider
              v-model="blendConfig.noiseLevel"
              :min="0"
              :max="0.1"
              :step="0.001"
            />
            <span class="param-value">{{ (blendConfig.noiseLevel * 100).toFixed(1) }}%</span>
          </div>

          <div class="field checkbox-field">
            <Checkbox v-model="blendConfig.applyBaseline" binary />
            <label>Add Baseline Drift</label>
          </div>

          <div v-if="blendConfig.applyBaseline" class="field">
            <label>Baseline Amplitude</label>
            <Slider
              v-model="blendConfig.baselineAmplitude"
              :min="0"
              :max="0.5"
              :step="0.01"
            />
            <span class="param-value">{{ blendConfig.baselineAmplitude.toFixed(2) }}</span>
          </div>
        </div>

        <div class="output-summary">
          <h4>Output Preview</h4>
          <div class="summary-item">
            <span>Species:</span>
            <strong>{{ selectedSpecies.length }}</strong>
          </div>
          <div class="summary-item">
            <span>Time Points:</span>
            <strong>{{ blendConfig.n_timepoints }}</strong>
          </div>
          <div class="summary-item">
            <span>Output Shape:</span>
            <strong>{{ blendConfig.n_timepoints }} x N wavenumbers</strong>
          </div>
        </div>
      </div>
    </div>

    <!-- Species Selector Dialog -->
    <Dialog
      v-model:visible="showSpeciesSelector"
      header="Select Input Species"
      :style="{ width: '500px' }"
      modal
    >
      <div class="species-selector">
        <p>Select upstream nodes to use as species:</p>
        <div class="upstream-nodes">
          <div
            v-for="node in upstreamNodes"
            :key="node.id"
            class="upstream-node"
            @click="addSpeciesFromNode(node)"
          >
            <span class="node-icon">{{ node.icon }}</span>
            <span class="node-name">{{ node.label }}</span>
          </div>
        </div>
      </div>
    </Dialog>

    <template #footer>
      <div class="modal-footer">
        <Button
          label="Cancel"
          class="p-button-text"
          @click="visible = false"
        />
        <Button
          label="Apply Configuration"
          icon="pi pi-check"
          class="p-button-success"
          :disabled="selectedSpecies.length === 0"
          @click="applyConfiguration"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- blend editor emits exploratory configuration payloads with partially typed previews. */
import { ref, computed, watch } from "vue";
import Dialog from "primevue/dialog";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import Slider from "primevue/slider";
import Checkbox from "primevue/checkbox";
import PlotlyChart from "@/components/PlotlyChart.vue";

interface Species {
  name: string;
  nodeId: number | null;
  curveType: string;
  maxConcentration: number;
  center: number;
  width: number;
}

interface BlendConfig {
  n_timepoints: number;
  modelType: string;
  pathlength: number;
  noiseLevel: number;
  applyBaseline: boolean;
  baselineAmplitude: number;
}

interface Props {
  modelValue: boolean;
  upstreamNodes?: { id: number; label: string; icon: string }[];
}

const props = withDefaults(defineProps<Props>(), {
  upstreamNodes: () => [],
});

const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void;
  (e: "configure", config: any): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

// Species management
const selectedSpecies = ref<Species[]>([]);
const activeSpeciesIndex = ref<number | null>(null);
const showSpeciesSelector = ref(false);

const speciesColors = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899"];

const activeSpecies = computed(() => {
  if (activeSpeciesIndex.value === null) return null;
  return selectedSpecies.value[activeSpeciesIndex.value] || null;
});

const curveTypes = [
  { label: "Sigmoid", value: "sigmoid" },
  { label: "Gaussian", value: "gaussian" },
  { label: "Linear", value: "linear" },
  { label: "Step", value: "step" },
  { label: "Constant", value: "constant" },
];

const modelTypes = [
  { label: "Linear (Beer-Lambert)", value: "linear" },
  { label: "Saturation", value: "saturation" },
];

// Blend configuration
const blendConfig = ref<BlendConfig>({
  n_timepoints: 100,
  modelType: "linear",
  pathlength: 0.01,
  noiseLevel: 0.01,
  applyBaseline: false,
  baselineAmplitude: 0.1,
});

// Add species from upstream node
function addSpeciesFromNode(node: { id: number; label: string }) {
  selectedSpecies.value.push({
    name: node.label,
    nodeId: node.id,
    curveType: "sigmoid",
    maxConcentration: 1.0,
    center: 0.5,
    width: 0.1,
  });
  activeSpeciesIndex.value = selectedSpecies.value.length - 1;
  showSpeciesSelector.value = false;
  updateCurvePreview();
}

function removeSpecies(index: number) {
  selectedSpecies.value.splice(index, 1);
  if (activeSpeciesIndex.value === index) {
    activeSpeciesIndex.value = selectedSpecies.value.length > 0 ? 0 : null;
  } else if (activeSpeciesIndex.value !== null && activeSpeciesIndex.value > index) {
    activeSpeciesIndex.value--;
  }
  updateCurvePreview();
}

// Curve preview
const curvePreviewData = ref<any[]>([]);
const curvePreviewLayout = {
  autosize: true,
  template: "plotly_dark",
  paper_bgcolor: "#0f172a",
  plot_bgcolor: "#0f172a",
  font: { color: "#f8fafc", size: 11 },
  margin: { t: 30, r: 20, b: 40, l: 50 },
  xaxis: { title: "Time", gridcolor: "#334155" },
  yaxis: { title: "Concentration", gridcolor: "#334155" },
  showlegend: true,
  legend: { bgcolor: "rgba(30, 41, 59, 0.8)" },
};

function generateCurve(species: Species, n: number): number[] {
  const t = Array.from({ length: n }, (_, i) => i / (n - 1));

  switch (species.curveType) {
    case "sigmoid":
      return t.map((x) => species.maxConcentration / (1 + Math.exp(-(x - species.center) / species.width)));
    case "gaussian":
      return t.map((x) => species.maxConcentration * Math.exp(-Math.pow(x - species.center, 2) / (2 * Math.pow(species.width, 2))));
    case "linear":
      return t.map((x) => species.maxConcentration * x);
    case "step":
      return t.map((x) => (x >= species.center ? species.maxConcentration : 0));
    case "constant":
      return t.map(() => species.maxConcentration);
    default:
      return t.map(() => species.maxConcentration);
  }
}

function updateCurvePreview() {
  const n = blendConfig.value.n_timepoints;
  const t = Array.from({ length: n }, (_, i) => i);

  curvePreviewData.value = selectedSpecies.value.map((species, index) => ({
    type: "scatter",
    mode: "lines",
    x: t,
    y: generateCurve(species, n),
    name: species.name,
    line: { color: speciesColors[index % speciesColors.length], width: 2 },
  }));
}

// Watch for changes
watch(() => blendConfig.value.n_timepoints, updateCurvePreview);

// Apply configuration
function applyConfiguration() {
  const config = {
    species: selectedSpecies.value.map((s) => ({
      nodeId: s.nodeId,
      name: s.name,
      curve: {
        type: s.curveType,
        maxConcentration: s.maxConcentration,
        center: s.center,
        width: s.width,
      },
    })),
    n_timepoints: blendConfig.value.n_timepoints,
    modelType: blendConfig.value.modelType,
    pathlength: blendConfig.value.pathlength,
    noiseLevel: blendConfig.value.noiseLevel,
    applyBaseline: blendConfig.value.applyBaseline,
    baselineAmplitude: blendConfig.value.baselineAmplitude,
  };

  emit("configure", config);
  visible.value = false;
}
</script>

<style scoped>
.blend-editor-modal :deep(.p-dialog-content) {
  padding: 0;
  background: #0f172a;
}

.blend-editor-container {
  display: grid;
  grid-template-columns: 250px 1fr 280px;
  min-height: 600px;
}

/* Species Panel */
.species-panel {
  background: #1e293b;
  border-right: 1px solid #334155;
  padding: 16px;
}

.panel-header {
  margin-bottom: 16px;
}

.panel-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: #f8fafc;
}

.panel-header small {
  color: #64748b;
  font-size: 0.8rem;
}

.species-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.species-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.species-item:hover {
  border-color: #475569;
}

.species-item.active {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.1);
}

.species-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.species-color {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.species-name {
  font-size: 0.9rem;
  color: #f8fafc;
}

.add-species-btn {
  width: 100%;
  margin-top: 8px;
}

/* Curve Panel */
.curve-panel {
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.curve-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.time-info {
  font-size: 0.8rem;
  color: #94a3b8;
}

.timepoints-input {
  width: 100px;
}

.curve-editor {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.curve-type-section {
  margin-bottom: 8px;
}

.curve-type-section label {
  display: block;
  font-size: 0.85rem;
  color: #94a3b8;
  margin-bottom: 8px;
}

.curve-type-buttons {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.curve-params {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.param-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.param-group label {
  font-size: 0.8rem;
  color: #94a3b8;
}

.param-value {
  font-size: 0.75rem;
  color: #64748b;
  font-family: monospace;
}

.curve-preview {
  flex: 1;
  min-height: 300px;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 8px;
  overflow: hidden;
}

.empty-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #64748b;
}

/* Settings Panel */
.settings-panel {
  background: #1e293b;
  border-left: 1px solid #334155;
  padding: 16px;
}

.settings-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-size: 0.85rem;
  color: #94a3b8;
}

.checkbox-field {
  flex-direction: row;
  align-items: center;
  gap: 10px;
}

.checkbox-field label {
  margin: 0;
}

.output-summary {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #334155;
}

.output-summary h4 {
  margin: 0 0 12px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #f8fafc;
}

.summary-item {
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
  padding: 4px 0;
}

.summary-item span {
  color: #94a3b8;
}

.summary-item strong {
  color: #f8fafc;
}

/* Species Selector */
.species-selector p {
  color: #94a3b8;
  margin-bottom: 16px;
}

.upstream-nodes {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.upstream-node {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.upstream-node:hover {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.1);
}

.node-icon {
  font-size: 1.2rem;
}

.node-name {
  color: #f8fafc;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* PrimeVue overrides */
:deep(.p-dropdown),
:deep(.p-inputnumber-input),
:deep(.p-inputtext) {
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
}

:deep(.p-slider) {
  background: #334155;
}

:deep(.p-slider .p-slider-range) {
  background: #3b82f6;
}

:deep(.p-slider .p-slider-handle) {
  background: #3b82f6;
  border-color: #3b82f6;
}

:deep(.p-dialog) {
  background: #1e293b;
  border: 1px solid #334155;
}

:deep(.p-dialog-header) {
  background: #1e293b;
  color: #f8fafc;
  border-bottom: 1px solid #334155;
}

:deep(.p-dialog-footer) {
  background: #1e293b;
  border-top: 1px solid #334155;
}

:deep(.p-checkbox .p-checkbox-box) {
  background: #0f172a;
  border-color: #475569;
}

:deep(.p-checkbox .p-checkbox-box.p-highlight) {
  background: #3b82f6;
  border-color: #3b82f6;
}
</style>
