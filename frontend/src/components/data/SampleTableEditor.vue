<template>
  <Button
    label="Edit measured samples"
    icon="pi pi-table"
    class="p-button-outlined p-button-sm"
    :disabled="sampleCount < 1"
    @click="openEditor"
  />

  <Dialog
    v-model:visible="visible"
    modal
    maximizable
    header="Measured samples"
    class="sample-table-dialog"
    :style="{ width: 'min(98vw, 1600px)' }"
  >
    <div class="editor-intro">
      <div>
        <strong>{{ sampleCount.toLocaleString() }} source samples</strong>
        <p>Review responses, groups, exclusions, and physical well positions.</p>
      </div>
      <div class="intro-tags">
        <Tag :value="`${includedSampleCount.toLocaleString()} included`" severity="success" />
        <Tag
          :value="`${selectedTargetValueCount.toLocaleString()}/${includedSampleCount.toLocaleString()} ${selectedTarget || 'target'} values`"
          :severity="selectedTargetValueCount === includedSampleCount ? 'success' : 'warning'"
        />
        <Tag value="Portable CSV" severity="info" />
      </div>
    </div>

    <div v-if="editorLoading" class="editor-state" role="status">
      <i class="pi pi-spin pi-spinner" aria-hidden="true" />
      <span>Loading saved measured samples...</span>
    </div>
    <div v-else-if="editorLoadError" class="validation-errors editor-load-error" role="alert">
      <i class="pi pi-exclamation-triangle" aria-hidden="true" />
      <span>{{ editorLoadError }}</span>
      <Button
        label="Retry"
        icon="pi pi-refresh"
        class="p-button-sm p-button-outlined"
        @click="loadMeasuredSamples"
      />
    </div>
    <div v-if="saveError" class="validation-errors editor-save-error" role="alert">
      <i class="pi pi-exclamation-triangle" aria-hidden="true" />
      <span>{{ saveError }}</span>
      <Button label="Retry publication" icon="pi pi-refresh" class="p-button-sm" @click="publish" />
      <Button
        v-if="saveConflict"
        label="Refresh binding"
        icon="pi pi-sync"
        class="p-button-sm p-button-outlined"
        :loading="bindingRevisionLoading"
        title="Keep these edits and update only the saved-version check"
        @click="refreshBindingRevision"
      />
    </div>
    <small v-if="bindingRevisionNotice" class="binding-revision-notice" role="status">
      {{ bindingRevisionNotice }}
    </small>

    <section class="control-section" aria-labelledby="target-columns-title">
      <div class="section-heading">
        <button
          type="button"
          class="section-toggle"
          :aria-expanded="targetsExpanded"
          aria-controls="target-columns-content"
          @click="targetsExpanded = !targetsExpanded"
        >
          <i :class="targetsExpanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
          <span id="target-columns-title">Target columns</span>
          <i
            class="pi pi-info-circle section-info"
            title="Define one or more continuous or categorical responses. The selected response enters this DAG; the others remain in the portable sample table."
            aria-label="About target columns"
          />
        </button>
        <div v-if="targetsExpanded" class="icon-actions">
          <Button
            icon="pi pi-plus"
            class="p-button-sm"
            aria-label="Add target column"
            title="Add target column"
            @click="addTarget"
          />
          <Button
            icon="pi pi-trash"
            class="p-button-sm p-button-outlined p-button-danger"
            aria-label="Delete selected target column"
            title="Delete selected target column"
            :disabled="targets.length <= 1"
            @click="deleteTarget"
          />
        </div>
      </div>
      <div v-show="targetsExpanded" id="target-columns-content" class="editor-controls">
        <div class="field target-select">
          <label for="sample-target-select">Selected target</label>
          <Dropdown
            id="sample-target-select"
            v-model="selectedTarget"
            :options="targets"
            optionLabel="name"
            optionValue="name"
          />
        </div>
        <div class="field">
          <label for="sample-target-name">Name</label>
          <InputText id="sample-target-name" v-model.trim="targetNameDraft" />
        </div>
        <div class="field">
          <label for="sample-target-type">Type</label>
          <Dropdown
            id="sample-target-type"
            v-model="targetTypeDraft"
            :options="targetTypeOptions"
            optionLabel="label"
            optionValue="value"
          />
        </div>
        <Button
          label="Update target"
          icon="pi pi-check"
          class="p-button-sm p-button-outlined"
          @click="updateTarget"
        />
      </div>
    </section>

    <section class="control-section" aria-labelledby="group-annotations-title">
      <div class="section-heading">
        <button
          type="button"
          class="section-toggle"
          :aria-expanded="annotationsExpanded"
          aria-controls="group-annotations-content"
          @click="annotationsExpanded = !annotationsExpanded"
        >
          <i :class="annotationsExpanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
          <span id="group-annotations-title">Group annotations</span>
          <i
            class="pi pi-info-circle section-info"
            title="Add optional grouping metadata such as plate, batch, treatment, operator, or cohort. Group annotations are preserved but never silently used as model features."
            aria-label="About group annotations"
          />
        </button>
      </div>
      <div v-show="annotationsExpanded" id="group-annotations-content">
        <div class="editor-controls">
          <div class="field annotation-field">
            <label for="annotation-column">New group column</label>
            <div class="inline-control">
              <InputText
                id="annotation-column"
                v-model.trim="newColumn"
                placeholder="e.g. plate or batch"
                @keyup.enter="addColumn"
              />
              <Button label="Add" icon="pi pi-plus" class="p-button-sm" @click="addColumn" />
            </div>
          </div>
        </div>
        <div v-if="annotationColumns.length" class="annotation-list">
          <div v-for="column in annotationColumns" :key="column" class="annotation-row">
            <strong>{{ column }}</strong>
            <InputText v-model="annotationBulkValues[column]" placeholder="Value for every row" />
            <Button
              label="Apply to all"
              icon="pi pi-copy"
              class="p-button-sm p-button-outlined"
              @click="applyAnnotationToAll(column)"
            />
            <Button
              icon="pi pi-times"
              class="p-button-sm p-button-text p-button-danger"
              :aria-label="`Remove ${column}`"
              :title="`Remove ${column}`"
              @click="removeColumn(column)"
            />
          </div>
        </div>
      </div>
    </section>

    <section class="control-section" aria-labelledby="plate-title">
      <div class="section-heading">
        <button
          type="button"
          class="section-toggle"
          :aria-expanded="plateAssignmentExpanded"
          aria-controls="plate-assignment-content"
          @click="plateAssignmentExpanded = !plateAssignmentExpanded"
        >
          <i :class="plateAssignmentExpanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
          <span id="plate-title">Multi-well assignment</span>
          <i
            class="pi pi-info-circle section-info"
            title="Map measured samples to physical wells. The selected region repeats on additional plates."
            aria-label="About multi-well assignment"
          />
        </button>
      </div>
      <div
        v-show="plateAssignmentExpanded"
        id="plate-assignment-content"
        class="editor-controls plate-controls"
      >
        <div class="field compact-field plate-format-field">
          <label for="plate-format">Format</label>
          <Dropdown
            id="plate-format"
            v-model="plateFormatId"
            :options="plateFormatOptions"
            optionLabel="label"
            optionValue="value"
            :disabled="plateFormatOptions.length === 1"
          />
        </div>
        <div class="field compact-field">
          <label for="plate-start">Start</label>
          <Dropdown id="plate-start" v-model="plateStart" :options="wellOptions" />
        </div>
        <div class="field compact-field">
          <label for="plate-end">End</label>
          <Dropdown id="plate-end" v-model="plateEnd" :options="wellOptions" />
        </div>
        <div class="field direction-field">
          <label for="plate-direction">Direction</label>
          <Dropdown
            id="plate-direction"
            v-model="plateDirection"
            :options="plateDirectionOptions"
            optionLabel="label"
            optionValue="value"
          />
        </div>
        <label class="checkbox-control" for="plate-serpentine">
          <Checkbox id="plate-serpentine" v-model="plateSerpentine" binary />
          <span>Serpentine</span>
        </label>
        <Button label="Assign" icon="pi pi-th-large" class="p-button-sm" @click="assignPlate" />
        <Button
          label="Edit rows"
          icon="pi pi-pencil"
          class="p-button-sm p-button-outlined"
          title="Show plate and well columns for partial assignment or a single-row correction"
          @click="enableManualPlateEditing"
        />
      </div>
      <small v-if="plateAssignmentExpanded && plateError" class="inline-error" role="alert">
        {{ plateError }}
      </small>
      <div v-if="plateAssignmentExpanded" class="plan-sync" aria-live="polite">
        <template v-if="planLoading">
          <small>Loading acquisition plan...</small>
        </template>
        <template v-else-if="planError">
          <small class="inline-error">{{ planError }}</small>
        </template>
        <template v-else-if="plannedWells.length">
          <div class="plate-coverage">
            <Tag :value="`${planComparison.planned} planned`" severity="info" />
            <Tag :value="`${planComparison.matched} matched`" severity="success" />
            <Tag
              v-if="planComparison.unmeasured"
              :value="`${planComparison.unmeasured} not measured`"
              severity="warning"
            />
            <Tag :value="planSyncLabel" :severity="planDifferenceCount ? 'warning' : 'success'" />
            <Tag
              v-if="planComparison.outsidePlan"
              :value="`${planComparison.outsidePlan} outside plan`"
              severity="warning"
            />
          </div>
          <Button
            v-if="!confirmPlanAssignment"
            label="Use acquisition plan"
            icon="pi pi-arrow-down"
            class="p-button-sm p-button-outlined"
            :disabled="!canApplyPlan"
            :title="planAssignmentHint"
            @click="confirmPlanAssignment = true"
          />
          <div v-else class="plan-confirm">
            <span>Build a proposed measured-sample table from saved matches and plate order?</span>
            <Button
              label="Cancel"
              class="p-button-sm p-button-text"
              @click="confirmPlanAssignment = false"
            />
            <Button
              label="Preview differences"
              icon="pi pi-check"
              class="p-button-sm"
              @click="previewAcquisitionPlan"
            />
          </div>
          <small v-if="!canApplyPlan">{{ planAssignmentHint }}</small>
          <small v-else>Nothing is published until you review the proposed differences.</small>
        </template>
        <small v-else>No intended wells are saved for this dataset.</small>
      </div>
      <div
        v-if="proposalDifferences.length"
        class="proposal-preview"
        role="region"
        aria-label="Proposed measured sample differences"
      >
        <div class="section-heading">
          <div>
            <strong>Proposed measured samples</strong>
            <small
              >{{ proposalDifferences.length }} field changes across
              {{ proposalRowCount }} rows</small
            >
          </div>
          <div class="icon-actions">
            <Button label="Dismiss" class="p-button-sm p-button-text" @click="clearProposal" />
            <Button
              label="Apply proposal"
              icon="pi pi-check"
              class="p-button-sm"
              @click="applyProposal"
            />
          </div>
        </div>
        <DataTable :value="proposalDifferences.slice(0, 20)" size="small" stripedRows>
          <Column field="rowIndex" header="Row" />
          <Column field="field" header="Field" />
          <Column field="before" header="Published/current" />
          <Column field="after" header="Proposed" />
        </DataTable>
        <small v-if="proposalDifferences.length > 20">Showing the first 20 changes.</small>
      </div>
    </section>

    <div v-if="validationErrors.length" class="validation-errors" role="alert">
      <i class="pi pi-exclamation-triangle" aria-hidden="true"></i>
      <ul>
        <li v-for="error in validationErrors" :key="error">{{ error }}</li>
      </ul>
    </div>

    <section v-if="hasPlateAssignments" class="plate-preview" aria-labelledby="plate-preview-title">
      <div class="section-heading">
        <div class="compact-heading">
          <h4 id="plate-preview-title">Plate preview</h4>
          <i
            class="pi pi-info-circle section-info"
            title="Hover or focus an assigned well to inspect the corresponding sample-table row, targets, and group annotations."
            aria-label="About the plate preview"
          />
        </div>
        <Dropdown
          v-if="plateOptions.length > 1"
          v-model="previewPlate"
          :options="plateOptions"
          aria-label="Preview plate"
        />
      </div>
      <div class="plate-coverage" role="status">
        <Tag :value="`${previewPlateCoverage.assigned} assigned`" severity="info" />
        <Tag :value="`${previewPlateCoverage.included} included`" severity="success" />
        <Tag
          :value="`${previewPlateCoverage.targetValues}/${previewPlateCoverage.included} ${selectedTarget} values`"
          :severity="
            previewPlateCoverage.targetValues === previewPlateCoverage.included
              ? 'success'
              : 'warning'
          "
        />
        <Tag :value="`${previewPlateCoverage.empty} empty wells`" severity="secondary" />
      </div>
      <PlateMap96Well :wells="previewPlateWells" showLegend />
    </section>

    <section class="control-section sample-table-section" aria-labelledby="sample-table-title">
      <div class="section-heading">
        <button
          type="button"
          class="section-toggle"
          :aria-expanded="sampleTableExpanded"
          aria-controls="sample-table-content"
          @click="sampleTableExpanded = !sampleTableExpanded"
        >
          <i :class="sampleTableExpanded ? 'pi pi-chevron-down' : 'pi pi-chevron-right'" />
          <span id="sample-table-title">Measured samples</span>
          <Tag :value="`${rows.length.toLocaleString()} rows`" severity="secondary" />
          <i
            class="pi pi-info-circle section-info"
            title="The saved table preserves source-row identity, inclusion, typed targets, physical wells, and group annotations."
            aria-label="About the sample table"
          />
        </button>
      </div>

      <div v-show="sampleTableExpanded" id="sample-table-content">
        <DataTable
          :value="rows"
          dataKey="row_index"
          scrollable
          scrollHeight="46vh"
          stripedRows
          class="sample-table"
        >
          <Column field="row_index" header="#" frozen style="width: 4rem" />
          <Column frozen style="width: 4.5rem">
            <template #header>
              <Checkbox
                :modelValue="allRowsIncluded"
                :indeterminate="someRowsIncluded"
                binary
                aria-label="Select or clear all samples"
                title="Select or clear all samples"
                @update:model-value="setAllIncluded(Boolean($event))"
              />
            </template>
            <template #body="{ data }"><Checkbox v-model="data.include" binary /></template>
          </Column>
          <Column header="Sample ID" frozen style="min-width: 12rem">
            <template #body="{ data }"
              ><InputText v-model="data.sample_id" class="cell-input"
            /></template>
          </Column>
          <Column v-for="target in targets" :key="target.name" style="min-width: 11rem">
            <template #header>
              <span>{{ target.name }}</span>
              <Tag
                :value="target.type === 'continuous' ? 'Continuous' : 'Categorical'"
                severity="secondary"
                class="target-type-tag"
              />
            </template>
            <template #body="{ data }">
              <InputText v-model="data.targets[target.name]" class="cell-input" />
            </template>
          </Column>
          <Column v-if="showPhysicalColumns" header="Assigned plate" style="min-width: 8rem">
            <template #body="{ data }">
              <InputText v-model="data.plate_id" class="cell-input" />
            </template>
          </Column>
          <Column v-if="showPhysicalColumns" header="Well" style="min-width: 6rem">
            <template #body="{ data }">
              <InputText v-model="data.well" class="cell-input" />
            </template>
          </Column>
          <Column
            v-for="column in annotationColumns"
            :key="column"
            :header="column"
            style="min-width: 10rem"
          >
            <template #body="{ data }"
              ><InputText v-model="data.annotations[column]" class="cell-input"
            /></template>
          </Column>
        </DataTable>
      </div>
    </section>

    <section
      v-if="pendingPublication"
      class="publication-review"
      aria-labelledby="publication-title"
    >
      <div>
        <h4 id="publication-title">Publish a new immutable measured-sample version</h4>
        <p>
          Review complete: {{ publicationDifferenceCount }} changed fields across
          {{ publicationRowCount }} rows. The current version remains immutable and existing
          workflows keep their current file IDs.
        </p>
      </div>
      <Tag value="Explicit publication required" severity="warning" />
    </section>

    <template #footer>
      <Button label="Cancel" class="p-button-text" @click="visible = false" />
      <Button
        v-if="!pendingPublication"
        label="Review publication"
        icon="pi pi-search"
        :loading="saving"
        :disabled="editorLoading || Boolean(editorLoadError)"
        @click="reviewPublication"
      />
      <Button
        v-else
        label="Publish new immutable version"
        icon="pi pi-upload"
        :loading="saving"
        :disabled="editorLoading || Boolean(editorLoadError)"
        @click="publish"
      />
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import InputText from "primevue/inputtext";
import Tag from "primevue/tag";

