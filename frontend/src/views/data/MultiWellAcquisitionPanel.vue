<template>
  <section class="multi-well" aria-labelledby="multi-well-title">
    <header class="plan-header">
      <div>
        <div class="title-row">
          <h3 id="multi-well-title">Multi-well experiment</h3>
          <Tag value="Acquisition plan" severity="info" />
        </div>
        <span>{{ planStatus }}</span>
      </div>
      <div class="actions">
        <Button
          icon="pi pi-refresh"
          class="p-button-text p-button-sm"
          aria-label="Reload acquisition plan"
          :loading="loading"
          :disabled="experimentId == null"
          @click="loadPlan"
        />
        <Button
          v-if="canAuthor"
          label="Save acquisition plan"
          icon="pi pi-check"
          class="p-button-sm"
          :loading="saving"
          :disabled="experimentId == null || loading || !dirty"
          @click="savePlan"
        />
      </div>
    </header>

    <div class="plan-controls">
      <div class="field">
        <label for="acquisition-dataset">Dataset</label>
        <Dropdown
          id="acquisition-dataset"
          :model-value="experimentId"
          :options="experimentOptions"
          option-label="name"
          option-value="id"
          placeholder="Select a dataset"
          @update:model-value="selectExperiment"
        />
      </div>
      <div class="field">
        <label for="acquisition-format">Default plate format</label>
        <Dropdown
          id="acquisition-format"
          :model-value="plateFormat.id"
          :options="formatOptions"
          option-label="label"
          option-value="value"
          disabled
        />
      </div>
      <dl class="plan-facts">
        <div>
          <dt>Planned wells</dt>
          <dd>{{ draft.wells.length }}/{{ plateFormat.capacity }}</dd>
        </div>
        <div>
          <dt>Measured rows changed</dt>
          <dd>{{ measuredDifferenceCount }}</dd>
        </div>
      </dl>
      <small v-if="!canAuthor">This acquisition plan is read-only in the current profile.</small>
    </div>

    <div v-if="experimentId == null" class="empty-plan">
      <i class="pi pi-database" /><strong>Select a dataset</strong>
    </div>
    <div v-else-if="loadError" class="plan-error" role="alert">
      <i class="pi pi-exclamation-triangle" /><span>{{ loadError }}</span>
      <Button
        label="Retry"
        icon="pi pi-refresh"
        class="p-button-sm p-button-outlined"
        @click="loadPlan"
      />
    </div>
    <ProgressSpinner v-else-if="loading" class="plan-spinner" />
    <div v-else class="plan-sections" :aria-busy="saving">
      <section class="plan-section" aria-labelledby="planned-samples-title">
        <div class="section-heading">
          <div>
            <span class="step">1</span>
            <h4 id="planned-samples-title">Samples</h4>
          </div>
          <Button
            v-if="canAuthor"
            label="Add sample"
            icon="pi pi-plus"
            class="p-button-sm p-button-outlined"
            @click="addSample"
          />
        </div>
        <p>
          Define the materials expected before acquisition. Measured samples remain an immutable
          dataset version.
        </p>
        <div v-if="draft.samples.length" class="editor-grid sample-grid">
          <template v-for="sample in draft.samples" :key="sample.sample_id">
            <InputText v-model="sample.sample_id" aria-label="Sample ID" placeholder="Sample ID" />
            <InputText v-model="sample.name" aria-label="Sample name" placeholder="Name" />
            <InputText v-model="sample.sample_type" aria-label="Sample type" placeholder="Type" />
            <Button
              v-if="canAuthor"
              icon="pi pi-trash"
              class="p-button-text p-button-danger"
              aria-label="Remove sample"
              @click="removeSample(sample)"
            />
          </template>
        </div>
        <small v-else>No planned samples yet.</small>
      </section>

      <section class="plan-section" aria-labelledby="mixtures-title">
        <div class="section-heading">
          <div>
            <span class="step">2</span>
            <h4 id="mixtures-title">Mixtures</h4>
          </div>
          <Button
            v-if="canAuthor"
            label="Add mixture"
            icon="pi pi-plus"
            class="p-button-sm p-button-outlined"
            @click="addMixture"
          />
        </div>
        <div v-for="mixture in draft.mixtures" :key="mixture.mixture_id" class="definition-card">
          <div class="definition-row">
            <InputText
              v-model="mixture.mixture_id"
              aria-label="Mixture ID"
              placeholder="Mixture ID"
            />
            <InputText v-model="mixture.name" aria-label="Mixture name" placeholder="Name" />
            <Dropdown
              v-model="mixture.basis"
              :options="['volume', 'mass']"
              aria-label="Mixture basis"
            />
            <Button
              v-if="canAuthor"
              icon="pi pi-trash"
              class="p-button-text p-button-danger"
              aria-label="Remove mixture"
              @click="removeMixture(mixture)"
            />
          </div>
          <div v-for="(component, index) in mixture.components" :key="index" class="component-row">
            <Dropdown
              v-model="component.sample_id"
              :options="sampleOptions"
              option-label="label"
              option-value="value"
              placeholder="Sample"
            />
            <InputNumber v-model="component.amount" :min="0" placeholder="Amount" />
            <InputText v-model="component.unit" aria-label="Component unit" placeholder="Unit" />
            <Button
              v-if="canAuthor"
              icon="pi pi-times"
              class="p-button-text p-button-danger"
              aria-label="Remove component"
              @click="mixture.components.splice(index, 1)"
            />
          </div>
          <Button
            v-if="canAuthor && draft.samples.length"
            label="Add component"
            icon="pi pi-plus"
            class="p-button-sm p-button-text"
            @click="addComponent(mixture)"
          />
        </div>
        <small v-if="!draft.mixtures.length">No mixture definitions yet.</small>
      </section>

      <section class="plan-section" aria-labelledby="factors-title">
        <div class="section-heading">
          <div>
            <span class="step">3</span>
            <h4 id="factors-title">Factors</h4>
          </div>
          <Button
            v-if="canAuthor"
            label="Add factor"
            icon="pi pi-plus"
            class="p-button-sm p-button-outlined"
            @click="addFactor"
          />
        </div>
        <div
          v-for="factor in draft.factors"
          :key="factor.factor_id"
          class="definition-row factor-row"
        >
          <InputText v-model="factor.factor_id" aria-label="Factor ID" placeholder="Factor ID" />
          <InputText v-model="factor.name" aria-label="Factor name" placeholder="Name" />
          <Dropdown
            v-model="factor.scope"
            :options="['sample', 'method']"
            aria-label="Factor scope"
          />
          <Dropdown
            v-model="factor.factor_type"
            :options="['categorical', 'numeric']"
            aria-label="Factor type"
          />
          <InputText
            :model-value="levelsText(factor)"
            aria-label="Factor levels"
            placeholder="Levels, comma separated"
            @update:model-value="setLevels(factor, $event)"
          />
          <Button
            v-if="canAuthor"
            icon="pi pi-trash"
            class="p-button-text p-button-danger"
            aria-label="Remove factor"
            @click="removeFactor(factor)"
          />
        </div>
        <small v-if="!draft.factors.length">No experimental factors yet.</small>
      </section>

      <section class="plan-section plate-section" aria-labelledby="plate-layout-title">
        <div class="section-heading">
          <div>
            <span class="step">4</span>
            <h4 id="plate-layout-title">Plate layout</h4>
          </div>
          <div v-if="canAuthor" class="actions">
            <Button
              label="Fill 96 wells"
              icon="pi pi-th-large"
              class="p-button-sm p-button-outlined"
              @click="fillPlate"
            />
            <Button
              label="Clear"
              icon="pi pi-times"
              class="p-button-sm p-button-text"
              :disabled="!draft.wells.length"
              @click="clearPlate"
            />
          </div>
        </div>
        <p>Click a well to include or exclude it, then assign a planned sample or mixture.</p>
        <PlateMap96Well
          :wells="displayWells"
          :selected-well="selectedWell"
          :interactive="canAuthor"
          show-legend
          @well-click="toggleWell"
        />
        <div v-if="selectedWellRecord" class="well-assignment">
          <strong>{{ selectedWellRecord.well_position }}</strong>
          <Dropdown
            v-model="selectedAssignment"
            :options="assignmentOptions"
            option-label="label"
            option-value="value"
            placeholder="Unassigned"
            show-clear
          />
          <InputText
            v-model="selectedWellRecord.planned_sample_label"
            aria-label="Planned sample label"
            placeholder="Display label"
          />
        </div>
      </section>

      <section class="plan-section" aria-labelledby="order-title">
        <div class="section-heading">
          <div>
            <span class="step">5</span>
            <h4 id="order-title">Acquisition order</h4>
          </div>
          <Button
            v-if="canAuthor && draft.factors.length"
            label="Add run level"
            icon="pi pi-plus"
            class="p-button-sm p-button-outlined"
            @click="addOrderStep"
          />
        </div>
        <div
          v-for="(stepItem, index) in draft.acquisition_order"
          :key="`${stepItem.sequence_order}-${stepItem.factor_id}`"
          class="definition-row order-row"
        >
          <InputNumber v-model="stepItem.sequence_order" :min="0" aria-label="Sequence order" />
          <Dropdown
            v-model="stepItem.factor_id"
            :options="factorOptions"
            option-label="label"
            option-value="value"
            placeholder="Factor"
          />
          <InputText v-model="stepItem.level_value" aria-label="Run level" placeholder="Level" />
          <InputText v-model="stepItem.path" aria-label="Run path" placeholder="Folder or path" />
          <InputNumber v-model="stepItem.batch" aria-label="Run batch" placeholder="Batch" />
          <Button
            v-if="canAuthor"
            icon="pi pi-trash"
            class="p-button-text p-button-danger"
            aria-label="Remove run level"
            @click="draft.acquisition_order.splice(index, 1)"
          />
        </div>
        <small v-if="!draft.acquisition_order.length">No method run levels yet.</small>
      </section>

      <section class="plan-section" aria-labelledby="matching-title">
        <div class="section-heading">
          <div>
            <span class="step">6</span>
            <h4 id="matching-title">Acquisition matching</h4>
          </div>
          <Dropdown
            v-if="presets.length"
            :options="presets"
            option-label="name"
            placeholder="Apply retained preset"
            @update:model-value="applyPreset"
          />
        </div>
        <div class="matching-rules">
          <div class="field">
            <label for="filename-pattern">Filename pattern</label
            ><InputText
              id="filename-pattern"
              :model-value="ruleText('filename_pattern')"
              placeholder="e.g. _(?&lt;seq&gt;\\d+)"
              @update:model-value="setRule('filename_pattern', $event)"
            />
          </div>
          <div class="field">
            <label for="first-well">First well</label
            ><InputText
              id="first-well"
              :model-value="ruleText('first_well')"
              placeholder="A01"
              @update:model-value="setRule('first_well', $event)"
            />
          </div>
          <div class="field">
            <label for="scan-direction">Scan direction</label
            ><Dropdown
              id="scan-direction"
              :model-value="ruleText('direction') || 'rows'"
              :options="['rows', 'columns', 'serpentine']"
              @update:model-value="setRule('direction', $event)"
            />
          </div>
        </div>
        <div class="match-summary">
          <Tag :value="`${draft.matching.matches.length} retained matches`" severity="info" />
          <span
            >Saved matches take precedence; unmatched measured rows use planned plate order.</span
          >
        </div>
      </section>

      <section class="plan-section review-section" aria-labelledby="review-title">
        <div class="section-heading">
          <div>
            <span class="step">7</span>
            <h4 id="review-title">Review</h4>
          </div>
        </div>
        <div class="review-grid">
          <div>
            <strong>{{ draft.samples.length }}</strong
            ><span>samples</span>
          </div>
          <div>
            <strong>{{ draft.mixtures.length }}</strong
            ><span>mixtures</span>
          </div>
          <div>
            <strong>{{ draft.factors.length }}</strong
            ><span>factors</span>
          </div>
          <div>
            <strong>{{ draft.wells.length }}</strong
            ><span>wells</span>
          </div>
          <div>
            <strong>{{ draft.acquisition_order.length }}</strong
            ><span>run levels</span>
          </div>
        </div>
        <div class="sync-status" role="status">
          <Tag :value="syncLabel" :severity="syncSeverity" />
          <span>{{ syncDetail }}</span>
        </div>
        <div v-if="saveError" class="plan-error inline" role="alert">
          <i class="pi pi-exclamation-triangle" /><span>{{ saveError }}</span>
          <Button
            label="Retry save"
            icon="pi pi-refresh"
            class="p-button-sm p-button-outlined"
            :loading="saving"
            @click="savePlan"
          />
        </div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import ProgressSpinner from "primevue/progressspinner";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";
