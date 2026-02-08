<template>
  <div class="doe-tab">
    <div v-if="!experimentId" class="empty-state">
      <i class="pi pi-info-circle" style="font-size: 3rem; color: #94a3b8"></i>
      <h3>No Experiment Selected</h3>
      <p>Select an experiment to configure Design of Experiments</p>
    </div>

    <div v-else class="doe-content">
      <!-- 1. Sample Database Section -->
      <div class="tab-section">
        <div class="section-header">
          <h3>Sample Database</h3>
          <Button
            label="Import CSV"
            icon="pi pi-upload"
            class="p-button-sm"
            @click="showSampleImport = true"
          />
        </div>

        <DataTable
          :value="samples"
          :paginator="true"
          :rows="10"
          stripedRows
          class="doe-table"
        >
          <Column field="sample_id" header="Sample ID" sortable />
          <Column field="name" header="Name" sortable />
          <Column field="type" header="Type" />
          <Column field="brand" header="Brand" />
          <Column field="cas_number" header="CAS Number" />
          <Column field="active" header="Active">
            <template #body="slotProps">
              <Tag
                :value="slotProps.data.active ? 'Active' : 'Inactive'"
                :severity="slotProps.data.active ? 'success' : 'danger'"
              />
            </template>
          </Column>
        </DataTable>
      </div>

      <!-- 2. Mixtures Section -->
      <div class="tab-section">
        <div class="section-header">
          <h3>Mixtures</h3>
          <Button
            label="Create Mixture"
            icon="pi pi-plus"
            class="p-button-sm"
            @click="showMixtureCreate = true"
            :disabled="samples.length === 0"
          />
        </div>

        <DataTable :value="mixtures" stripedRows class="doe-table">
          <Column field="mixture_id" header="Mixture ID" sortable />
          <Column field="name" header="Name" />
          <Column field="basis" header="Basis">
            <template #body="slotProps">
              <Tag :value="slotProps.data.basis" />
            </template>
          </Column>
          <Column field="components" header="Components">
            <template #body="slotProps">
              {{ slotProps.data.components?.length || 0 }} component(s)
            </template>
          </Column>
        </DataTable>
      </div>

      <!-- 3. Plate Map Section -->
      <div class="tab-section">
        <div class="section-header">
          <h3>96-Well Plate Map</h3>
          <div class="header-actions">
            <Dropdown
              v-model="selectedMixtureForPlate"
              :options="mixtures"
              optionLabel="mixture_id"
              optionValue="id"
              placeholder="Select mixture to assign"
              class="assignment-dropdown"
            />
            <Button
              label="Clear Plate"
              icon="pi pi-times"
              class="p-button-sm p-button-text p-button-danger"
              @click="clearPlateMap"
            />
          </div>
        </div>

        <PlateMap96Well
          :wells="plateWells"
          :selected-well="selectedWell"
          :show-legend="true"
          @well-click="onWellClick"
        />

        <div class="plate-stats">
          <div class="stat-card">
            <label>Assigned Wells:</label>
            <span>{{ assignedWellsCount }} / 96</span>
          </div>
          <div class="stat-card">
            <label>Empty Wells:</label>
            <span>{{ 96 - assignedWellsCount }}</span>
          </div>
        </div>
      </div>

      <!-- 4. Factors Section -->
      <div class="tab-section">
        <div class="section-header">
          <h3>Experimental Factors</h3>
          <Button
            label="Add Factor"
            icon="pi pi-plus"
            class="p-button-sm"
            @click="showFactorCreate = true"
          />
        </div>

        <div class="factors-grid">
          <div class="factor-group">
            <h4>Sample Factors</h4>
            <DataTable :value="sampleFactors" stripedRows class="doe-table">
              <Column field="name" header="Name" />
              <Column field="type" header="Type">
                <template #body="slotProps">
                  <Tag :value="slotProps.data.type" />
                </template>
              </Column>
              <Column field="levels" header="Levels">
                <template #body="slotProps">
                  {{ slotProps.data.levels?.length || 0 }}
                </template>
              </Column>
            </DataTable>
          </div>

          <div class="factor-group">
            <h4>Method Factors</h4>
            <DataTable :value="methodFactors" stripedRows class="doe-table">
              <Column field="name" header="Name" />
              <Column field="type" header="Type">
                <template #body="slotProps">
                  <Tag :value="slotProps.data.type" />
                </template>
              </Column>
              <Column field="levels" header="Levels">
                <template #body="slotProps">
                  {{ slotProps.data.levels?.length || 0 }}
                </template>
              </Column>
            </DataTable>
          </div>
        </div>
      </div>

      <!-- 5. Run Sequence Section -->
      <div class="tab-section">
        <div class="section-header">
          <h3>Run Sequence</h3>
          <Button
            label="Add Run Level"
            icon="pi pi-plus"
            class="p-button-sm"
            @click="showRunLevelCreate = true"
            :disabled="methodFactors.length === 0"
          />
        </div>

        <DataTable :value="runSequence" stripedRows class="doe-table">
          <Column field="sequence_order" header="#" sortable />
          <Column field="level_value" header="Level Value" />
          <Column field="path" header="Folder Path" />
          <Column field="batch" header="Batch" />
          <Column field="file_count" header="File Count" />
        </DataTable>
      </div>

      <!-- 6. Acquisition Matching Section -->
      <div class="tab-section">
        <div class="section-header">
          <h3>Acquisition Matching</h3>
          <Button
            label="Auto-Match Files"
            icon="pi pi-sync"
            class="p-button-sm"
            @click="showMatchDialog = true"
          />
        </div>

        <DataTable :value="matchedAcquisitions" :paginator="true" :rows="15" stripedRows class="doe-table" scrollable scrollHeight="600px">
          <Column field="seq" header="Seq" sortable frozen style="min-width: 80px" />
          <Column field="filename" header="Filename" frozen style="min-width: 200px" />
          <Column field="folder" header="Folder" style="min-width: 200px" />
          <Column field="batch" header="Batch" style="min-width: 80px" />
          <Column field="cell" header="Cell" style="min-width: 80px" />
          <Column field="sample_id" header="Sample ID" style="min-width: 150px" />
          <!-- Dynamic factor columns (method + sample) -->
          <Column v-for="factorName in factorColumnNames" :key="factorName" :field="`factor_values.${factorName}`" :header="factorName" style="min-width: 120px">
            <template #body="slotProps">
              {{ slotProps.data.factor_values?.[factorName] || '' }}
            </template>
          </Column>
        </DataTable>

        <div class="match-stats">
          <Tag
            :value="`${matchedAcquisitions.length} acquisitions matched`"
            severity="info"
          />
        </div>
      </div>

      <!-- 7. Export Section -->
      <div class="tab-section">
        <div class="section-header">
          <h3>Export DOE Design</h3>
        </div>

        <div class="export-options">
          <Button
            label="Export CSV"
            icon="pi pi-file"
            class="p-button-outlined"
            @click="exportDOE('csv')"
            :disabled="matchedAcquisitions.length === 0"
          />
          <Button
            label="Export JSON"
            icon="pi pi-file"
            class="p-button-outlined"
            @click="exportDOE('json')"
            :disabled="matchedAcquisitions.length === 0"
          />
          <Button
            label="Export XML"
            icon="pi pi-file"
            class="p-button-outlined"
            @click="exportDOE('xml')"
            :disabled="matchedAcquisitions.length === 0"
          />
        </div>

        <div class="doe-summary">
          <div class="summary-card">
            <i class="pi pi-database"></i>
            <div class="summary-content">
              <label>Samples</label>
              <span>{{ samples.length }}</span>
            </div>
          </div>
          <div class="summary-card">
            <i class="pi pi-flask"></i>
            <div class="summary-content">
              <label>Mixtures</label>
              <span>{{ mixtures.length }}</span>
            </div>
          </div>
          <div class="summary-card">
            <i class="pi pi-th-large"></i>
            <div class="summary-content">
              <label>Assigned Wells</label>
              <span>{{ assignedWellsCount }}</span>
            </div>
          </div>
          <div class="summary-card">
            <i class="pi pi-sliders-h"></i>
            <div class="summary-content">
              <label>Factors</label>
              <span>{{ factors.length }}</span>
            </div>
          </div>
          <div class="summary-card">
            <i class="pi pi-list"></i>
            <div class="summary-content">
              <label>Run Levels</label>
              <span>{{ runSequence.length }}</span>
            </div>
          </div>
          <div class="summary-card">
            <i class="pi pi-check-square"></i>
            <div class="summary-content">
              <label>Matched</label>
              <span>{{ matchedAcquisitions.length }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Sample Import Dialog -->
    <Dialog
      v-model:visible="showSampleImport"
      header="Import Samples from CSV"
      :modal="true"
      style="width: 600px"
    >
      <div class="import-dialog">
        <p class="dialog-help">
          Upload a CSV file with columns: sample_id, name, type, brand, cas_number, active, notes
        </p>
        <Textarea
          v-model="sampleImportCsv"
          rows="10"
          placeholder="Paste CSV data here&#10;sample_id,name,type,brand,cas_number,active&#10;S001,Methanol,Solvent,Sigma,67-56-1,true"
          style="width: 100%"
        />
        <div class="dialog-actions">
          <Button label="Cancel" class="p-button-text" @click="showSampleImport = false" />
          <Button label="Import" icon="pi pi-upload" @click="importSamples" :loading="importing" />
        </div>
      </div>
    </Dialog>

    <!-- Mixture Create Dialog -->
    <Dialog
      v-model:visible="showMixtureCreate"
      header="Create Mixture"
      :modal="true"
      style="width: 700px"
    >
      <div class="mixture-dialog">
        <div class="field">
          <label>Mixture ID *</label>
          <InputText v-model="newMixture.mixture_id" placeholder="e.g., MIX001" />
        </div>

        <div class="field">
          <label>Name</label>
          <InputText v-model="newMixture.name" placeholder="Optional mixture name" />
        </div>

        <div class="field">
          <label>Basis</label>
          <Dropdown
            v-model="newMixture.basis"
            :options="[{ label: 'Volume', value: 'volume' }, { label: 'Mass', value: 'mass' }]"
            optionLabel="label"
            optionValue="value"
          />
        </div>

        <div class="field">
          <label>Components</label>
          <div v-for="(comp, idx) in newMixture.components" :key="idx" class="component-row">
            <Dropdown
              v-model="comp.sample_id"
              :options="samples"
              optionLabel="name"
              optionValue="id"
              placeholder="Select sample"
              class="sample-select"
            />
            <InputNumber v-model="comp.amount" placeholder="Amount" mode="decimal" :minFractionDigits="2" />
            <InputText v-model="comp.unit" placeholder="Unit (mL, g, etc.)" />
            <Button
              icon="pi pi-times"
              class="p-button-text p-button-danger p-button-sm"
              @click="newMixture.components.splice(idx, 1)"
            />
          </div>
          <Button
            label="Add Component"
            icon="pi pi-plus"
            class="p-button-text p-button-sm"
            @click="newMixture.components.push({ sample_id: null, amount: 0, unit: 'mL' })"
          />
        </div>

        <div class="dialog-actions">
          <Button label="Cancel" class="p-button-text" @click="showMixtureCreate = false" />
          <Button
            label="Create"
            icon="pi pi-check"
            @click="createMixture"
            :loading="creating"
            :disabled="!newMixture.mixture_id || newMixture.components.length === 0"
          />
        </div>
      </div>
    </Dialog>

    <!-- Factor Create Dialog -->
    <Dialog
      v-model:visible="showFactorCreate"
      header="Add Experimental Factor"
      :modal="true"
      style="width: 600px"
    >
      <div class="factor-dialog">
        <div class="field">
          <label>Factor Name *</label>
          <InputText v-model="newFactor.name" placeholder="e.g., Temperature, Pressure" />
        </div>

        <div class="field">
          <label>Scope *</label>
          <Dropdown
            v-model="newFactor.scope"
            :options="[{ label: 'Sample', value: 'sample' }, { label: 'Method', value: 'method' }]"
            optionLabel="label"
            optionValue="value"
          />
        </div>

        <div class="field">
          <label>Type *</label>
          <Dropdown
            v-model="newFactor.type"
            :options="[{ label: 'Categorical', value: 'categorical' }, { label: 'Numeric', value: 'numeric' }]"
            optionLabel="label"
            optionValue="value"
          />
        </div>

        <div class="field">
          <label>Unit</label>
          <InputText v-model="newFactor.unit" placeholder="e.g., °C, atm (optional)" />
        </div>

        <div class="field">
          <label>Levels (comma-separated)</label>
          <InputText v-model="factorLevelsInput" placeholder="e.g., 25, 50, 75, 100" />
        </div>

        <div class="dialog-actions">
          <Button label="Cancel" class="p-button-text" @click="showFactorCreate = false" />
          <Button
            label="Add"
            icon="pi pi-check"
            @click="createFactor"
            :loading="creating"
            :disabled="!newFactor.name || !newFactor.scope || !newFactor.type"
          />
        </div>
      </div>
    </Dialog>

    <!-- Run Level Create Dialog -->
    <Dialog
      v-model:visible="showRunLevelCreate"
      header="Add Run Level"
      :modal="true"
      style="width: 600px"
    >
      <div class="run-level-dialog">
        <div class="field">
          <label>Factor *</label>
          <Dropdown
            v-model="newRunLevel.factor_definition_id"
            :options="methodFactors"
            optionLabel="name"
            optionValue="id"
            placeholder="Select factor"
          />
        </div>

        <div class="field">
          <label>Level Value *</label>
          <InputText v-model="newRunLevel.level_value" placeholder="e.g., 25" />
        </div>

        <div class="field">
          <label>Folder Path</label>
          <InputText v-model="newRunLevel.path" placeholder="Optional folder path" />
        </div>

        <div class="field">
          <label>Batch Number</label>
          <InputNumber v-model="newRunLevel.batch" placeholder="Optional batch number" />
        </div>

        <div class="field">
          <label>File Count</label>
          <InputNumber v-model="newRunLevel.file_count" placeholder="Optional file count" />
        </div>

        <div class="field">
          <label>Sequence Order</label>
          <InputNumber v-model="newRunLevel.sequence_order" placeholder="Order in sequence" />
        </div>

        <div class="dialog-actions">
          <Button label="Cancel" class="p-button-text" @click="showRunLevelCreate = false" />
          <Button
            label="Add"
            icon="pi pi-check"
            @click="createRunLevel"
            :loading="creating"
            :disabled="!newRunLevel.factor_definition_id || !newRunLevel.level_value"
          />
        </div>
      </div>
    </Dialog>

    <!-- Match Files Dialog -->
    <Dialog
      v-model:visible="showMatchDialog"
      header="Auto-Match Acquisition Files"
      :modal="true"
      style="width: 900px; max-height: 90vh"
    >
      <div class="match-dialog">
        <div class="config-selector-section">
          <div class="field">
            <label>Configuration Profile (optional)</label>
            <Dropdown
              v-model="selectedConfigId"
              :options="configProfiles"
              optionLabel="name"
              optionValue="id"
              placeholder="Select a saved profile or configure manually"
              @change="applyConfigProfile"
              showClear
            />
            <small class="muted-text">
              Load saved settings from Settings → DOE Configurations
            </small>
          </div>
        </div>

        <TabView>
          <TabPanel header="Simple File List">
            <p class="dialog-help">
              Paste filenames (one per line). System extracts folder from paths automatically.
            </p>

            <Textarea
              v-model="fileListInput"
              rows="15"
              placeholder="Paste filenames or paths:&#10;08-29-2025_@05-19-55/Spectrum_0001.csv&#10;08-29-2025_@05-19-55/Spectrum_0002.csv&#10;08-29-2025_@05-39-11/Spectrum_0003.csv"
              style="width: 100%"
            />
          </TabPanel>

          <TabPanel header="Folder-Based">
            <p class="dialog-help">
              Select folders from your computer. Files and timestamps will be automatically extracted.
            </p>

            <div class="folder-picker-section">
              <Button
                label="Select Folders"
                icon="pi pi-folder-open"
                class="p-button-outlined"
                @click="triggerFolderPicker"
              />
              <input
                ref="folderInput"
                type="file"
                webkitdirectory
                directory
                multiple
                style="display: none"
                @change="handleFolderSelection"
              />
              <small class="muted-text">
                Select one or more folders containing spectral data files. Batch numbers will be assigned automatically.
              </small>
            </div>

            <div v-for="(folder, idx) in matchFolders" :key="idx" class="folder-entry">
              <div class="folder-header">
                <div class="folder-info">
                  <i class="pi pi-folder"></i>
                  <span class="folder-name">{{ folder.folder_path }}</span>
                  <Tag :value="`${folder.file_list.length} files`" severity="info" />
                </div>
                <InputNumber
                  v-model="folder.batch_number"
                  placeholder="Batch #"
                  style="width: 100px"
                />
                <Button
                  icon="pi pi-times"
                  class="p-button-text p-button-danger p-button-sm"
                  @click="matchFolders.splice(idx, 1)"
                />
              </div>

              <div v-if="folder.file_list.length > 0" class="file-preview">
                <small class="muted-text">
                  Files: {{ folder.file_list.slice(0, 5).join(', ') }}{{ folder.file_list.length > 5 ? ` ... and ${folder.file_list.length - 5} more` : '' }}
                </small>
              </div>
            </div>

            <div v-if="matchFolders.length === 0" class="empty-folders">
              <i class="pi pi-info-circle"></i>
              <p>No folders selected. Click "Select Folders" to choose directories.</p>
            </div>
          </TabPanel>
        </TabView>

        <div class="match-options">
          <h4>Scan Path Options</h4>

          <div class="field">
            <label>First Cell</label>
            <InputText v-model="matchOptions.first_cell" placeholder="e.g., A1" />
            <small class="muted-text">Starting position for scan path derivation</small>
          </div>

          <div class="field">
            <label>Scan Orientation</label>
            <Dropdown
              v-model="matchOptions.scan_orientation"
              :options="[
                { label: 'Row-wise (A1→A2→...→H12)', value: 'row' },
                { label: 'Column-wise (A1→B1→...→H12)', value: 'column' },
                { label: 'Row-wise serpentine (A1→A12, B12→B1, ...)', value: 'serpentine' },
                { label: 'Column-wise serpentine (A1→H1, H2→A2, ...)', value: 'serpentine_column' }
              ]"
              optionLabel="label"
              optionValue="value"
              placeholder="Select orientation"
            />
          </div>

          <div class="field">
            <label>Sequence Offset</label>
            <InputNumber v-model="matchOptions.seq_offset" placeholder="0" />
            <small class="muted-text">Add this to extracted sequence numbers</small>
          </div>

          <div class="checkbox-field">
            <InputSwitch v-model="matchOptions.use_plate_map" />
            <label>Use Plate Map to derive cell/sample</label>
          </div>

          <div class="checkbox-field">
            <InputSwitch v-model="matchOptions.use_run_sequence" />
            <label>Map folders to run sequence for factor values</label>
          </div>
        </div>

        <div class="dialog-actions">
          <Button label="Cancel" class="p-button-text" @click="showMatchDialog = false" />
          <Button
            label="Match Files"
            icon="pi pi-sync"
            @click="matchFiles"
            :loading="matching"
            :disabled="!fileListInput && matchFolders.length === 0"
          />
        </div>
      </div>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from "vue";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputSwitch from "primevue/inputswitch";