import api from "@/api/client";
import PlateMap96Well from "@/components/PlateMap96Well.vue";
import {
  defaultPlateFormatId,
  formatWell,
  getPlateFormat,
  plateFormats,
} from "@/utils/plateFormats";
import {
  assignPlateCoordinates,
  compareAcquisitionPlan,
  createSampleTableRows,
  isReservedSampleTableColumn,
  normalizeAnnotationColumnName,
  proposeMeasuredSamples,
  serializeSampleTableCsv,
  validateSampleTable,
  wellForOrdinal,
  type PlateTraversalDirection,
  type SampleTableRow,
  type SampleTargetDefinition,
  type SampleTargetType,
} from "@/utils/sampleTable";
import { getErrorMessage } from "@/utils/errors";
import type { AcquisitionPlan, MeasuredSampleTableEditor } from "@/types";

export interface SampleTableSavePayload {
  file: File;
  expectedRevision: string | null;
  targetColumn: string;
  targetType: SampleTargetType;
  summary: SampleTableSaveSummary;
}

export interface SampleTableSaveSummary {
  sourceFileId: number;
  totalSamples: number;
  includedSamples: number;
  selectedTargetValues: number;
  targetColumns: SampleTargetDefinition[];
  targetValueCounts: Record<string, number>;
  groupColumns: string[];
  plateFormatId: string;
  plateFormatLabel: string;
  assignedWells: number;
  plateCount: number;
}