import api from "@/api/client";
import PlateMap96Well from "@/components/PlateMap96Well.vue";
import { useAppConfig } from "@/composables/useAppConfig";
import {
  defaultPlateFormatId,
  formatWell,
  getPlateFormat,
  plateFormats,
} from "@/utils/plateFormats";
import { proposeMeasuredSamples, type SampleTableRow } from "@/utils/sampleTable";
import { getErrorMessage } from "@/utils/errors";
import type {
  AcquisitionOrderStep,
  AcquisitionPlan,
  MeasuredSampleTableEditor,
  PlannedFactor,
  PlannedMixture,
  PlannedSample,
} from "@/types";

interface ExperimentOption {
  id: number;
  name: string;
}
interface AcquisitionPreset {
  preset_key: string;
  name: string;
  description: string | null;
  is_default: boolean;
  settings: Record<string, unknown>;
}

const props = defineProps<{
  experimentId: number | null;
  experimentName?: string | null;
  experimentOptions: ExperimentOption[];
  sourceFileId?: number | null;
  syncRefreshRevision?: number;
}>();
const emit = defineEmits<{
  selectExperiment: [experimentId: number];
  saved: [plan: AcquisitionPlan];
}>();
const toast = useToast();
const { isCapabilityDisabled } = useAppConfig();
const preferredFormatId = ref(defaultPlateFormatId);
const plateFormat = computed(() => getPlateFormat(preferredFormatId.value));
const formatOptions = plateFormats.map((format) => ({ label: format.label, value: format.id }));
const loading = ref(false);
const saving = ref(false);
const loadError = ref<string | null>(null);
const saveError = ref<string | null>(null);
const revision = ref("");
const baseline = ref("");
const selectedWell = ref<string | null>(null);
const measuredRows = ref<SampleTableRow[]>([]);
const measuredLoading = ref(false);
const measuredAvailable = ref(false);
const presets = ref<AcquisitionPreset[]>([]);
let requestToken = 0;