import InputText from "primevue/inputtext";
import Tag from "primevue/tag";
import TabView from "primevue/tabview";
import TabPanel from "primevue/tabpanel";
import Textarea from "primevue/textarea";
import { useToast } from "primevue/usetoast";
import PlateMap96Well from "@/components/PlateMap96Well.vue";
import api from "@/api/client";

const props = defineProps<{
  experimentId: number | null;
}>();

const toast = useToast();

// Data
const samples = ref<any[]>([]);
const mixtures = ref<any[]>([]);
const factors = ref<any[]>([]);
const plateWells = ref<any[]>([]);
const runSequence = ref<any[]>([]);
const matchedAcquisitions = ref<any[]>([]);

// Dialogs
const showSampleImport = ref(false);
const showMixtureCreate = ref(false);
const showFactorCreate = ref(false);
const showRunLevelCreate = ref(false);
const showMatchDialog = ref(false);

// Loading states
const importing = ref(false);
const creating = ref(false);
const matching = ref(false);

// Sample Import
const sampleImportCsv = ref("");

// Mixture Create
const newMixture = ref({
  mixture_id: "",
  name: "",
  basis: "volume" as "volume" | "mass",
  components: [] as any[],
});

// Factor Create
const newFactor = ref({
  name: "",
  scope: "sample" as "sample" | "method",
  type: "categorical" as "categorical" | "numeric",
  unit: "",
  levels: [] as string[],
});
const factorLevelsInput = ref("");