const props = defineProps<{
  sampleCount: number;
  sampleLabels: string[];
  sourceFileId: number;
  sourceName: string;
  experimentId: number;
  analysisBinding?: {
    revision: string;
    sample_table_file_id: number;
    selected_target: string;
    target_type: SampleTargetType;
  };
  saving?: boolean;
  saveError?: string;
  saveConflict?: boolean;
}>();

const emit = defineEmits<{
  (event: "save", payload: SampleTableSavePayload): void;
  (event: "clearSaveError"): void;
}>();

const visible = ref(false);
const rows = ref<SampleTableRow[]>([]);
const originalRows = ref<SampleTableRow[]>([]);
const targets = ref<SampleTargetDefinition[]>([{ name: "target", type: "continuous" }]);
const selectedTarget = ref("target");
const targetNameDraft = ref("target");
const targetTypeDraft = ref<SampleTargetType>("continuous");
const annotationColumns = ref<string[]>([]);
const annotationBulkValues = ref<Record<string, string>>({});
const newColumn = ref("");
const validationErrors = ref<string[]>([]);
const targetsExpanded = ref(true);
const annotationsExpanded = ref(true);
const plateAssignmentExpanded = ref(true);
const sampleTableExpanded = ref(true);
const plateFormatId = ref(defaultPlateFormatId);
const plateStart = ref("A01");
const initialPlateFormat = getPlateFormat();
const plateEnd = ref(
  formatWell(
    initialPlateFormat,
    initialPlateFormat.rows.length - 1,
    initialPlateFormat.columns - 1,
  ),
);
const plateDirection = ref<PlateTraversalDirection>("rows");
const plateSerpentine = ref(false);
const plateError = ref("");
const manualPlateEditing = ref(false);
const previewPlate = ref("plate-1");
const plannedWells = ref<string[]>([]);
const loadedPlan = ref<AcquisitionPlan | null>(null);
const proposedRows = ref<SampleTableRow[]>([]);
const proposalDifferences = ref<ReturnType<typeof proposeMeasuredSamples>["differences"]>([]);
const pendingPublication = ref<SampleTableSavePayload | null>(null);
const planLoading = ref(false);
const planError = ref("");
const confirmPlanAssignment = ref(false);
const editorLoading = ref(false);
const editorLoadError = ref("");
const bindingRevision = ref<string | null>(null);
const bindingRevisionLoading = ref(false);
const bindingRevisionNotice = ref("");
const targetTypeOptions = [
  { label: "Continuous", value: "continuous" },
  { label: "Categorical", value: "categorical" },
];
const plateDirectionOptions = [
  { label: "Across rows", value: "rows" },
  { label: "Down columns", value: "columns" },
];
const plateFormatOptions = plateFormats.map((format) => ({
  label: format.label,
  value: format.id,
}));
const selectedPlateFormat = computed(() => getPlateFormat(plateFormatId.value));
const wellOptions = computed(() =>
  Array.from({ length: selectedPlateFormat.value.capacity }, (_, index) =>
    wellForOrdinal(index, selectedPlateFormat.value.id),
  ),
);