const blankDraft = () => ({
  samples: [] as PlannedSample[],
  mixtures: [] as PlannedMixture[],
  factors: [] as PlannedFactor[],
  wells: [] as AcquisitionPlan["wells"],
  acquisition_order: [] as AcquisitionOrderStep[],
  matching: {
    rules: {} as Record<string, unknown>,
    matches: [] as AcquisitionPlan["matching"]["matches"],
  },
});
const draft = ref(blankDraft());
const canAuthor = computed(() => !isCapabilityDisabled("sample_table_authoring"));
const serializedDraft = computed(() => JSON.stringify(draft.value));
const dirty = computed(() => baseline.value !== serializedDraft.value);
const sampleOptions = computed(() =>
  draft.value.samples.map((item) => ({
    label: `${item.sample_id}${item.name ? ` — ${item.name}` : ""}`,
    value: item.sample_id,
  })),
);
const factorOptions = computed(() =>
  draft.value.factors.map((item) => ({ label: item.name, value: item.factor_id })),
);
const assignmentOptions = computed(() => [
  ...draft.value.samples.map((item) => ({
    label: `Sample: ${item.sample_id}`,
    value: `sample:${item.sample_id}`,
  })),
  ...draft.value.mixtures.map((item) => ({
    label: `Mixture: ${item.mixture_id}`,
    value: `mixture:${item.mixture_id}`,
  })),
]);
const selectedWellRecord = computed(
  () => draft.value.wells.find((well) => well.well_position === selectedWell.value) ?? null,
);
const selectedAssignment = computed({
  get: () =>
    selectedWellRecord.value?.sample_id
      ? `sample:${selectedWellRecord.value.sample_id}`
      : selectedWellRecord.value?.mixture_id
        ? `mixture:${selectedWellRecord.value.mixture_id}`
        : null,
  set: (value: string | null) => {
    if (!selectedWellRecord.value) return;
    selectedWellRecord.value.sample_id = value?.startsWith("sample:") ? value.slice(7) : null;
    selectedWellRecord.value.mixture_id = value?.startsWith("mixture:") ? value.slice(8) : null;
  },
});
const displayWells = computed(() =>
  draft.value.wells.map((well) => ({
    well_position: well.well_position,
    assigned: true,
    label: well.planned_sample_label || well.sample_id || well.mixture_id || "Planned",
    tooltip: `${well.well_position}: ${well.planned_sample_label || well.sample_id || well.mixture_id || "included"}`,
  })),
);