// Run Level Create
const newRunLevel = ref({
  factor_definition_id: null as number | null,
  level_value: "",
  path: "",
  batch: null as number | null,
  file_count: null as number | null,
  sequence_order: 0,
});

// Plate Map
const selectedWell = ref<string | null>(null);
const selectedMixtureForPlate = ref<number | null>(null);

// File Matching
const fileListInput = ref("");
const folderInput = ref<HTMLInputElement | null>(null);
const matchFolders = ref<Array<{
  folder_path: string;
  batch_number: number;
  file_list: string[];
  file_list_text?: string;
}>>([]);
const matchOptions = ref({
  first_cell: "",
  scan_orientation: "",
  seq_offset: 0,
  use_plate_map: true,
  use_run_sequence: true,
});

// DOE Configuration Profiles
const configProfiles = ref<any[]>([]);
const selectedConfigId = ref<number | null>(null);

// Computed
const sampleFactors = computed(() => factors.value.filter((f) => f.scope === "sample"));
const methodFactors = computed(() => factors.value.filter((f) => f.scope === "method"));
const assignedWellsCount = computed(() => plateWells.value.filter((w) => w.mixture_id).length);

// Extract unique factor column names from matched acquisitions
const factorColumnNames = computed(() => {
  const names = new Set<string>();
  for (const acq of matchedAcquisitions.value) {
    if (acq.factor_values) {
      Object.keys(acq.factor_values).forEach(name => names.add(name));
    }
  }
  return Array.from(names).sort();
});