watch(plateFormatId, () => {
  const format = selectedPlateFormat.value;
  plateStart.value = formatWell(format, 0, 0);
  plateEnd.value = formatWell(format, format.rows.length - 1, format.columns - 1);
  plateError.value = "";
});

watch(selectedTarget, (name) => {
  const target = targets.value.find((item) => item.name === name);
  if (!target) return;
  targetNameDraft.value = target.name;
  targetTypeDraft.value = target.type;
});

function openEditor(): void {
  emit("clearSaveError");
  targets.value = [{ name: "target", type: "continuous" }];
  selectedTarget.value = "target";
  targetNameDraft.value = "target";
  targetTypeDraft.value = "continuous";
  rows.value = createSampleTableRows(props.sampleCount, props.sourceFileId, props.sampleLabels, [
    "target",
  ]);
  originalRows.value = rows.value.map(cloneRow);
  annotationColumns.value = [];
  annotationBulkValues.value = {};
  validationErrors.value = [];
  plateError.value = "";
  manualPlateEditing.value = false;
  plateFormatId.value = defaultPlateFormatId;
  targetsExpanded.value = true;
  annotationsExpanded.value = true;
  plateAssignmentExpanded.value = true;
  sampleTableExpanded.value = true;
  visible.value = true;
  editorLoadError.value = "";
  editorLoading.value = false;
  bindingRevision.value = props.analysisBinding?.revision ?? null;
  bindingRevisionNotice.value = "";
  pendingPublication.value = null;
  clearProposal();
  void loadAcquisitionPlan();
  void loadMeasuredSamples();
}