const planForProposal = computed<AcquisitionPlan>(() => ({
  schema_version: "spectrasherpa-acquisition-plan/3",
  experiment_id: props.experimentId ?? 0,
  plate_format_id: "plate-96",
  plate_format_label: plateFormat.value.label,
  capacity: plateFormat.value.capacity,
  revision: revision.value,
  ...draft.value,
}));
const measuredProposal = computed(() =>
  proposeMeasuredSamples(measuredRows.value, planForProposal.value),
);
const measuredDifferenceCount = computed(() => measuredProposal.value.differences.length);
const syncLabel = computed(() =>
  measuredLoading.value
    ? "Checking measured samples"
    : !props.sourceFileId
      ? "No measured source selected"
      : !measuredAvailable.value
        ? "No published measured-sample version"
        : measuredDifferenceCount.value
          ? "Publication needed"
          : "Plan and measured samples synchronized",
);
const syncSeverity = computed(() =>
  measuredDifferenceCount.value || (props.sourceFileId && !measuredAvailable.value)
    ? "warning"
    : props.sourceFileId
      ? "success"
      : "secondary",
);
const syncDetail = computed(() =>
  !props.sourceFileId
    ? "Select a source file in My Dataset to preview synchronization."
    : !measuredAvailable.value
      ? "Open Measured samples in My Dataset to review and publish the first immutable version."
      : measuredDifferenceCount.value
        ? `${measuredDifferenceCount.value} proposed field changes are waiting for review in My Dataset.`
        : `${measuredProposal.value.status.matched}/${measuredProposal.value.status.planned} planned wells match the published measured-sample version.`,
);
const planStatus = computed(() =>
  !props.experimentId
    ? "No dataset selected"
    : loading.value
      ? `Loading ${props.experimentName || "dataset"}`
      : dirty.value
        ? "Unsaved changes"
        : `${draft.value.wells.length} wells saved with ${props.experimentName || "dataset"}`,
);