// Methods
const fetchAll = async () => {
  if (!props.experimentId) return;

  try {
    const [
      samplesRes,
      mixturesRes,
      factorsRes,
      plateRes,
      runRes,
      matchedRes,
    ] = await Promise.all([
      api.get(`/experiments/${props.experimentId}/doe/samples`),
      api.get(`/experiments/${props.experimentId}/doe/mixtures`),
      api.get(`/experiments/${props.experimentId}/doe/factors`),
      api.get(`/experiments/${props.experimentId}/doe/plate-map`),
      api.get(`/experiments/${props.experimentId}/doe/run-sequence`),
      api.get(`/experiments/${props.experimentId}/doe/matched-acquisitions`),
    ]);

    samples.value = samplesRes.data;
    mixtures.value = mixturesRes.data;
    factors.value = factorsRes.data;
    plateWells.value = plateRes.data;
    runSequence.value = runRes.data;
    matchedAcquisitions.value = matchedRes.data;
  } catch (error: any) {
    console.error("Failed to fetch DOE data:", error);
  }
};

const importSamples = async () => {
  if (!props.experimentId || !sampleImportCsv.value) return;

  importing.value = true;
  try {
    const response = await api.post(
      `/experiments/${props.experimentId}/doe/samples/import`,
      { csv_data: sampleImportCsv.value }
    );
    samples.value = response.data;
    showSampleImport.value = false;
    sampleImportCsv.value = "";
    toast.add({
      severity: "success",
      summary: "Imported",
      detail: `Imported ${response.data.length} samples`,
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Import Failed",
      detail: error.response?.data?.detail || "Failed to import samples",
      life: 3000,
    });
  } finally {
    importing.value = false;
  }
};

