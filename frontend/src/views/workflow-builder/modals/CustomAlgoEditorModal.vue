<script setup lang="ts">
/**
 * Custom Algo Editor Modal — wide expandable modal over the workflow canvas.
 *
 * Provides a Monaco code editor, mode toggle (simple/advanced), name/description
 * fields, Run Trial button, and result preview (diagnostics + plot).
 */
import { ref, computed, watch } from "vue";
import Dialog from "primevue/dialog";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import SelectButton from "primevue/selectbutton";
import MonacoEditor from "@/components/MonacoEditor.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { useCustomAlgoStore, type CustomAlgo, type UpdateCustomAlgo } from "@/stores/customAlgo";
import { useWorkflowStore, normalizeNodeType } from "@/stores/workflow";
import api from "@/api/client";

const props = defineProps<{
  projectId: number;
}>();

const visible = defineModel<boolean>({ default: false });
const customAlgoStore = useCustomAlgoStore();
const workflowStore = useWorkflowStore();

// Current algo being edited
const currentAlgo = ref<CustomAlgo | null>(null);

// Editable fields
const editName = ref("");
const editDescription = ref("");
const editCode = ref("");
const editMode = ref("simple");

// Mode options for SelectButton
const modeOptions = [
  { label: "Simple (numpy)", value: "simple" },
  { label: "Advanced (SherpaDataset)", value: "advanced" },
];

// Trial execution state
const isRunning = ref(false);
const trialResult = ref<Record<string, unknown> | null>(null);
const trialError = ref<string | null>(null);

// Saving state
const isSaving = ref(false);
const saveMessage = ref<string | null>(null);

// Dirty tracking
const isDirty = computed(() => {
  if (!currentAlgo.value) return false;
  return (
    editName.value !== currentAlgo.value.name ||
    editDescription.value !== (currentAlgo.value.description || "") ||
    editCode.value !== currentAlgo.value.code ||
    editMode.value !== currentAlgo.value.mode
  );
});

// Open the modal for editing an existing algo
function openForAlgo(algo: CustomAlgo) {
  currentAlgo.value = algo;
  editName.value = algo.name;
  editDescription.value = algo.description || "";
  editCode.value = algo.code;
  editMode.value = algo.mode;
  trialResult.value = null;
  trialError.value = null;
  saveMessage.value = null;
  visible.value = true;
}

// Open the modal for a new algo (after creation)
function openForNew(algo: CustomAlgo) {
  openForAlgo(algo);
}

// Save changes
async function save() {
  if (!currentAlgo.value) return;
  isSaving.value = true;
  saveMessage.value = null;

  const payload: UpdateCustomAlgo = {};
  if (editName.value !== currentAlgo.value.name) payload.name = editName.value;
  if (editDescription.value !== (currentAlgo.value.description || ""))
    payload.description = editDescription.value;
  if (editCode.value !== currentAlgo.value.code) payload.code = editCode.value;
  if (editMode.value !== currentAlgo.value.mode) payload.mode = editMode.value;

  const updated = await customAlgoStore.update(
    props.projectId,
    currentAlgo.value.id,
    payload
  );

  if (updated) {
    currentAlgo.value = updated;
    saveMessage.value = "Saved";
    setTimeout(() => (saveMessage.value = null), 2000);
  }

  isSaving.value = false;
}

// Run Trial — save first, then execute via trial endpoint
async function runTrial() {
  if (!currentAlgo.value) return;

  // Auto-save if dirty
  if (isDirty.value) {
    await save();
  }

  isRunning.value = true;
  trialResult.value = null;
  trialError.value = null;

  try {
    // Find first data source node in the current workflow for trial input
    const dataSourceNode = workflowStore.nodes.find(
      (n) => normalizeNodeType(n.type).startsWith("data.")
    );
    const dataSourceParams = dataSourceNode?.params ?? {};

    // Use the existing trial execution endpoint
    const { data } = await api.post("/workflows/trial/execute", {
      target_node_id: "custom_trial",
      trial_params: {},
      project_id: props.projectId,
      nodes: [
        {
          node_id: "data_source",
          node_type: "data.source",
          parameters: dataSourceParams,
        },
        {
          node_id: "custom_trial",
          node_type: currentAlgo.value.node_type,
          parameters: {},
        },
      ],
      edges: [
        {
          from_node_id: "data_source",
          to_node_id: "custom_trial",
          from_output: "default",
          to_input: "default",
        },
      ],
    });

    if (data.status === "completed" && data.result) {
      trialResult.value = data.result as Record<string, unknown>;
    } else if (data.error) {
      trialError.value = data.error;
    }
  } catch (e: unknown) {
    if (e && typeof e === "object" && "response" in e) {
      const resp = (e as { response?: { data?: { detail?: string } } }).response;
      trialError.value = resp?.data?.detail || "Trial execution failed";
    } else {
      trialError.value = String(e);
    }
  } finally {
    isRunning.value = false;
  }
}

// Diagnostics from trial result
const diagnostics = computed(() => {
  if (!trialResult.value) return null;
  const r = trialResult.value as Record<string, unknown>;
  const diag = r.diagnostics as Record<string, unknown> | undefined;
  return diag || null;
});

// Plot data from trial result
const plotData = computed(() => {
  if (!trialResult.value) return [];
  const r = trialResult.value as Record<string, { data?: number[][] }>;
  const output = r.default || r.outputs;
  if (!output || !output.data) return [];

  // Plot first few rows of the result
  const data = output.data;
  const traces = [];
  const maxTraces = Math.min(data.length, 10);
  for (let i = 0; i < maxTraces; i++) {
    traces.push({
      y: data[i],
      type: "scatter",
      mode: "lines",
      name: `Row ${i}`,
    });
  }
  return traces;
});