function clonePlan(data: AcquisitionPlan) {
  return JSON.parse(
    JSON.stringify({
      samples: data.samples,
      mixtures: data.mixtures,
      factors: data.factors,
      wells: data.wells,
      acquisition_order: data.acquisition_order,
      matching: data.matching,
    }),
  ) as ReturnType<typeof blankDraft>;
}
function allWells(): string[] {
  return plateFormat.value.rows.flatMap((_, row) =>
    Array.from({ length: plateFormat.value.columns }, (_, column) =>
      formatWell(plateFormat.value, row, column),
    ),
  );
}
function nextId(prefix: string, existing: string[]): string {
  let index = existing.length + 1;
  while (existing.includes(`${prefix}-${index}`)) index += 1;
  return `${prefix}-${index}`;
}
function addSample(): void {
  const sample_id = nextId(
    "sample",
    draft.value.samples.map((item) => item.sample_id),
  );
  draft.value.samples.push({ sample_id, source_specimen_uid: null, name: "", sample_type: null, notes: null });
}
function removeSample(sample: PlannedSample): void {
  draft.value.samples = draft.value.samples.filter((item) => item !== sample);
  for (const mixture of draft.value.mixtures)
    mixture.components = mixture.components.filter((item) => item.sample_id !== sample.sample_id);
}
function addMixture(): void {
  const mixture_id = nextId(
    "mixture",
    draft.value.mixtures.map((item) => item.mixture_id),
  );
  draft.value.mixtures.push({
    mixture_id,
    name: null,
    basis: "volume",
    notes: null,
    components: [],
  });
}
function removeMixture(mixture: PlannedMixture): void {
  draft.value.mixtures = draft.value.mixtures.filter((item) => item !== mixture);
}
function addComponent(mixture: PlannedMixture): void {
  if (draft.value.samples[0])
    mixture.components.push({
      sample_id: draft.value.samples[0].sample_id,
      amount: 1,
      unit: mixture.basis === "mass" ? "g" : "mL",
    });
}
function addFactor(): void {
  const factor_id = nextId(
    "factor",
    draft.value.factors.map((item) => item.factor_id),
  );
  draft.value.factors.push({
    factor_id,
    name: `Factor ${draft.value.factors.length + 1}`,
    scope: "method",
    factor_type: "categorical",
    unit: null,
    levels: [],
  });
}
function removeFactor(factor: PlannedFactor): void {
  draft.value.factors = draft.value.factors.filter((item) => item !== factor);
  draft.value.acquisition_order = draft.value.acquisition_order.filter(
    (item) => item.factor_id !== factor.factor_id,
  );
}
function levelsText(factor: PlannedFactor): string {
  return factor.levels.map(String).join(", ");
}
function setLevels(factor: PlannedFactor, value: string | undefined): void {
  factor.levels = String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
function addOrderStep(): void {
  const factor = draft.value.factors[0];
  if (!factor) return;
  draft.value.acquisition_order.push({
    sequence_order: draft.value.acquisition_order.length,
    factor_id: factor.factor_id,
    level_value: String(factor.levels[0] ?? ""),
    path: null,
    batch: null,
    file_count: null,
  });
}
function ruleText(key: string): string {
  const value = draft.value.matching.rules[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}
function setRule(key: string, value: string | undefined): void {
  draft.value.matching.rules[key] = value ?? "";
}
function applyPreset(preset: AcquisitionPreset | null): void {
  if (preset) draft.value.matching.rules = { ...draft.value.matching.rules, ...preset.settings };
}
function toggleWell(well: string): void {
  if (!canAuthor.value) return;
  const index = draft.value.wells.findIndex((item) => item.well_position === well);
  if (index >= 0) draft.value.wells.splice(index, 1);
  else
    draft.value.wells.push({
      well_position: well,
      planned_sample_label: null,
      sample_id: null,
      mixture_id: null,
      factor_values: {},
    });
  selectedWell.value = well;
}
function fillPlate(): void {
  const existing = new Map(draft.value.wells.map((item) => [item.well_position, item]));
  draft.value.wells = allWells().map(
    (well_position) =>
      existing.get(well_position) ?? {
        well_position,
        planned_sample_label: null,
        sample_id: null,
        mixture_id: null,
        factor_values: {},
      },
  );
}
function clearPlate(): void {
  draft.value.wells = [];
  selectedWell.value = null;
}
function selectExperiment(id: number | null): void {
  if (typeof id === "number") emit("selectExperiment", id);
}

async function loadMeasuredRows(): Promise<void> {
  measuredRows.value = [];
  measuredAvailable.value = false;
  if (!props.sourceFileId) return;
  measuredLoading.value = true;
  try {
    const { data } = await api.get<MeasuredSampleTableEditor>(
      `/builder/analysis-binding/${props.sourceFileId}`,
    );
    measuredRows.value = data.rows.map((row) => ({
      ...row,
      targets: { ...row.targets },
      annotations: { ...row.annotations },
    }));
    measuredAvailable.value = true;
  } catch {
    measuredRows.value = [];
  } finally {
    measuredLoading.value = false;
  }
}
async function loadPlan(): Promise<void> {
  const experimentId = props.experimentId;
  const token = ++requestToken;
  draft.value = blankDraft();
  baseline.value = JSON.stringify(draft.value);
  revision.value = "";
  selectedWell.value = null;
  loadError.value = null;
  saveError.value = null;
  if (experimentId == null) return;
  loading.value = true;
  try {
    const [{ data }, presetResponse, preferenceResponse] = await Promise.all([
      api.get<AcquisitionPlan>(`/experiments/${experimentId}/acquisition-plan`),
      api
        .get<AcquisitionPreset[]>("/acquisition-preferences/presets")
        .catch(() => ({ data: [] as AcquisitionPreset[] })),
      api
        .get<{ default_plate_format_id: string }>("/acquisition-preferences")
        .catch(() => ({ data: { default_plate_format_id: defaultPlateFormatId } })),
    ]);
    if (token === requestToken) {
      preferredFormatId.value = preferenceResponse.data.default_plate_format_id;
      preferredFormatId.value = data.plate_format_id || preferredFormatId.value;
      draft.value = clonePlan(data);
      revision.value = data.revision;
      baseline.value = JSON.stringify(draft.value);
      presets.value = presetResponse.data;
      await loadMeasuredRows();
    }
  } catch (cause) {
    if (token === requestToken) loadError.value = getErrorMessage(cause);
  } finally {
    if (token === requestToken) loading.value = false;
  }
}
async function savePlan(): Promise<void> {
  if (props.experimentId == null || !canAuthor.value) return;
  saving.value = true;
  saveError.value = null;
  try {
    const { data } = await api.put<AcquisitionPlan>(
      `/experiments/${props.experimentId}/acquisition-plan`,
      { plate_format_id: plateFormat.value.id, expected_revision: revision.value, ...draft.value },
    );
    draft.value = clonePlan(data);
    revision.value = data.revision;
    baseline.value = JSON.stringify(draft.value);
    emit("saved", data);
    toast.add({
      severity: "success",
      summary: "Acquisition plan saved",
      detail: `${data.wells.length} planned wells and complete scientific intent`,
      life: 3000,
    });
  } catch (cause) {
    saveError.value = getErrorMessage(cause);
  } finally {
    saving.value = false;
  }
}

watch(() => props.experimentId, loadPlan, { immediate: true });
watch(() => props.sourceFileId, loadMeasuredRows);
watch(() => props.syncRefreshRevision, loadMeasuredRows);
</script>

<style scoped>
.multi-well,
.plan-sections {
  display: grid;
  gap: 1rem;
  min-width: 0;
}
.plan-header,
.plan-controls,
.actions,
.title-row,
.section-heading,
.section-heading > div,
.definition-row,
.component-row,
.well-assignment,
.match-summary,
.sync-status {
  align-items: center;
  display: flex;
  gap: 0.65rem;
}
.plan-header,
.section-heading {
  justify-content: space-between;
}
.plan-header {
  border-bottom: 1px solid var(--surface-border);
  padding-bottom: 0.85rem;
}
.plan-header h3,
.plan-section h4 {
  margin: 0;
}
.plan-controls {
  align-items: end;
  flex-wrap: wrap;
}
.field {
  display: grid;
  gap: 0.35rem;
}
.plan-facts {
  display: flex;
  gap: 1.5rem;
  margin: 0;
}
.plan-facts div {
  display: grid;
}
.plan-facts dt,
.plan-section p,
.plan-section small {
  color: var(--text-color-secondary);
  font-size: 0.8rem;
}
.plan-facts dd {
  font-weight: 600;
  margin: 0;
}
.empty-plan,
.plan-error {
  align-items: center;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  display: flex;
  gap: 0.65rem;
  padding: 1rem;
}
.plan-error {
  border-color: #f59e0b;
  color: #92400e;
}
.plan-spinner {
  justify-self: center;
}
.plan-section {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  display: grid;
  gap: 0.75rem;
  padding: 1rem;
}
.step {
  align-items: center;
  background: var(--primary-color);
  border-radius: 50%;
  color: var(--primary-color-text);
  display: inline-flex;
  font-size: 0.75rem;
  font-weight: 700;
  height: 1.65rem;
  justify-content: center;
  width: 1.65rem;
}
.editor-grid {
  display: grid;
  gap: 0.5rem;
}
.sample-grid {
  grid-template-columns: minmax(8rem, 1fr) minmax(10rem, 2fr) minmax(8rem, 1fr) auto;
}
.definition-card {
  border: 1px solid var(--surface-border);
  border-radius: 7px;
  display: grid;
  gap: 0.5rem;
  padding: 0.75rem;
}
.definition-row,
.component-row {
  flex-wrap: wrap;
}
.definition-row > * {
  flex: 1 1 8rem;
}
.definition-row > .p-button,
.component-row > .p-button {
  flex: 0 0 auto;
}
.component-row {
  padding-left: 1rem;
}
.component-row > * {
  flex: 0 1 12rem;
}
.factor-row > *:nth-child(2),
.order-row > *:nth-child(4) {
  flex: 2 1 12rem;
}
.plate-section :deep(.plate-map) {
  max-width: 100%;
}
.well-assignment {
  border-top: 1px solid var(--surface-border);
  padding-top: 0.75rem;
}
.well-assignment > * {
  flex: 1;
}
.well-assignment strong {
  flex: 0 0 4rem;
}
.matching-rules {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.review-grid {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: repeat(5, minmax(0, 1fr));
}
.review-grid div {
  background: var(--surface-ground);
  border-radius: 7px;
  display: grid;
  padding: 0.75rem;
  text-align: center;
}
.review-grid strong {
  font-size: 1.25rem;
}
.review-grid span {
  color: var(--text-color-secondary);
  font-size: 0.75rem;
}
.sync-status {
  border-top: 1px solid var(--surface-border);
  padding-top: 0.75rem;
}
.inline {
  margin-top: 0.5rem;
}
@media (max-width: 800px) {
  .sample-grid,
  .matching-rules,
  .review-grid {
    grid-template-columns: 1fr;
  }
  .plan-header,
  .section-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