const createMixture = async () => {
  if (!props.experimentId) return;

  creating.value = true;
  try {
    const response = await api.post(
      `/experiments/${props.experimentId}/doe/mixtures`,
      newMixture.value
    );
    mixtures.value.push(response.data);
    showMixtureCreate.value = false;
    newMixture.value = {
      mixture_id: "",
      name: "",
      basis: "volume",
      components: [],
    };
    toast.add({
      severity: "success",
      summary: "Created",
      detail: "Mixture created successfully",
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Creation Failed",
      detail: error.response?.data?.detail || "Failed to create mixture",
      life: 3000,
    });
  } finally {
    creating.value = false;
  }
};

const createFactor = async () => {
  if (!props.experimentId) return;

  creating.value = true;
  try {
    const levels = factorLevelsInput.value
      .split(",")
      .map((l) => l.trim())
      .filter((l) => l);
    const payload = { ...newFactor.value, levels };

    const response = await api.post(
      `/experiments/${props.experimentId}/doe/factors`,
      payload
    );
    factors.value.push(response.data);
    showFactorCreate.value = false;
    newFactor.value = {
      name: "",
      scope: "sample",
      type: "categorical",
      unit: "",
      levels: [],
    };
    factorLevelsInput.value = "";
    toast.add({
      severity: "success",
      summary: "Created",
      detail: "Factor created successfully",
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Creation Failed",
      detail: error.response?.data?.detail || "Failed to create factor",
      life: 3000,
    });
  } finally {
    creating.value = false;
  }
};