async function loadMeasuredSamples(): Promise<void> {
  if (!props.analysisBinding) return;
  editorLoading.value = true;
  editorLoadError.value = "";
  try {
    const { data } = await api.get<MeasuredSampleTableEditor>(
      `/builder/analysis-binding/${props.sourceFileId}`,
    );
    if (data.revision !== bindingRevision.value) {
      throw new Error("Measured samples changed. Close and reopen this editor.");
    }
    bindingRevision.value = data.revision;
    rows.value = data.rows.map((row) => ({
      ...row,
      targets: { ...row.targets },
      annotations: { ...row.annotations },
    }));
    originalRows.value = rows.value.map(cloneRow);
    targets.value = data.target_definitions.map((target) => ({ ...target }));
    annotationColumns.value = [...data.annotation_columns];
    annotationBulkValues.value = Object.fromEntries(
      data.annotation_columns.map((column) => [column, ""]),
    );
    selectedTarget.value = data.selected_target;
    plateFormatId.value = data.plate_format_id;
    manualPlateEditing.value = rows.value.some((row) => Boolean(row.plate_id || row.well));
  } catch (error: unknown) {
    editorLoadError.value = getErrorMessage(
      error,
      "Unable to load the saved measured-sample version.",
    );
  } finally {
    editorLoading.value = false;
  }
}

async function refreshBindingRevision(): Promise<void> {
  bindingRevisionLoading.value = true;
  bindingRevisionNotice.value = "";
  try {
    const { data } = await api.get<{ revision: string | null }>(
      `/builder/analysis-binding/${props.sourceFileId}/revision`,
    );
    bindingRevision.value = data.revision;
    bindingRevisionNotice.value =
      "Saved-version check refreshed. Your edits are unchanged; publish them as a new immutable version.";
    emit("clearSaveError");
  } catch (error: unknown) {
    bindingRevisionNotice.value = getErrorMessage(
      error,
      "Unable to refresh the saved measured-sample version.",
    );
  } finally {
    bindingRevisionLoading.value = false;
  }
}

async function loadAcquisitionPlan(): Promise<void> {
  planLoading.value = true;
  planError.value = "";
  plannedWells.value = [];
  confirmPlanAssignment.value = false;
  try {
    const { data } = await api.get<AcquisitionPlan>(
      `/experiments/${props.experimentId}/acquisition-plan`,
    );
    plannedWells.value = data.wells.map((well) => well.well_position);
    loadedPlan.value = data;
  } catch (error: unknown) {
    planError.value = getErrorMessage(error, "Unable to load the acquisition plan.");
  } finally {
    planLoading.value = false;
  }
}