const plotLayout = computed(() => ({
  margin: { t: 20, r: 20, b: 40, l: 50 },
  height: 200,
  xaxis: { title: "Feature Index" },
  yaxis: { title: "Value" },
  showlegend: plotData.value.length <= 5,
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  font: { color: "#e2e8f0" },
}));

// Default code templates
const simpleTemplate = `# Simple mode: 'data' is a numpy 2D array, 'x' is the feature axis
# Assign your transformed data to 'result'

result = data  # pass-through — modify this!`;

const advancedTemplate = `# Advanced mode: 'input_ds' is a SherpaDataset object
# Assign your transformed dataset to 'result'

result = input_ds  # pass-through — modify this!`;

// Expose for parent component
defineExpose({ openForAlgo, openForNew });
</script>

<template>
  <Dialog
    v-model:visible="visible"
    :header="currentAlgo ? `Custom Algo: ${currentAlgo.name}` : 'Custom Algo'"
    :style="{ width: '85vw', maxWidth: '1400px' }"
    :contentStyle="{ height: '80vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }"
    modal
    :draggable="false"
    class="custom-algo-modal"
  >
    <!-- Header controls -->
    <div class="algo-header">
      <div class="algo-fields">
        <div class="field">
          <label>Name</label>
          <InputText v-model="editName" placeholder="Algorithm name" class="name-input" />
        </div>
        <div class="field">
          <label>Description</label>
          <InputText v-model="editDescription" placeholder="Brief description" class="desc-input" />
        </div>
        <div class="field">
          <label>Mode</label>
          <SelectButton v-model="editMode" :options="modeOptions" optionLabel="label" optionValue="value" />
        </div>
      </div>
      <div class="algo-actions">
        <span v-if="saveMessage" class="save-message">{{ saveMessage }}</span>
        <span v-if="isDirty" class="dirty-indicator">*</span>
        <Button
          label="Run Trial"
          icon="pi pi-play"
          :loading="isRunning"
          :disabled="!currentAlgo"
          class="p-button-success p-button-sm"
          @click="runTrial"
        />
        <Button
          label="Save"
          icon="pi pi-check"
          :loading="isSaving"
          :disabled="!isDirty"
          class="p-button-sm"
          @click="save"
        />
      </div>
    </div>

    <!-- Code editor -->
    <div class="editor-section">
      <MonacoEditor
        v-model="editCode"
        language="python"
        height="100%"
      />
    </div>

    <!-- Result preview -->
    <div class="result-section">
      <template v-if="trialError">
        <div class="error-panel">
          <h4>Error</h4>
          <pre class="error-trace">{{ trialError }}</pre>
        </div>
      </template>
      <template v-else-if="trialResult">
        <div class="result-grid">
          <div class="diagnostics-panel" v-if="diagnostics">
            <h4>Diagnostics</h4>
            <table class="diag-table">
              <tr v-for="(val, key) in diagnostics" :key="key">
                <td class="diag-key">{{ key }}</td>
                <td class="diag-val">{{ Array.isArray(val) ? (val as unknown[]).join(' x ') : val }}</td>
              </tr>
            </table>
          </div>
          <div class="plot-panel" v-if="plotData.length > 0">
            <PlotlyChart
              :data="plotData"
              :layout="plotLayout"
            />
          </div>
        </div>
      </template>
      <template v-else>
        <div class="empty-result">
          Click <strong>Run Trial</strong> to preview the output of your algorithm.
        </div>
      </template>
    </div>
  </Dialog>
</template>

<style scoped>
.algo-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--surface-border, #333);
  flex-shrink: 0;
}

.algo-fields {
  display: flex;
  gap: 16px;
  align-items: flex-end;
  flex-wrap: wrap;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field label {
  font-size: 0.75rem;
  color: var(--text-color-secondary, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.name-input {
  width: 200px;
}

.desc-input {
  width: 300px;
}

.algo-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.save-message {
  color: var(--green-400, #4ade80);
  font-size: 0.875rem;
}

.dirty-indicator {
  color: var(--yellow-400, #facc15);
  font-size: 1.25rem;
  font-weight: bold;
}

.editor-section {
  flex: 1;
  min-height: 200px;
  padding: 12px 0;
  overflow: hidden;
}

.result-section {
  flex-shrink: 0;
  max-height: 35%;
  overflow-y: auto;
  border-top: 1px solid var(--surface-border, #333);
  padding-top: 8px;
}

.error-panel {
  padding: 8px 12px;
  border-radius: 6px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid var(--red-500, #ef4444);
}

.error-panel h4 {
  margin: 0 0 4px;
  color: var(--red-400, #f87171);
}

.error-trace {
  font-family: monospace;
  font-size: 0.8rem;
  white-space: pre-wrap;
  color: var(--red-300, #fca5a5);
  margin: 0;
  max-height: 150px;
  overflow-y: auto;
}

.result-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 12px;
}

.diagnostics-panel h4,
.plot-panel h4 {
  margin: 0 0 6px;
  font-size: 0.85rem;
  color: var(--text-color-secondary, #94a3b8);
}

.diag-table {
  font-size: 0.8rem;
  border-collapse: collapse;
}

.diag-table td {
  padding: 2px 12px 2px 0;
}

.diag-key {
  color: var(--text-color-secondary, #94a3b8);
}

.diag-val {
  font-family: monospace;
  color: var(--text-color, #e2e8f0);
}

.empty-result {
  text-align: center;
  padding: 20px;
  color: var(--text-color-secondary, #94a3b8);
  font-size: 0.9rem;
}
</style>