const createRunLevel = async () => {
  if (!props.experimentId) return;

  creating.value = true;
  try {
    const payload = {
      levels: [newRunLevel.value],
    };

    const response = await api.post(
      `/experiments/${props.experimentId}/doe/run-sequence`,
      payload
    );
    runSequence.value = response.data;
    showRunLevelCreate.value = false;
    newRunLevel.value = {
      factor_definition_id: null,
      level_value: "",
      path: "",
      batch: null,
      file_count: null,
      sequence_order: runSequence.value.length,
    };
    toast.add({
      severity: "success",
      summary: "Created",
      detail: "Run level added successfully",
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Creation Failed",
      detail: error.response?.data?.detail || "Failed to create run level",
      life: 3000,
    });
  } finally {
    creating.value = false;
  }
};

const onWellClick = async (wellPosition: string) => {
  if (!props.experimentId) return;

  selectedWell.value = wellPosition;

  if (selectedMixtureForPlate.value) {
    // Assign mixture to well
    try {
      const existingWell = plateWells.value.find((w) => w.well_position === wellPosition);
      if (existingWell) {
        // Update existing well
        plateWells.value = plateWells.value.map((w) =>
          w.well_position === wellPosition
            ? { ...w, mixture_id: selectedMixtureForPlate.value }
            : w
        );
      } else {
        // Add new well
        plateWells.value.push({
          well_position: wellPosition,
          mixture_id: selectedMixtureForPlate.value,
        });
      }

      // Save to backend
      await api.post(`/experiments/${props.experimentId}/doe/plate-map`, {
        wells: plateWells.value,
      });

      toast.add({
        severity: "success",
        summary: "Assigned",
        detail: `Mixture assigned to ${wellPosition}`,
        life: 2000,
      });
    } catch (error: any) {
      toast.add({
        severity: "error",
        summary: "Assignment Failed",
        detail: error.response?.data?.detail || "Failed to assign mixture",
        life: 3000,
      });
    }
  }
};

const clearPlateMap = async () => {
  if (!props.experimentId) return;

  try {
    await api.post(`/experiments/${props.experimentId}/doe/plate-map`, {
      wells: [],
    });
    plateWells.value = [];
    toast.add({
      severity: "success",
      summary: "Cleared",
      detail: "Plate map cleared",
      life: 2000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Clear Failed",
      detail: error.response?.data?.detail || "Failed to clear plate map",
      life: 3000,
    });
  }
};

// Folder Picker Methods
const triggerFolderPicker = () => {
  folderInput.value?.click();
};