function nextTargetName(): string {
  let ordinal = targets.value.length + 1;
  while (targets.value.some((target) => target.name === `target_${ordinal}`)) ordinal += 1;
  return `target_${ordinal}`;
}

function addTarget(): void {
  const name = nextTargetName();
  targets.value.push({ name, type: "continuous" });
  for (const row of rows.value) row.targets[name] = "";
  selectedTarget.value = name;
  validationErrors.value = [];
}

function updateTarget(): void {
  const current = targets.value.find((target) => target.name === selectedTarget.value);
  const normalized = normalizeAnnotationColumnName(targetNameDraft.value);
  if (!current || !normalized) {
    validationErrors.value = ["Target column name is required."];
    return;
  }
  if (isReservedSampleTableColumn(normalized) || annotationColumns.value.includes(normalized)) {
    validationErrors.value = [`'${normalized}' is already a structural or annotation column.`];
    return;
  }
  if (targets.value.some((target) => target !== current && target.name === normalized)) {
    validationErrors.value = [`Target column '${normalized}' already exists.`];
    return;
  }
  const previous = current.name;
  current.name = normalized;
  current.type = targetTypeDraft.value;
  if (previous !== normalized) {
    for (const row of rows.value) {
      row.targets[normalized] = row.targets[previous] ?? "";
      delete row.targets[previous];
    }
  }
  selectedTarget.value = normalized;
  validationErrors.value = [];
}

function deleteTarget(): void {
  if (targets.value.length <= 1) return;
  const index = targets.value.findIndex((target) => target.name === selectedTarget.value);
  if (index < 0) return;
  const [removed] = targets.value.splice(index, 1);
  for (const row of rows.value) delete row.targets[removed.name];
  selectedTarget.value = targets.value[Math.min(index, targets.value.length - 1)].name;
  validationErrors.value = [];
}

function addColumn(): void {
  const normalized = normalizeAnnotationColumnName(newColumn.value);
  if (!normalized) return;
  if (
    isReservedSampleTableColumn(normalized) ||
    targets.value.some((target) => target.name === normalized)
  ) {
    validationErrors.value = [`'${normalized}' is already a structural or target column.`];
    return;
  }
  if (!annotationColumns.value.includes(normalized)) annotationColumns.value.push(normalized);
  for (const row of rows.value) row.annotations[normalized] ??= "";
  annotationBulkValues.value[normalized] = "";
  newColumn.value = "";
  validationErrors.value = [];
}

function applyAnnotationToAll(column: string): void {
  const value = annotationBulkValues.value[column] ?? "";
  for (const row of rows.value) row.annotations[column] = value;
}

function removeColumn(column: string): void {
  annotationColumns.value = annotationColumns.value.filter((item) => item !== column);
  for (const row of rows.value) delete row.annotations[column];
  delete annotationBulkValues.value[column];
}

const allRowsIncluded = computed(
  () => rows.value.length > 0 && rows.value.every((row) => row.include),
);
const someRowsIncluded = computed(
  () => rows.value.some((row) => row.include) && !allRowsIncluded.value,
);

function setAllIncluded(value: boolean): void {
  for (const row of rows.value) row.include = value;
}

function assignPlate(): void {
  try {
    assignPlateCoordinates(rows.value, {
      formatId: plateFormatId.value,
      startWell: plateStart.value,
      endWell: plateEnd.value,
      direction: plateDirection.value,
      serpentine: plateSerpentine.value,
    });
    previewPlate.value = "plate-1";
    plateError.value = "";
  } catch (error: unknown) {
    plateError.value = error instanceof Error ? error.message : "Unable to assign plate wells.";
  }
}

function enableManualPlateEditing(): void {
  manualPlateEditing.value = true;
  sampleTableExpanded.value = true;
}

const canApplyPlan = computed(() => plannedWells.value.length > 0 && rows.value.length > 0);
const planAssignmentHint = computed(() =>
  canApplyPlan.value
    ? "Preview matching by retained acquisition records, then planned plate order"
    : `A proposal needs planned wells and measured rows (${plannedWells.value.length} planned, ${rows.value.length} measured).`,
);
const planComparison = computed(() => compareAcquisitionPlan(rows.value, plannedWells.value));
const planDifferenceCount = computed(() =>
  loadedPlan.value ? proposeMeasuredSamples(rows.value, loadedPlan.value).differences.length : 0,
);
const planSyncLabel = computed(() =>
  planDifferenceCount.value ? "Publication needed" : "Plan and measured samples synchronized",
);

function previewAcquisitionPlan(): void {
  if (!loadedPlan.value) return;
  const proposal = proposeMeasuredSamples(rows.value, loadedPlan.value);
  proposedRows.value = proposal.rows;
  proposalDifferences.value = proposal.differences;
  if (!proposal.differences.length)
    plateError.value = "The measured samples already match this acquisition plan.";
  confirmPlanAssignment.value = false;
}
function clearProposal(): void {
  proposedRows.value = [];
  proposalDifferences.value = [];
}
function applyProposal(): void {
  rows.value = proposedRows.value.map(cloneRow);
  const proposalColumns = new Set(rows.value.flatMap((row) => Object.keys(row.annotations)));
  annotationColumns.value = [...new Set([...annotationColumns.value, ...proposalColumns])];
  manualPlateEditing.value = true;
  previewPlate.value = "plate-1";
  plateError.value = "";
  pendingPublication.value = null;
  clearProposal();
}
const proposalRowCount = computed(
  () => new Set(proposalDifferences.value.map((item) => item.rowIndex)).size,
);