const handleFolderSelection = async (event: Event) => {
  const input = event.target as HTMLInputElement;
  if (!input.files || input.files.length === 0) return;

  const files = Array.from(input.files);
  const folderMap = new Map<string, { files: string[]; batch: number }>();

  // Group files by folder
  for (const file of files) {
    const pathParts = file.webkitRelativePath.split('/');
    if (pathParts.length < 2) continue; // Skip root files

    const folderName = pathParts[0]; // First part is the selected folder name

    // Filter: Only include CSV files with "Spectrum" in the name
    if (!file.name.toLowerCase().endsWith('.csv')) continue;
    if (!file.name.includes('Spectrum')) continue;

    if (!folderMap.has(folderName)) {
      folderMap.set(folderName, {
        files: [],
        batch: matchFolders.value.length + folderMap.size + 1,
      });
    }

    // Add filename (not full path) to the folder
    folderMap.get(folderName)!.files.push(file.name);
  }

  // Convert map to matchFolders array and count total filtered files
  let totalSpectrumFiles = 0;
  for (const [folderPath, data] of folderMap) {
    matchFolders.value.push({
      folder_path: folderPath,
      batch_number: data.batch,
      file_list: data.files.sort(), // Sort filenames
    });
    totalSpectrumFiles += data.files.length;
  }

  // Auto-populate run sequence if methodFactors exist
  if (methodFactors.value.length > 0 && matchFolders.value.length > 0) {
    autoPopulateRunSequence();
  }

  toast.add({
    severity: "success",
    summary: "Folders Loaded",
    detail: `Loaded ${folderMap.size} folder(s) with ${totalSpectrumFiles} Spectrum files`,
    life: 3000,
  });

  // Reset input to allow selecting same folder again
  input.value = '';
};

const autoPopulateRunSequence = async () => {
  if (!props.experimentId || methodFactors.value.length === 0) return;

  // Use the first method factor for auto-population
  const primaryFactor = methodFactors.value[0];

  // Create run levels from folders
  const levels = matchFolders.value.map((folder, idx) => ({
    factor_definition_id: primaryFactor.id,
    path: folder.folder_path,
    batch: folder.batch_number,
    file_count: folder.file_list.length,
    level_value: folder.batch_number.toString(), // Default: use batch number as level value
    sequence_order: idx,
  }));

  try {
    const response = await api.post(
      `/experiments/${props.experimentId}/doe/run-sequence`,
      { levels }
    );
    runSequence.value = response.data;

    toast.add({
      severity: "info",
      summary: "Run Sequence Auto-Created",
      detail: `Created ${levels.length} run levels from selected folders`,
      life: 3000,
    });
  } catch (error: any) {
    console.warn("Failed to auto-populate run sequence:", error);
    // Don't show error - this is auto-population, user can manually create
  }
};

const matchFiles = async () => {
  if (!props.experimentId) return;
  if (!fileListInput.value && matchFolders.value.length === 0) return;

  matching.value = true;
  try {
    let payload: any = {
      first_cell: matchOptions.value.first_cell || null,
      scan_orientation: matchOptions.value.scan_orientation || null,
      seq_offset: matchOptions.value.seq_offset || 0,
      use_plate_map: matchOptions.value.use_plate_map,
      use_run_sequence: matchOptions.value.use_run_sequence,
    };

    // Folder-based or simple file list
    if (matchFolders.value.length > 0) {
      // Folder-based matching
      payload.folders = matchFolders.value.map(f => ({
        folder_path: f.folder_path,
        batch_number: f.batch_number,
        file_list: f.file_list, // Already an array from folder picker
      }));
      payload.file_list = null;
    } else {
      // Simple file list
      payload.file_list = fileListInput.value
        .split("\n")
        .map((f) => f.trim())
        .filter((f) => f);
      payload.folders = null;
    }

    const response = await api.post(
      `/experiments/${props.experimentId}/doe/match-acquisitions`,
      payload
    );

    matchedAcquisitions.value = response.data;
    showMatchDialog.value = false;
    fileListInput.value = "";
    matchFolders.value = [];
    toast.add({
      severity: "success",
      summary: "Matched",
      detail: `Matched ${response.data.length} acquisitions`,
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Match Failed",
      detail: error.response?.data?.detail || "Failed to match files",
      life: 3000,
    });
  } finally {
    matching.value = false;
  }
};

const exportDOE = async (format: "csv" | "json" | "xml") => {
  if (!props.experimentId) return;

  try {
    const response = await api.get(
      `/experiments/${props.experimentId}/doe/export/${format}`,
      { responseType: "blob" }
    );

    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `doe_export.${format}`);
    document.body.appendChild(link);
    link.click();
    link.remove();

    toast.add({
      severity: "success",
      summary: "Exported",
      detail: `DOE design exported as ${format.toUpperCase()}`,
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Export Failed",
      detail: error.response?.data?.detail || "Failed to export",
      life: 3000,
    });
  }
};

// DOE Config Profile Management
const fetchConfigProfiles = async () => {
  try {
    const response = await api.get("/doe-configs");
    configProfiles.value = response.data.configs;

    // Auto-select default config if exists
    const defaultConfig = configProfiles.value.find((c: any) => c.is_default);
    if (defaultConfig) {
      selectedConfigId.value = defaultConfig.id;
      applyConfigProfile();
    }
  } catch (error) {
    // Silently fail - config profiles are optional
    console.warn("Failed to load DOE config profiles:", error);
  }
};

const applyConfigProfile = () => {
  if (!selectedConfigId.value) return;

  const config = configProfiles.value.find((c: any) => c.id === selectedConfigId.value);
  if (!config) return;

  // Apply scan defaults
  if (config.scan_defaults) {
    matchOptions.value.first_cell = config.scan_defaults.first_cell || "";
    matchOptions.value.scan_orientation = config.scan_defaults.orientation || "";
    matchOptions.value.seq_offset = config.scan_defaults.seq_offset || 0;
  }

  // Apply matching behavior
  if (config.match_settings) {
    matchOptions.value.use_plate_map = config.match_settings.use_plate_map ?? true;
    matchOptions.value.use_run_sequence = config.match_settings.use_run_sequence ?? true;
  }

  toast.add({
    severity: "success",
    summary: "Config Loaded",
    detail: `Applied settings from "${config.name}"`,
    life: 2000,
  });
};

// Watchers
watch(
  () => props.experimentId,
  (newId) => {
    if (newId) {
      fetchAll();
    }
  },
  { immediate: true }
);

onMounted(() => {
  if (props.experimentId) {
    fetchAll();
  }
  fetchConfigProfiles();
});
</script>

<style scoped>
.doe-tab {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  color: #64748b;
}

.empty-state h3 {
  margin: 16px 0 8px;
  font-size: 1.2rem;
  color: #475569;
}

.doe-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tab-section {
  background: #ffffff;
  border-radius: 8px;
  padding: 20px;
  border: 1px solid #e2e8f0;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 2px solid #e2e8f0;
}

.section-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.assignment-dropdown {
  width: 250px;
}

.doe-table {
  margin-top: 12px;
}

.factors-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.factor-group h4 {
  margin: 0 0 12px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #475569;
}

.plate-stats {
  display: flex;
  gap: 16px;
  margin-top: 16px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.stat-card label {
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 500;
}

.stat-card span {
  font-size: 1.2rem;
  color: #1e293b;
  font-weight: 600;
}

.match-stats {
  margin-top: 12px;
}

.export-options {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.doe-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-top: 20px;
}

.summary-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.summary-card i {
  font-size: 1.5rem;
  color: #3b82f6;
}

.summary-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.summary-content label {
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 500;
}

.summary-content span {
  font-size: 1.5rem;
  color: #1e293b;
  font-weight: 600;
}

.import-dialog,
.mixture-dialog,
.factor-dialog,
.run-level-dialog,
.match-dialog {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.config-selector-section {
  padding: 12px 16px;
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  margin-bottom: 8px;
}

.config-selector-section .muted-text {
  margin-top: 4px;
  font-size: 0.85rem;
}

.dialog-help {
  color: #64748b;
  font-size: 0.9rem;
  margin-bottom: 8px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-weight: 500;
  font-size: 0.9rem;
  color: #334155;
}

.component-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr auto;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.sample-select {
  min-width: 0;
}

.match-options {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #e2e8f0;
}

.match-options h4 {
  margin: 0 0 12px 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: #334155;
}

.folder-entry {
  margin-bottom: 16px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.folder-header {
  display: flex;
  gap: 8px;
  align-items: center;
}

.checkbox-field {
  display: flex;
  align-items: center;
  gap: 10px;
}

.checkbox-field label {
  margin: 0;
}

.folder-picker-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.folder-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.folder-info i {
  color: #3b82f6;
  font-size: 1.1rem;
}

.folder-name {
  font-weight: 500;
  color: #334155;
  flex: 1;
}

.file-preview {
  margin-top: 8px;
  padding: 8px 12px;
  background: #ffffff;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
}

.empty-folders {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 20px;
  text-align: center;
  color: #94a3b8;
  background: #f8fafc;
  border-radius: 6px;
  border: 2px dashed #e2e8f0;
}

.empty-folders i {
  font-size: 2rem;
  color: #cbd5e1;
}

.empty-folders p {
  margin: 0;
  color: #64748b;
  font-size: 0.9rem;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e2e8f0;
}

@media (max-width: 1200px) {
  .factors-grid {
    grid-template-columns: 1fr;
  }

  .component-row {
    grid-template-columns: 1fr;
  }

  .match-options {
    grid-template-columns: 1fr;
  }
}
</style>