const hasPlateAssignments = computed(() => rows.value.some((row) => row.plate_id && row.well));
const showPhysicalColumns = computed(() => manualPlateEditing.value || hasPlateAssignments.value);
const includedSampleCount = computed(() => rows.value.filter((row) => row.include).length);
const selectedTargetValueCount = computed(
  () =>
    rows.value.filter((row) => row.include && Boolean(row.targets[selectedTarget.value]?.trim()))
      .length,
);
const plateOptions = computed(() =>
  Array.from(new Set(rows.value.map((row) => row.plate_id).filter(Boolean))).sort((left, right) => {
    const leftNumber = Number.parseInt(left.replace(/^plate-/, ""), 10);
    const rightNumber = Number.parseInt(right.replace(/^plate-/, ""), 10);
    return leftNumber - rightNumber;
  }),
);
watch(plateOptions, (options) => {
  if (options.length && !options.includes(previewPlate.value)) {
    previewPlate.value = options[0];
  }
});
const previewPlateWells = computed(() => {
  const selected = targets.value.find((target) => target.name === selectedTarget.value);
  return rows.value
    .filter((row) => row.plate_id === previewPlate.value && row.well)
    .map((row) => {
      const targetValue = selected ? row.targets[selected.name] || "not entered" : "not selected";
      return {
        well_position: row.well,
        label: row.sample_id,
        assigned: true,
        excluded: !row.include,
        details: [
          { label: "Source row", value: String(row.row_index) },
          { label: "Included", value: row.include ? "Yes" : "No" },
          { label: "Assigned plate", value: row.plate_id },
          { label: "Well", value: row.well },
          ...targets.value.map((target) => ({
            label: `${target.name} (${target.type})`,
            value: row.targets[target.name] || "",
          })),
          ...annotationColumns.value.map((column) => ({
            label: column,
            value: row.annotations[column] || "",
          })),
        ],
        tooltip: [
          row.sample_id,
          `Source row ${row.row_index}`,
          row.include ? "Included" : "Excluded",
          selected ? `${selected.name}: ${targetValue}` : "No selected target",
        ].join(" · "),
      };
    });
});
const previewPlateCoverage = computed(() => {
  const plateRows = rows.value.filter(
    (row) => row.plate_id === previewPlate.value && Boolean(row.well.trim()),
  );
  const uniqueWells = new Set(plateRows.map((row) => row.well.trim().toUpperCase()));
  return {
    assigned: plateRows.length,
    included: plateRows.filter((row) => row.include).length,
    targetValues: plateRows.filter(
      (row) => row.include && Boolean(row.targets[selectedTarget.value]?.trim()),
    ).length,
    empty: Math.max(0, selectedPlateFormat.value.capacity - uniqueWells.size),
  };
});

function safeFileStem(value: string): string {
  return (
    value
      .replace(/\.[^.]+$/, "")
      .replace(/[^a-zA-Z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "") || "dataset"
  );
}

function cloneRow(row: SampleTableRow): SampleTableRow {
  return { ...row, targets: { ...row.targets }, annotations: { ...row.annotations } };
}
function buildSavePayload(): SampleTableSavePayload | null {
  const result = validateSampleTable(
    rows.value,
    targets.value,
    selectedTarget.value,
    annotationColumns.value,
    plateFormatId.value,
  );
  validationErrors.value = result.errors;
  if (!result.valid) return null;
  const selected = targets.value.find((target) => target.name === selectedTarget.value);
  if (!selected) return null;
  const csv = serializeSampleTableCsv(
    rows.value,
    targets.value,
    annotationColumns.value,
    plateFormatId.value,
  );
  const file = new File([csv], `${safeFileStem(props.sourceName)}-sample-table.csv`, {
    type: "text/csv;charset=utf-8",
  });
  return {
    file,
    expectedRevision: bindingRevision.value,
    targetColumn: selected.name,
    targetType: selected.type,
    summary: {
      sourceFileId: props.sourceFileId,
      totalSamples: rows.value.length,
      includedSamples: includedSampleCount.value,
      selectedTargetValues: selectedTargetValueCount.value,
      targetColumns: targets.value.map((target) => ({ ...target })),
      targetValueCounts: Object.fromEntries(
        targets.value.map((target) => [
          target.name,
          rows.value.filter((row) => row.include && Boolean(row.targets[target.name]?.trim()))
            .length,
        ]),
      ),
      groupColumns: [...annotationColumns.value],
      plateFormatId: selectedPlateFormat.value.id,
      plateFormatLabel: selectedPlateFormat.value.label,
      assignedWells: rows.value.filter((row) => row.plate_id.trim() && row.well.trim()).length,
      plateCount: new Set(rows.value.map((row) => row.plate_id.trim()).filter(Boolean)).size,
    },
  };
}
function reviewPublication(): void {
  pendingPublication.value = buildSavePayload();
}
function publish(): void {
  const payload = buildSavePayload();
  if (!payload) return;
  pendingPublication.value = payload;
  emit("save", payload);
}

const publicationDifferences = computed(() => {
  const before = new Map(originalRows.value.map((row) => [row.row_index, row]));
  const changes: Array<{ rowIndex: number; field: string }> = [];
  for (const row of rows.value) {
    const prior = before.get(row.row_index);
    if (!prior) {
      changes.push({ rowIndex: row.row_index, field: "row" });
      continue;
    }
    for (const field of ["sample_id", "include", "plate_id", "well"] as const) {
      if (row[field] !== prior[field]) changes.push({ rowIndex: row.row_index, field });
    }
    if (JSON.stringify(row.targets) !== JSON.stringify(prior.targets))
      changes.push({ rowIndex: row.row_index, field: "targets" });
    if (JSON.stringify(row.annotations) !== JSON.stringify(prior.annotations))
      changes.push({ rowIndex: row.row_index, field: "annotations" });
  }
  return changes;
});
const publicationDifferenceCount = computed(() => publicationDifferences.value.length);
const publicationRowCount = computed(
  () => new Set(publicationDifferences.value.map((item) => item.rowIndex)).size,
);

function markSaved(): void {
  originalRows.value = rows.value.map(cloneRow);
  pendingPublication.value = null;
  visible.value = false;
}

defineExpose({ markSaved });
</script>

<style scoped>
.editor-intro,
.editor-controls,
.inline-control,
.section-heading,
.icon-actions,
.annotation-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.intro-tags,
.plate-coverage,
.plan-confirm {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.plan-sync {
  display: grid;
  gap: 0.65rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid #e2e8f0;
}
.plan-sync > .p-button {
  justify-self: start;
}
.plan-confirm {
  justify-content: flex-start;
}
.editor-state,
.editor-load-error,
.editor-save-error {
  margin-bottom: 0.8rem;
}
.editor-save-error {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.65rem;
}
.binding-revision-notice {
  display: block;
  margin-bottom: 0.8rem;
  color: #475569;
}
.editor-state ~ .control-section,
.editor-load-error ~ .control-section,
.editor-state ~ .plate-preview,
.editor-load-error ~ .plate-preview {
  pointer-events: none;
  opacity: 0.45;
}
.editor-intro,
.section-heading {
  justify-content: space-between;
}
.editor-intro {
  margin-bottom: 1rem;
}
.editor-intro p,
.section-heading p {
  margin: 0.25rem 0 0;
  color: #64748b;
}
.section-heading h4 {
  margin: 0;
}
.section-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  min-height: 2rem;
  padding: 0;
  border: 0;
  background: transparent;
  color: #0f172a;
  cursor: pointer;
  font: inherit;
  font-weight: 650;
  text-align: left;
}
.section-toggle:focus-visible {
  border-radius: 0.35rem;
  outline: 2px solid #3b82f6;
  outline-offset: 3px;
}
.section-info {
  color: #64748b;
  cursor: help;
  font-size: 0.9rem;
}
.compact-heading {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.control-section {
  border: 1px solid #e2e8f0;
  border-radius: 0.65rem;
  padding: 0.85rem;
  margin-bottom: 0.8rem;
}
.editor-controls {
  align-items: end;
  flex-wrap: wrap;
  margin-top: 0.75rem;
}
.field {
  display: grid;
  gap: 0.35rem;
}
.field label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #475569;
}
.target-select,
.direction-field {
  min-width: 12rem;
}
.annotation-field {
  min-width: 22rem;
}
.compact-field {
  width: 7rem;
}
.inline-control .p-inputtext {
  flex: 1;
}
.annotation-list {
  display: grid;
  gap: 0.55rem;
  margin-top: 0.75rem;
}
.annotation-row strong {
  min-width: 9rem;
}
.annotation-row .p-inputtext {
  min-width: 14rem;
}
.checkbox-control {
  align-items: center;
  display: flex;
  gap: 0.5rem;
  padding-bottom: 0.45rem;
}
.validation-errors {
  display: flex;
  gap: 0.5rem;
  color: #b91c1c;
  background: #fef2f2;
  padding: 0.75rem;
  margin-bottom: 0.75rem;
}
.validation-errors ul {
  margin: 0;
  padding-left: 1.25rem;
}
.inline-error {
  color: #b91c1c;
}
.cell-input {
  width: 100%;
}
.target-type-tag {
  margin-left: 0.4rem;
  font-size: 0.65rem;
}
.plate-preview {
  border-top: 1px solid #e2e8f0;
  margin-top: 1rem;
  margin-bottom: 1rem;
  padding-top: 1rem;
}
.plate-coverage {
  margin: 0.65rem 0 0.85rem;
}
.sample-table-section {
  padding-bottom: 0;
}
.sample-table-section .sample-table {
  margin-top: 0.75rem;
}
</style>
