<template>
  <section class="contents-panel" aria-label="Dataset contents">
    <details
      v-if="dataStore.fileInfo || dataStore.catalogDatasetInfo"
      class="global-display-metadata"
    >
      <summary>Display Settings</summary>
      <div class="global-display-metadata-controls">
        <MetadataEditor
          v-model:x-title="editXTitle"
          v-model:x-units="editXUnits"
          v-model:y-title="editYTitle"
          v-model:is-time-series="isTimeSeriesToggle"
          v-model:target-mode="targetMode"
          v-model:selected-target="selectedTarget"
          :x-title-options="xTitleOptions"
          :x-units-options="xUnitsOptions"
          :y-title-options="yTitleOptions"
          :target-options="targetOptions"
          :show-target-controls="showTargetControls"
        />
      </div>
    </details>

    <div v-if="dataStore.fileInfoLoading" class="explore-loading">
      <ProgressSpinner style="width: 36px; height: 36px" />
      <span>Loading contents...</span>
    </div>

    <div v-else-if="dataStore.fileInfoError" class="explore-error">
      <i class="pi pi-exclamation-triangle"></i>
      <span>{{ dataStore.fileInfoError }}</span>
    </div>

    <div v-else-if="dataStore.catalogDatasetLoading" class="explore-loading">
      <ProgressSpinner style="width: 36px; height: 36px" />
      <span>Loading dataset info...</span>
    </div>

    <div v-else-if="dataStore.catalogDatasetError" class="explore-error">
      <i class="pi pi-exclamation-triangle"></i>
      <span>{{ dataStore.catalogDatasetError }}</span>
    </div>

    <div v-else-if="dataStore.catalogDatasetInfo" class="explore-content">
      <div class="explore-header">
        <div class="explore-title">
          <i class="pi pi-database"></i>
          <span>{{ dataStore.catalogDatasetInfo.label }}</span>
          <Tag
            v-if="dataStore.catalogDatasetInfo.technique"
            :value="dataStore.catalogDatasetInfo.technique"
            severity="info"
          />
        </div>
      </div>

      <div v-if="catalogBoxPlotData.length" class="explore-table">
        <div class="table-summary">
          <Tag value="Properties" severity="info" />
          <span class="meta-val">
            {{ dataStore.catalogDatasetInfo.n_samples?.toLocaleString() }} samples &times;
            {{ dataStore.catalogDatasetInfo.n_features }} features
          </span>
        </div>
        <PlotlyChart
          :data="catalogBoxPlotData"
          :layout="catalogBoxPlotLayout"
          :config="{ displayModeBar: true, displaylogo: false }"
        />
      </div>
      <div v-else-if="catalogPreviewPlotData.length" class="explore-plot">
        <PlotlyChart
          :data="catalogPreviewPlotData"
          :layout="catalogPreviewPlotLayout"
          :config="{ displayModeBar: true, displaylogo: false }"
        />
      </div>

      <div class="explore-panels">
        <div class="metadata-panel">
          <h4 class="panel-title">Dataset Metadata</h4>
          <div class="metadata-table">
            <div v-if="dataStore.catalogDatasetInfo.source" class="meta-row">
              <span class="meta-key">Source</span>
              <span class="meta-val">{{ dataStore.catalogDatasetInfo.source }}</span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.file_metadata?.name" class="meta-row">
              <span class="meta-key">Title</span>
              <span class="meta-val">{{ dataStore.catalogDatasetInfo.file_metadata.name }}</span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.n_samples" class="meta-row">
              <span class="meta-key">Samples</span>
              <span class="meta-val">{{
                dataStore.catalogDatasetInfo.n_samples.toLocaleString()
              }}</span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.n_features" class="meta-row">
              <span class="meta-key">Features</span>
              <span class="meta-val">{{
                dataStore.catalogDatasetInfo.n_features.toLocaleString()
              }}</span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.wavelength_min != null" class="meta-row">
              <span class="meta-key">Spectral Range</span>
              <span class="meta-val">
                {{ dataStore.catalogDatasetInfo.wavelength_min.toFixed(1) }} &ndash;
                {{ dataStore.catalogDatasetInfo.wavelength_max?.toFixed(1) }}
                {{ dataStore.catalogDatasetInfo.x_units || "" }}
              </span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.task_type" class="meta-row">
              <span class="meta-key">Task Type</span>
              <span class="meta-val">{{ dataStore.catalogDatasetInfo.task_type }}</span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.target_names?.length" class="meta-row">
              <span class="meta-key">Classes</span>
              <span class="meta-val">{{
                dataStore.catalogDatasetInfo.target_names.join(", ")
              }}</span>
            </div>
          </div>
        </div>

        <div class="metadata-panel">
          <div v-if="dataStore.catalogDatasetInfo.property_stats?.length">
            <h4 class="panel-title">Reference Properties</h4>
            <PropertyStatsTable :stats="dataStore.catalogDatasetInfo.property_stats" />
          </div>
          <div v-else>
            <h4 class="panel-title">Description</h4>
            <p class="dataset-description">
              {{ dataStore.catalogDatasetInfo.description }}
            </p>
          </div>
        </div>
      </div>

      <DataStorySection />
    </div>

    <div v-else-if="!dataStore.fileInfo" class="explore-empty">
      <i class="pi pi-table"></i>
      <h3>No contents selected</h3>
      <p>
        Select a dataset name to view all raw contents, or select a file to view that file alone.
      </p>
    </div>

    <DatasetAnalysisReadinessCard
      v-if="displayedAnalysisReadiness && !dataStore.catalogDatasetInfo"
      :readiness="displayedAnalysisReadiness"
      :binding="dataStore.fileInfo?.analysis_binding ?? undefined"
      :unbinding="sampleTableSaving"
      :target-options="analysisTargetOptions"
      :group-options="analysisGroupOptions"
      :selected-target="analysisTarget"
      :selected-group="analysisGroup"
      :loading="analysisReadinessLoading"
      :preview-error="analysisReadinessError"
      :is-target-preview="Boolean(analysisTarget)"
      :selection-status="analysisSelectionStatus"
      @unbind="unbindSampleTable"
      @update:selected-target="commitAnalysisTarget"
      @update:selected-group="commitAnalysisGroup"
    />

    <details
      v-if="dataStore.fileInfo && !dataStore.catalogDatasetInfo"
      class="focused-dataset-details"
    >
      <summary>
        <span>
          <strong>Active dataset: {{ contentsTitle }}</strong>
          <small>Files · acquisition · labels · metadata · quality</small>
        </span>
      </summary>
      <div class="explore-content">
        <div class="explore-header">
          <div class="explore-title">
            <span class="essential-card-number">1</span>
            <div class="loaded-file-title">
              <small>Loaded files</small>
              <span>{{ contentsTitle }}</span>
            </div>
            <Tag
              v-if="contentsFileCount"
              :value="`${contentsFileCount} file${contentsFileCount === 1 ? '' : 's'}`"
              severity="info"
            />
          </div>
          <SampleTableEditor
            v-if="canPrepareSamples"
            ref="sampleTableEditorRef"
            :sampleCount="dataStore.fileInfo.n_samples"
            :sampleLabels="sampleLabels"
            :sourceFileId="dataStore.activeFileId!"
            :sourceName="contentsTitle"
            :experimentId="dataStore.activeExperimentId!"
            :analysisBinding="dataStore.fileInfo.analysis_binding"
            :saving="sampleTableSaving"
            :saveError="sampleTableSaveError"
            :saveConflict="sampleTableSaveConflict"
            @save="saveSampleTable"
            @clearSaveError="clearSampleTableSaveError"
          />
        </div>
        <details v-if="selectedFileNames.length" class="selected-files-details">
          <summary>
            {{ selectedFileNames.length }} selected file{{
              selectedFileNames.length === 1 ? "" : "s"
            }}
          </summary>
          <ul>
            <li v-for="fileName in selectedFileNames" :key="fileName">{{ fileName }}</li>
          </ul>
        </details>

        <section
          v-if="sampleTableMessage"
          class="sample-table-message"
          :class="sampleTableMessage.kind"
          role="status"
          aria-live="polite"
        >
          <template v-if="sampleTableMessage.kind === 'success'">
            <div class="sample-table-receipt-heading">
              <i class="pi pi-check-circle" aria-hidden="true"></i>
              <div>
                <strong>Measured samples saved</strong>
                <p>
                  {{ sampleTableMessage.filePath }} · file #{{ sampleTableMessage.fileId }} · from
                  source file #{{ sampleTableMessage.summary.sourceFileId }}
                </p>
              </div>
            </div>
            <div class="sample-table-receipt-facts">
              <Tag
                :value="`${sampleTableMessage.summary.includedSamples}/${sampleTableMessage.summary.totalSamples} included`"
                severity="success"
              />
              <Tag
                :value="`${sampleTableMessage.summary.selectedTargetValues} ${sampleTableMessage.targetColumn} values`"
                severity="info"
              />
              <Tag
                :value="`${sampleTableMessage.summary.targetColumns.length} target column${sampleTableMessage.summary.targetColumns.length === 1 ? '' : 's'}`"
                severity="secondary"
              />
              <Tag
                v-if="sampleTableMessage.summary.assignedWells"
                :value="`${sampleTableMessage.summary.assignedWells} wells on ${sampleTableMessage.summary.plateCount} ${sampleTableMessage.summary.plateFormatLabel}${sampleTableMessage.summary.plateCount === 1 ? '' : 's'}`"
                severity="secondary"
              />
            </div>
            <dl class="sample-table-receipt-details">
              <dt>Targets</dt>
              <dd>
                {{
                  formatSavedTargets(
                    sampleTableMessage.summary.targetColumns,
                    sampleTableMessage.summary.targetValueCounts,
                  )
                }}
              </dd>
              <dt>Groups</dt>
              <dd>{{ sampleTableMessage.summary.groupColumns.join(", ") || "None" }}</dd>
            </dl>
            <p class="sample-table-next-step">
              Existing workflows remain bound to their previous file IDs. Start or rebind a
              canonical workflow to use saved file #{{ sampleTableMessage.fileId }}; no prior result
              was changed.
            </p>
          </template>
          <template v-else>
            <i class="pi pi-exclamation-triangle" aria-hidden="true"></i>
            <span>{{ sampleTableMessage.text }}</span>
          </template>
        </section>

        <section
          v-if="requiresDimensionProjection"
          class="dimension-projection-notice"
          role="status"
        >
          <i class="pi pi-clone" aria-hidden="true"></i>
          <div>
            <strong
              >{{ dataStore.fileInfo.ndim || dataStore.fileInfo.shape?.length }}-D dataset
              retained</strong
            >
            <p>
              Choose the scientifically intended inner-mode index with
              <code>selection.dimension_project</code> before using a 2-D-only analysis node. The
              Workbench will not flatten these dimensions implicitly.
            </p>
          </div>
        </section>

        <div v-if="boxPlotData.length" class="explore-table">
          <div class="table-summary">
            <Tag value="Properties" severity="info" />
            <span class="meta-val">
              {{ dataStore.fileInfo.n_samples?.toLocaleString() }} samples &times;
              {{ dataStore.fileInfo.n_features }} properties
            </span>
          </div>
          <PlotlyChart
            :data="boxPlotData"
            :layout="boxPlotLayout"
            :config="{ displayModeBar: true, displaylogo: false }"
          />
        </div>

        <section
          v-if="acquisitionSettings.length"
          class="essential-card"
          aria-label="Acquisition settings"
        >
          <div class="essential-card-heading">
            <span class="essential-card-number">2</span>
            <div>
              <h4>Acquisition settings</h4>
            </div>
          </div>
          <dl class="essential-fact-grid">
            <template v-for="setting in acquisitionSettings" :key="setting.label">
              <dt>{{ setting.label }}</dt>
              <dd :title="setting.detail || setting.value">{{ setting.value }}</dd>
            </template>
          </dl>
        </section>

        <section v-if="sampleLabels.length" class="essential-card" aria-label="Sample labels">
          <div class="essential-card-heading">
            <span class="essential-card-number">3</span>
            <div>
              <h4>Sample labels</h4>
              <p>{{ sampleLabels.length }} identities</p>
            </div>
            <Button
              v-if="sampleLabels.length > SAMPLE_LABEL_PREVIEW_COUNT"
              :label="sampleLabelsExpanded ? 'Show less' : `Show all ${sampleLabels.length}`"
              class="p-button-text p-button-sm"
              @click="sampleLabelsExpanded = !sampleLabelsExpanded"
            />
          </div>
          <div class="sample-label-list">
            <Tag
              v-for="label in visibleSampleLabels"
              :key="label"
              :value="label"
              severity="info"
              :title="label"
            />
          </div>
        </section>

        <details class="technical-details" @toggle="onTechnicalDetailsToggle">
          <summary>
            <i class="pi pi-shield" aria-hidden="true"></i> Technical details and provenance
          </summary>

          <section
            v-if="axisInventoryCards.length || axisInventoryLoading || axisInventoryError"
            class="axis-inventory"
            aria-label="Dataset dimensions and axis sets"
          >
            <div class="axis-inventory-header">
              <div>
                <h4 class="panel-title">Dimensions and axis sets</h4>
                <p>Complete typed coordinates, labels, class schemes, and include masks.</p>
              </div>
              <Tag
                v-if="axisInventoryShape.length"
                :value="axisInventoryShape.join(' × ')"
                severity="info"
              />
            </div>
            <p v-if="axisInventoryLoading" class="plot-display-notice" role="status">
              Loading the complete owner-scoped axis inventory…
            </p>
            <p v-if="axisInventoryError" class="sample-table-retrieval-error" role="alert">
              {{ axisInventoryError }}
            </p>
            <div class="axis-inventory-grid">
              <article
                v-for="record in axisInventoryCards"
                :key="record.dimension"
                class="axis-card"
              >
                <div>
                  <strong>Dimension {{ record.dimension }} · {{ record.role }}</strong>
                  <span
                    >{{ record.axis.axis_class || "AxisInfo" }} ·
                    {{ record.length }} positions</span
                  >
                </div>
                <p
                  v-if="record.state.kind === 'invalid'"
                  class="sample-table-retrieval-error"
                  role="alert"
                >
                  {{ record.state.message }}
                </p>
                <dl v-else-if="record.state.kind === 'valid'">
                  <dt>Coordinate scales</dt>
                  <dd>{{ record.state.scaleOptions.length }}</dd>
                  <dt>Label sets</dt>
                  <dd>{{ record.state.labelOptions.length }}</dd>
                  <dt>Class sets</dt>
                  <dd>{{ record.state.classOptions.length }}</dd>
                  <dt>Included</dt>
                  <dd>
                    {{
                      record.axis.include_mask
                        ? `${record.axis.include_mask.filter(Boolean).length}/${record.length}`
                        : `All ${record.length}`
                    }}
                  </dd>
                </dl>
              </article>
            </div>
          </section>

          <section
            v-if="scientificContextRows.length || scientificDescription"
            class="scientific-context"
            aria-label="Source scientific context and provenance"
          >
            <div>
              <h4 class="panel-title">Source context and provenance</h4>
              <p v-if="scientificDescription">{{ scientificDescription }}</p>
            </div>
            <dl>
              <template v-for="row in scientificContextRows" :key="row.label">
                <dt>{{ row.label }}</dt>
                <dd :class="{ digest: row.label === 'Scientific digest' }">{{ row.value }}</dd>
              </template>
            </dl>
          </section>

          <section
            v-if="collectionState.kind === 'valid'"
            class="collection-identity"
            aria-label="Collection identity"
          >
            <div>
              <strong>Project collection</strong>
              <span>{{ collectionState.fileCount }} exact source files</span>
            </div>
            <code>{{ collectionState.manifestDigest }}</code>
          </section>
          <section
            v-else-if="collectionState.kind === 'invalid'"
            class="sample-table-message error"
            role="alert"
          >
            <i class="pi pi-exclamation-triangle" aria-hidden="true"></i>
            <span>{{ collectionState.message }}</span>
          </section>

          <section
            v-if="sampleTableState.kind === 'valid'"
            class="collection-sample-table"
            aria-label="Collection sample table"
          >
            <div class="collection-sample-table-header">
              <div>
                <h4 class="panel-title">Sample identity</h4>
                <p>Exact typed metadata retained with each spectrum.</p>
              </div>
              <Tag
                :value="`${sampleTableState.complete ? 'Complete' : 'Preview'} · ${sampleTableState.rowCount} rows · ${sampleTableState.columnCount} columns`"
                :severity="sampleTableState.complete ? 'success' : 'warning'"
              />
            </div>
            <div class="collection-sample-table-scroll">
              <table>
                <thead>
                  <tr>
                    <th v-for="column in sampleTableState.visibleColumns" :key="column">
                      {{ formatSampleColumn(column) }}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in sampleTableState.visibleRows" :key="row.index">
                    <td v-for="column in sampleTableState.visibleColumns" :key="column">
                      {{ formatSampleValue(row.values[column]) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="sampleTableState.omissionNote" class="sample-table-omission-note">
              {{ sampleTableState.omissionNote }}
            </p>
            <p v-if="completeSampleTableLoading" class="sample-table-omission-note" role="status">
              Loading the complete owner-scoped sample table…
            </p>
            <p v-if="completeSampleTableError" class="sample-table-retrieval-error" role="alert">
              {{ completeSampleTableError }}
            </p>
          </section>

          <section
            v-else-if="sampleTableState.kind === 'invalid'"
            class="sample-table-message error"
            role="alert"
          >
            <i class="pi pi-exclamation-triangle" aria-hidden="true"></i>
            <span>{{ sampleTableState.message }}</span>
          </section>

          <section class="complete-matrix" aria-label="Source data matrix">
            <div class="complete-matrix-header">
              <div>
                <h4 class="panel-title">Source data matrix</h4>
                <p>Source values shown with their exact sample and feature labels.</p>
              </div>
              <Tag
                v-if="completeMatrix"
                :value="`${completeMatrix.total_rows.toLocaleString()} × ${completeMatrix.total_cols.toLocaleString()}`"
                severity="info"
              />
            </div>
            <p v-if="completeMatrixLoading" class="plot-display-notice" role="status">
              Loading the source matrix…
            </p>
            <p v-if="completeMatrixError" class="sample-table-retrieval-error" role="alert">
              {{ completeMatrixError }}
            </p>
            <DataMatrixGrid v-if="completeMatrix" :matrix="completeMatrix" />
            <p v-if="completeMatrix?.truncated" class="sample-table-omission-note" role="status">
              This source is larger than the browser-safe matrix view; the labels and values shown above are an exact bounded slice.
            </p>
          </section>
        </details>

        <div class="explore-panels">
          <div class="metadata-panel essential-card priority-card">
            <div class="essential-card-heading">
              <span class="essential-card-number">4</span>
              <h4 class="panel-title">{{ metadataPanelTitle }}</h4>
            </div>
            <div class="metadata-table">
              <div class="meta-row">
                <span class="meta-key">Files</span>
                <span class="meta-val">{{ contentsFileCount || 1 }}</span>
              </div>
              <div class="meta-row">
                <span class="meta-key">Samples</span>
                <span class="meta-val">{{
                  (selectedRowIndexes?.length ?? dataStore.fileInfo.n_samples)?.toLocaleString()
                }}</span>
              </div>
              <div class="meta-row">
                <span class="meta-key">Features</span>
                <span class="meta-val">{{ dataStore.fileInfo.n_features?.toLocaleString() }}</span>
              </div>
            </div>
            <details v-if="propertyStats.length" class="metadata-editor-details">
              <summary>Reference properties</summary>
              <PropertyStatsTable :stats="propertyStats" />
            </details>
          </div>

          <DataQualityPanel
            v-if="hasMatrixData"
            :datasetDict="dataStore.fileInfo"
            :selected-row-indexes="selectedRowIndexes"
            :loading="dataStore.fileInfoLoading"
            priority-label="5"
          />
        </div>
      </div>
    </details>
    <details
      v-if="dataStore.fileInfo && isFeatureEnabled('sherpaDataStory')"
      class="focused-dataset-details data-story-details"
    >
      <summary>
        <span>
          <strong>Data Story</strong>
          <small>Optional scientific narrative</small>
        </span>
      </summary>
      <DataStorySection />
    </details>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";
import {
  computed,
  defineComponent,
  h,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
  type VNodeChild,
} from "vue";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Dropdown from "primevue/dropdown";
import InputSwitch from "primevue/inputswitch";
import ProgressSpinner from "primevue/progressspinner";
import Tag from "primevue/tag";
import Textarea from "primevue/textarea";
import Button from "primevue/button";
import api from "@/api/client";
import MemoryAttribution from "@/components/MemoryAttribution.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDataStore, type CatalogDatasetInfo, type DataStoryPropertyStat } from "@/stores/data";
import { useSherpaStore } from "@/stores/sherpa";
import DataQualityPanel from "./DataQualityPanel.vue";
import DatasetAnalysisReadinessCard from "./DatasetAnalysisReadinessCard.vue";
import DataMatrixGrid from "./DataMatrixGrid.vue";
import type { DataMatrixResponse } from "@/stores/data";
import SampleTableEditor, {
  type SampleTableSavePayload,
} from "@/components/data/SampleTableEditor.vue";
import {
  datasetAxisDisplayState,
  PRIMARY_AXIS_SET,
  projectDatasetAxisDisplay,
  type DatasetAxisWire,
} from "@/utils/datasetAxisSets";
import { selectedDatasetRows } from "@/utils/multiDatasetOverlay";
import { getErrorMessage } from "@/utils/errors";
import { retainedInspection } from "@/utils/retainedInspection";
import { shouldReverseFeatureAxis } from "@/utils/plotLabels";
import type { DatasetAnalysisReadiness } from "@/types";

const dataStore = useDataStore();
const sherpaStore = useSherpaStore();
const sampleTableEditorRef = ref<InstanceType<typeof SampleTableEditor> | null>(null);
const sampleTableSaving = ref(false);
const sampleTableSaveError = ref("");
const sampleTableSaveConflict = ref(false);
type SampleTableMessage =
  | {
      kind: "success";
      fileId: number;
      filePath: string;
      targetColumn: string;
      summary: SampleTableSavePayload["summary"];
    }
  | { kind: "error"; text: string };
const sampleTableMessage = ref<SampleTableMessage | null>(null);
const { isFeatureEnabled } = useAppConfig();

function clearSampleTableSaveError(): void {
  sampleTableSaveError.value = "";
  sampleTableSaveConflict.value = false;
}

const props = withDefaults(
  defineProps<{
    activeDatasetName?: string | null;
    selectedFileCount?: number | null;
    selectedFileNames?: string[];
    initialAnalysisTarget?: string;
    initialAnalysisGroup?: string;
    analysisSelectionHydrated?: boolean;
    analysisSelectionStatus?: "loading" | "idle" | "saving" | "saved" | "error";
  }>(),
  {
    activeDatasetName: null,
    selectedFileCount: null,
    selectedFileNames: () => [],
    initialAnalysisTarget: "",
    initialAnalysisGroup: "",
    analysisSelectionHydrated: true,
    analysisSelectionStatus: "idle",
  },
);

type AnalysisChoice = {
  target: string;
  targetType: "categorical" | "continuous" | null;
  targetUnits: string | null;
  sourceDigest: string | null;
  group: string;
  readiness: DatasetAnalysisReadiness | null;
};

const emit = defineEmits<{
  analysisChoice: [choice: AnalysisChoice];
  analysisSelectionCommit: [choice: AnalysisChoice];
  measuredSamplesPublished: [];
}>();
const selectedFileNames = computed(() =>
  props.selectedFileNames.map((name) => extractFileName(name)),
);

function formatSavedTargets(
  targets: SampleTableSavePayload["summary"]["targetColumns"],
  valueCounts: SampleTableSavePayload["summary"]["targetValueCounts"],
): string {
  return targets
    .map((target) => `${target.name} (${target.type}; ${valueCounts[target.name] ?? 0} values)`)
    .join(", ");
}

const PLOT_COLORS = [
  "#3b82f6",
  "#ef4444",
  "#22c55e",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
  "#06b6d4",
  "#f97316",
  "#14b8a6",
  "#6366f1",
  "#e11d48",
  "#84cc16",
  "#0ea5e9",
  "#d946ef",
  "#a3e635",
  "#2dd4bf",
  "#fb923c",
  "#818cf8",
  "#f472b6",
  "#34d399",
];
const MAX_SAMPLE_TABLE_ROWS = 100;
const MAX_SAMPLE_TABLE_COLUMNS = 24;
const SAMPLE_LABEL_PREVIEW_COUNT = 12;

const xTitleOptions = [
  "Wavenumber",
  "Wavelength",
  "Raman Shift",
  "m/z",
  "Time",
  "Energy",
  "Channel",
  "Index",
];
const xUnitsMap: Record<string, string[]> = {
  Wavenumber: ["cm\u207B\u00B9"],
  Wavelength: ["nm", "\u00B5m"],
  "Raman Shift": ["cm\u207B\u00B9"],
  "m/z": ["Da", "Th"],
  Time: ["s", "min", "h"],
  Energy: ["eV", "keV"],
  Channel: [""],
  Index: [""],
};
const yTitleOptions = ["Intensity", "Absorbance", "Transmittance", "Reflectance", "Response"];

const editXTitle = ref("");
const editXUnits = ref("");
const editYTitle = ref("");
const isTimeSeriesToggle = ref(false);
const targetMode = ref<"single" | "multi">("single");
const selectedTarget = ref("");
const selectedFeatureScale = ref(PRIMARY_AXIS_SET);
const selectedFeatureLabels = ref(PRIMARY_AXIS_SET);
const selectedFeatureTitle = ref(PRIMARY_AXIS_SET);
const selectedSampleLabels = ref(PRIMARY_AXIS_SET);
const sampleLabelsExpanded = ref(false);

type AxisInventoryPayload = {
  schema_version: "spectrasherpa-dataset-axis-inventory/1";
  dataset_id: string;
  scientific_projection_schema: string;
  scientific_digest: string;
  shape: number[];
  axes: Array<{ dimension: number; axis: DatasetAxisWire }>;
};

const axisInventory = ref<AxisInventoryPayload | null>(null);
const axisInventoryLoading = ref(false);
const axisInventoryError = ref<string | null>(null);
let axisInventoryRequest = 0;

const completeMatrix = ref<DataMatrixResponse | null>(null);
const completeMatrixLoading = ref(false);
const completeMatrixError = ref<string | null>(null);
let completeMatrixRequest = 0;
const technicalDetailsOpen = ref(false);

async function loadCompleteMatrix(): Promise<void> {
  if (completeMatrix.value || completeMatrixLoading.value) return;
  const experimentId = dataStore.activeExperimentId;
  const fileId = dataStore.activeFileId;
  if (experimentId == null || fileId == null) {
    completeMatrixError.value = "Select one source file to inspect its data matrix.";
    return;
  }
  const request = ++completeMatrixRequest;
  completeMatrixLoading.value = true;
  completeMatrixError.value = null;
  try {
    const matrix = await dataStore.fetchDataMatrix({
      kind: "experiment_file",
      experiment_id: experimentId,
      file_id: fileId,
    });
    if (request === completeMatrixRequest) completeMatrix.value = matrix;
  } catch (error: unknown) {
    if (request === completeMatrixRequest) {
      completeMatrixError.value = getErrorMessage(error, "The source data matrix could not be loaded.");
    }
  } finally {
    if (request === completeMatrixRequest) completeMatrixLoading.value = false;
  }
}

async function onTechnicalDetailsToggle(event: Event): Promise<void> {
  technicalDetailsOpen.value = (event.target as HTMLDetailsElement).open;
  if (!technicalDetailsOpen.value) return;
  await loadCompleteMatrix();
}

watch(
  () => [dataStore.activeExperimentId, dataStore.activeFileId, dataStore.fileInfo] as const,
  () => {
    completeMatrixRequest += 1;
    completeMatrix.value = null;
    completeMatrixError.value = null;
    completeMatrixLoading.value = false;
    if (dataStore.fileInfo && dataStore.activeFileId != null &&
        (technicalDetailsOpen.value || !dataStore.fileInfo.data?.length)) {
      void loadCompleteMatrix();
    }
  },
  { immediate: true },
);

const xUnitsOptions = computed(() => {
  const units = xUnitsMap[editXTitle.value];
  if (units) return units.filter((u) => u !== "");
  return [];
});

const contentsFileCount = computed(() => {
  if (props.selectedFileCount != null) return props.selectedFileCount;
  const metadata = dataStore.fileInfo?.metadata as Record<string, unknown> | undefined;
  const count = metadata?.contents_file_count;
  return typeof count === "number" && Number.isFinite(count)
    ? count
    : dataStore.activeFileId
      ? 1
      : null;
});

const contentsTitle = computed(() => {
  if (props.activeDatasetName?.trim()) return props.activeDatasetName.trim();
  const metadata = dataStore.fileInfo?.metadata as Record<string, unknown> | undefined;
  const title = metadata?.contents_title;
  if (typeof title === "string" && title.trim()) return title;
  if (dataStore.activeFilePath) return extractFileName(dataStore.activeFilePath);
  return dataStore.fileInfo?.title || "Dataset contents";
});

const metadataPanelTitle = computed(() => "Active Dataset Metadata");

const sampleLabels = computed(() => {
  const axisLabels = dataStore.fileInfo?.y_axis?.labels;
  if (Array.isArray(axisLabels) && axisLabels.every((value) => typeof value === "string")) {
    return selectedRows([...axisLabels]);
  }
  const metadata = dataStore.fileInfo?.metadata as Record<string, unknown> | undefined;
  const raw = metadata?.labels ?? metadata?.sample_labels;
  return Array.isArray(raw) ? raw.map((value) => String(value)) : [];
});

const visibleSampleLabels = computed(() =>
  sampleLabelsExpanded.value
    ? sampleLabels.value
    : sampleLabels.value.slice(0, SAMPLE_LABEL_PREVIEW_COUNT),
);

type AcquisitionSetting = { label: string; value: string; detail?: string };

function displaySettingValues(values: unknown[]): string | null {
  const normalized = values
    .flatMap((value) => (Array.isArray(value) ? value : [value]))
    .filter((value) => value !== null && value !== undefined && String(value).trim())
    .map((value) => String(value));
  const unique = [...new Set(normalized)];
  if (!unique.length) return null;
  if (unique.length === 1) return unique[0];
  return `${unique.length} values across the selected files`;
}

function formatAxisCoordinate(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value ?? "");
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

const acquisitionSettings = computed<AcquisitionSetting[]>(() => {
  const fileInfo = dataStore.fileInfo;
  if (!fileInfo) return [];
  const metadata = isRecord(fileInfo.metadata) ? fileInfo.metadata : {};
  const domain = isRecord(fileInfo.domain) ? fileInfo.domain : {};
  const selectedNames = new Set(props.selectedFileNames.map((name) => extractFileName(name)));
  const memberMetadata = Array.isArray(metadata.source_member_metadata)
    ? metadata.source_member_metadata
        .filter(isRecord)
        .filter((member) => {
          if (!selectedNames.size) return true;
          const nested = isRecord(member.metadata) ? member.metadata : {};
          const source = member.file_name ?? member.source_file ?? nested.source_file;
          return typeof source !== "string" || selectedNames.has(extractFileName(source));
        })
        .map((member) => (isRecord(member.metadata) ? member.metadata : {}))
    : [];
  const acquisitionRecords = [metadata, ...memberMetadata]
    .map((record) => record["omnic.acquisition"])
    .filter(isRecord);
  const rows: AcquisitionSetting[] = [];
  const add = (label: string, value: unknown, detail?: string): void => {
    if (value !== null && value !== undefined && String(value).trim()) {
      rows.push({ label, value: String(value), detail });
    }
  };
  add("Instrument", domain.instrument);
  add("Technique", domain.technique);
  add("Measurement", domain.data_quantity);
  const featureValues = featureAxisDisplay.value?.values ?? [];
  if (featureValues.length) {
    const first = featureValues[0];
    const last = featureValues[featureValues.length - 1];
    add(
      "Spectral range",
      `${formatAxisCoordinate(first)} – ${formatAxisCoordinate(last)}${
        featureAxisDisplay.value?.units ? ` ${featureAxisDisplay.value.units}` : ""
      }`,
    );
    add("Points per spectrum", featureValues.length);
  }
  const scanCounts = displaySettingValues(acquisitionRecords.map((record) => record.scan_count));
  const backgroundCounts = displaySettingValues(
    acquisitionRecords.map((record) => record.background_scan_count),
  );
  if (scanCounts) add("Sample scans", scanCounts);
  if (backgroundCounts) add("Background scans", backgroundCounts);
  const acquired = displaySettingValues(
    acquisitionRecords.flatMap((record) =>
      Array.isArray(record.acquired_at) ? record.acquired_at : [record.acquired_at],
    ),
  );
  if (acquired) add("Acquired", acquired);
  return rows;
});

const featureAxisState = computed(() =>
  datasetAxisDisplayState(dataStore.fileInfo?.x_axis, dataStore.fileInfo?.n_features),
);

const sampleAxisState = computed(() => {
  const rows = dataStore.fileInfo?.data?.length || dataStore.fileInfo?.n_samples;
  return datasetAxisDisplayState(dataStore.fileInfo?.y_axis, rows);
});

const featureAxisDisplay = computed(() =>
  projectDatasetAxisDisplay(
    featureAxisState.value,
    selectedFeatureScale.value,
    selectedFeatureLabels.value,
    selectedFeatureTitle.value,
  ),
);

const sampleAxisDisplay = computed(() =>
  projectDatasetAxisDisplay(
    sampleAxisState.value,
    PRIMARY_AXIS_SET,
    selectedSampleLabels.value,
    PRIMARY_AXIS_SET,
  ),
);

const displaySampleLabels = computed(() => {
  const projected = sampleAxisDisplay.value?.labels;
  return projected?.length === (dataStore.fileInfo?.data?.length ?? 0)
    ? projected
    : sampleLabels.value;
});

function preserveAxisChoice(current: { value: string }, options: Array<{ value: string }>): void {
  if (options.length && !options.some((option) => option.value === current.value)) {
    current.value = options[0].value;
  }
}

watch(
  [featureAxisState, sampleAxisState],
  ([feature, sample]) => {
    if (feature.kind === "valid") {
      preserveAxisChoice(selectedFeatureScale, feature.scaleOptions);
      preserveAxisChoice(selectedFeatureLabels, feature.labelOptions);
      preserveAxisChoice(selectedFeatureTitle, feature.titleOptions);
    }
    if (sample.kind === "valid") preserveAxisChoice(selectedSampleLabels, sample.labelOptions);
  },
  { immediate: true },
);

type ValidSampleTable = {
  kind: "valid";
  complete: boolean;
  totalRowCount: number;
  rowCount: number;
  columnCount: number;
  values: Record<string, unknown[]>;
  visibleColumns: string[];
  visibleRows: Array<{ index: number; values: Record<string, unknown> }>;
  omissionNote: string | null;
};
type SampleTableState =
  | { kind: "absent" }
  | { kind: "invalid"; message: string }
  | ValidSampleTable;
type CollectionState =
  | { kind: "absent" }
  | { kind: "invalid"; message: string }
  | {
      kind: "valid";
      fileCount: number;
      manifestDigest: string;
      scientificIdentity: {
        schemaVersion: string;
        sourceManifestDigest: string;
        definitionDigest: string | null;
        datasetProjectionDigest: string | null;
        scientificDigest: string;
      } | null;
    };
type CompleteSampleTablePayload = {
  schema_version: string;
  complete: true;
  row_count: number;
  columns: string[];
  labels: string[];
  sample_table: Record<string, unknown[]>;
  source_collection: {
    schema_version: string;
    file_count: number;
    manifest_digest: string;
    scientific_collection_schema_version?: string;
    source_manifest_sha256?: string;
    collection_definition_sha256?: string | null;
    scientific_dataset_projection_sha256?: string;
    scientific_collection_sha256?: string;
  };
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

const collectionState = computed<CollectionState>(() => {
  const metadata = dataStore.fileInfo?.metadata;
  if (!isRecord(metadata) || !("source_collection" in metadata)) return { kind: "absent" };
  if (!isRecord(metadata.source_collection)) {
    return { kind: "invalid", message: "The project collection identity is malformed." };
  }
  const source = metadata.source_collection;
  const fileCount = source.file_count;
  const manifestDigest = source.manifest_digest;
  const files = source.files;
  if (
    source.schema_version !== "spectrasherpa-source-collection/1" ||
    !Number.isInteger(fileCount) ||
    Number(fileCount) < 1 ||
    typeof manifestDigest !== "string" ||
    !/^[0-9a-f]{64}$/.test(manifestDigest) ||
    !Array.isArray(files) ||
    files.length !== Number(fileCount)
  ) {
    return {
      kind: "invalid",
      message: "The project collection identity is incomplete or unsupported.",
    };
  }
  for (const file of files) {
    if (
      !isRecord(file) ||
      typeof file.file_name !== "string" ||
      !file.file_name ||
      !Number.isInteger(file.size_bytes) ||
      Number(file.size_bytes) < 0 ||
      typeof file.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(file.sha256) ||
      typeof file.prepared_data_sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(file.prepared_data_sha256)
    ) {
      return { kind: "invalid", message: "A project collection source identity is malformed." };
    }
  }
  const baseIdentityFields = [
    "scientific_collection_schema_version",
    "source_manifest_sha256",
    "collection_definition_sha256",
    "scientific_collection_sha256",
  ];
  const baseIdentityCount = baseIdentityFields.filter((field) => field in source).length;
  if (baseIdentityCount !== 0 && baseIdentityCount !== baseIdentityFields.length) {
    return {
      kind: "invalid",
      message: "The project scientific collection identity is incomplete.",
    };
  }
  let scientificIdentity: Extract<CollectionState, { kind: "valid" }>["scientificIdentity"] = null;
  if (baseIdentityCount === baseIdentityFields.length) {
    const definitionDigest = source.collection_definition_sha256;
    const projectionDigest = source.scientific_dataset_projection_sha256;
    const isDefined = definitionDigest !== null;
    if (
      source.scientific_collection_schema_version !==
        (isDefined
          ? "spectrasherpa-scientific-collection/2"
          : "spectrasherpa-scientific-collection/1") ||
      source.source_manifest_sha256 !== manifestDigest ||
      (definitionDigest !== null &&
        (typeof definitionDigest !== "string" || !/^[0-9a-f]{64}$/.test(definitionDigest))) ||
      (isDefined
        ? typeof projectionDigest !== "string" || !/^[0-9a-f]{64}$/.test(projectionDigest)
        : projectionDigest !== undefined) ||
      typeof source.scientific_collection_sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(source.scientific_collection_sha256)
    ) {
      return {
        kind: "invalid",
        message: "The project scientific collection identity is malformed.",
      };
    }
    scientificIdentity = {
      schemaVersion: source.scientific_collection_schema_version as string,
      sourceManifestDigest: source.source_manifest_sha256,
      definitionDigest: definitionDigest as string | null,
      datasetProjectionDigest: isDefined ? (projectionDigest as string) : null,
      scientificDigest: source.scientific_collection_sha256,
    };
  }
  return { kind: "valid", fileCount: Number(fileCount), manifestDigest, scientificIdentity };
});

const completeSampleTablePayload = ref<CompleteSampleTablePayload | null>(null);
const completeSampleTableLoading = ref(false);
const completeSampleTableError = ref<string | null>(null);
let completeSampleTableRequest = 0;

function apiSerializationMetadata(): Record<string, unknown> | null {
  const metadata = dataStore.fileInfo?.metadata;
  if (!isRecord(metadata) || !isRecord(metadata.api_serialization)) return null;
  return metadata.api_serialization;
}

function retainedDatasetHandle(fileInfo: Record<string, unknown>): string | null {
  const direct = fileInfo.dataset_id;
  if (typeof direct === "string" && direct) return direct;
  const handle = apiSerializationMetadata()?.full_dataset_handle;
  return typeof handle === "string" && handle ? handle : null;
}

function requiresCompleteAxisInventory(fileInfo: Record<string, unknown>): boolean {
  const shape = Array.isArray(fileInfo.shape) ? fileInfo.shape : [];
  if (shape.length > 2 || apiSerializationMetadata()?.mode === "handle_only") return true;
  const axes = [
    fileInfo.x_axis,
    fileInfo.y_axis,
    ...Object.values((fileInfo.inner_axes as object) ?? {}),
  ];
  return axes.some(
    (axis) =>
      isRecord(axis) &&
      [
        axis.alternate_scales,
        axis.alternate_label_sets,
        axis.alternate_title_sets,
        axis.class_sets,
      ].some((sets) => Array.isArray(sets) && sets.length > 0),
  );
}

function validateAxisInventory(value: unknown, expectedHandle: string): AxisInventoryPayload {
  if (!isRecord(value) || value.schema_version !== "spectrasherpa-dataset-axis-inventory/1") {
    throw new Error("The complete dataset-axis inventory is malformed or unsupported.");
  }
  if (
    value.dataset_id !== expectedHandle ||
    typeof value.scientific_projection_schema !== "string" ||
    typeof value.scientific_digest !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.scientific_digest) ||
    !Array.isArray(value.shape) ||
    !value.shape.every((item) => Number.isSafeInteger(item) && Number(item) > 0) ||
    !Array.isArray(value.axes) ||
    value.axes.length < 2 ||
    value.axes.length > 16
  ) {
    throw new Error("The complete dataset-axis inventory has an invalid identity or shape.");
  }
  const shape = value.shape as number[];
  const dimensions = new Set<number>();
  for (const rawRecord of value.axes) {
    if (
      !isRecord(rawRecord) ||
      !Number.isSafeInteger(rawRecord.dimension) ||
      !isRecord(rawRecord.axis)
    ) {
      throw new Error("The complete dataset-axis inventory contains a malformed dimension.");
    }
    const dimension = Number(rawRecord.dimension);
    if (dimension < 0 || dimension >= shape.length || dimensions.has(dimension)) {
      throw new Error("The complete dataset-axis inventory contains an ambiguous dimension.");
    }
    dimensions.add(dimension);
    if (datasetAxisDisplayState(rawRecord.axis, shape[dimension]).kind !== "valid") {
      throw new Error("The complete dataset-axis inventory contains malformed aligned metadata.");
    }
  }
  const manifest = dataStore.fileInfo?.manifest;
  if (
    isRecord(manifest) &&
    ((typeof manifest.scientific_digest === "string" &&
      manifest.scientific_digest !== value.scientific_digest) ||
      (typeof manifest.scientific_projection_schema === "string" &&
        manifest.scientific_projection_schema !== value.scientific_projection_schema))
  ) {
    throw new Error("The complete dataset-axis inventory does not match the inspected dataset.");
  }
  return value as AxisInventoryPayload;
}

watch(
  () => dataStore.fileInfo,
  async (fileInfo) => {
    const request = ++axisInventoryRequest;
    axisInventory.value = null;
    axisInventoryError.value = null;
    axisInventoryLoading.value = false;
    if (!fileInfo) return;
    const record = fileInfo as unknown as Record<string, unknown>;
    if (!requiresCompleteAxisInventory(record)) return;
    const handle = retainedDatasetHandle(record);
    if (!handle) return;
    axisInventoryLoading.value = true;
    try {
      const data = await retainedInspection(
        fileInfo,
        `axes:${handle}`,
        async () => (await api.get(`/datasets/${encodeURIComponent(handle)}/axes`)).data,
      );
      const admitted = validateAxisInventory(data, handle);
      if (request === axisInventoryRequest) axisInventory.value = admitted;
    } catch (error: unknown) {
      if (request === axisInventoryRequest) {
        axisInventoryError.value =
          error instanceof Error ? error.message : "Failed to retrieve complete dataset axes.";
      }
    } finally {
      if (request === axisInventoryRequest) axisInventoryLoading.value = false;
    }
  },
  { immediate: true },
);

const axisInventoryRecords = computed(() => {
  if (axisInventory.value) return axisInventory.value.axes;
  const fileInfo = dataStore.fileInfo;
  if (!fileInfo) return [];
  const shape = fileInfo.shape ?? [fileInfo.n_samples, fileInfo.n_features];
  const records: Array<{ dimension: number; axis: DatasetAxisWire }> = [];
  const sample = fileInfo.sample_axis ?? fileInfo.y_axis;
  if (sample) records.push({ dimension: 0, axis: sample });
  for (const [dimension, axis] of Object.entries(fileInfo.inner_axes ?? {})) {
    if (/^(?:0|[1-9][0-9]*)$/.test(dimension)) records.push({ dimension: Number(dimension), axis });
  }
  if (fileInfo.x_axis && shape.length > 1) {
    records.push({ dimension: shape.length - 1, axis: fileInfo.x_axis });
  }
  return records.sort((left, right) => left.dimension - right.dimension);
});

const axisInventoryShape = computed(
  () =>
    axisInventory.value?.shape ??
    dataStore.fileInfo?.shape ?? [dataStore.fileInfo?.n_samples, dataStore.fileInfo?.n_features],
);

const axisInventoryCards = computed(() =>
  axisInventoryRecords.value.map((record) => {
    const length = Number(axisInventoryShape.value[record.dimension] ?? 0);
    const state = datasetAxisDisplayState(record.axis, length || undefined);
    return {
      ...record,
      length,
      state,
      role:
        record.dimension === 0
          ? "Samples"
          : record.dimension === axisInventoryShape.value.length - 1
            ? "Features"
            : `Inner mode ${record.dimension}`,
    };
  }),
);

const scientificContextRows = computed(() => {
  const fileInfo = dataStore.fileInfo;
  if (!fileInfo) return [];
  const descriptive = isRecord(fileInfo.descriptive) ? fileInfo.descriptive : {};
  const source = isRecord(fileInfo.source_identity) ? fileInfo.source_identity : {};
  const history = isRecord(fileInfo.source_history) ? fileInfo.source_history : {};
  const layout = isRecord(fileInfo.layout) ? fileInfo.layout : {};
  const manifest = isRecord(fileInfo.manifest) ? fileInfo.manifest : {};
  const rows: Array<{ label: string; value: string }> = [];
  const add = (label: string, value: unknown): void => {
    if (typeof value === "string" && value) rows.push({ label, value });
  };
  add("Source format", source.source_format);
  add("Source object", source.object_name);
  add("Source version", source.dataset_version ?? source.storage_version);
  if (Array.isArray(descriptive.authors) && descriptive.authors.length) {
    rows.push({ label: "Authors", value: descriptive.authors.join(", ") });
  }
  add("Created", descriptive.created_at);
  add("Modified", descriptive.modified_at);
  add("Layout", layout.kind);
  if (Array.isArray(layout.source_shape)) {
    rows.push({ label: "Source shape", value: layout.source_shape.join(" × ") });
  }
  if (Array.isArray(layout.mode_roles) && layout.mode_roles.length) {
    rows.push({ label: "Mode roles", value: layout.mode_roles.join(" · ") });
  }
  if (Array.isArray(history.entries)) {
    rows.push({ label: "Source history", value: `${history.entries.length} retained entries` });
  }
  add("Storage order", history.storage_order);
  add("Scientific digest", manifest.scientific_digest);
  return rows;
});

const scientificDescription = computed(() => {
  const value = dataStore.fileInfo?.descriptive?.description;
  return typeof value === "string" && value ? value : null;
});

watch(
  () => dataStore.fileInfo,
  async (fileInfo) => {
    const request = ++completeSampleTableRequest;
    completeSampleTablePayload.value = null;
    completeSampleTableError.value = null;
    completeSampleTableLoading.value = false;
    if (!fileInfo || apiSerializationMetadata()?.mode !== "bounded_preview") return;
    if (collectionState.value.kind !== "valid") return;
    const handle = retainedDatasetHandle(fileInfo as unknown as Record<string, unknown>);
    if (!handle) {
      completeSampleTableError.value =
        "Only an aligned API preview is available; the complete table handle was not retained.";
      return;
    }
    completeSampleTableLoading.value = true;
    try {
      const data = await retainedInspection(
        fileInfo,
        `sample-table:${handle}`,
        async () => (await api.get(`/datasets/${encodeURIComponent(handle)}/sample-table`)).data,
      );
      if (request === completeSampleTableRequest) {
        completeSampleTablePayload.value = data as CompleteSampleTablePayload;
      }
    } catch {
      if (request === completeSampleTableRequest) {
        completeSampleTableError.value =
          "Only an aligned API preview is shown. The complete owner-scoped table could not be retrieved within its 10,000-row and 4 MiB limits.";
      }
    } finally {
      if (request === completeSampleTableRequest) completeSampleTableLoading.value = false;
    }
  },
  { immediate: true },
);

function buildSampleTableState(
  raw: unknown,
  labels: unknown,
  rowCount: number,
  totalRowCount: number,
  complete: boolean,
): SampleTableState {
  if (raw == null) {
    return collectionState.value.kind === "valid"
      ? { kind: "invalid", message: "The project collection has no typed sample table." }
      : { kind: "absent" };
  }
  if (!isRecord(raw) || Object.keys(raw).length === 0) {
    return { kind: "invalid", message: "The retained sample table is empty or malformed." };
  }
  const exactLabels =
    Array.isArray(labels) &&
    labels.length === rowCount &&
    labels.every((value) => typeof value === "string");
  const labelValues = exactLabels ? (labels as string[]) : [];
  if (collectionState.value.kind === "valid" && !exactLabels) {
    return {
      kind: "invalid",
      message: "The retained sample labels do not match the visible spectra.",
    };
  }
  const columns = Object.keys(raw);
  const values: Record<string, unknown[]> = {};
  for (const column of columns) {
    const columnValues = raw[column];
    if (!Array.isArray(columnValues) || columnValues.length !== rowCount) {
      return {
        kind: "invalid",
        message: `Sample-table column ${column} does not match the ${rowCount} retained spectra. Plot grouping is disabled.`,
      };
    }
    if (!columnValues.every(isLosslessSampleTableScalar)) {
      return {
        kind: "invalid",
        message: `Sample-table column ${column} contains a structured, non-finite, or non-lossless value. Plot grouping is disabled.`,
      };
    }
    values[column] = columnValues;
  }
  if (collectionState.value.kind === "valid") {
    // Axis labels are the collection row-identity authority. A native
    // collection does not need to duplicate them in a sample_id column.
    // When sample_id is supplied, it must still agree exactly.
    if (values.sample_id) {
      for (let index = 0; index < rowCount; index += 1) {
        if (
          typeof values.sample_id[index] !== "string" ||
          values.sample_id[index] !== labelValues[index]
        ) {
          return {
            kind: "invalid",
            message: `Sample-table identity at row ${index + 1} does not match its retained spectrum label.`,
          };
        }
      }
    }
  }
  const visibleColumns = columns.slice(0, MAX_SAMPLE_TABLE_COLUMNS);
  const visibleRowCount = Math.min(rowCount, MAX_SAMPLE_TABLE_ROWS);
  const visibleRows = Array.from({ length: visibleRowCount }, (_, index) => ({
    index,
    values: Object.fromEntries(visibleColumns.map((column) => [column, values[column][index]])),
  }));
  const omitted: string[] = [];
  if (columns.length > visibleColumns.length) {
    omitted.push(`${columns.length - visibleColumns.length} additional columns`);
  }
  if (rowCount > visibleRowCount) omitted.push(`${rowCount - visibleRowCount} additional rows`);
  if (!complete)
    omitted.push(`${totalRowCount - rowCount} rows available through the complete table`);
  return {
    kind: "valid",
    complete,
    totalRowCount,
    rowCount,
    columnCount: columns.length,
    values,
    visibleColumns,
    visibleRows,
    omissionNote: omitted.length ? `Preview omits ${omitted.join(" and ")}.` : null,
  };
}

const selectedRowIndexes = computed<number[] | null>(() => {
  const fileInfo = dataStore.fileInfo;
  if (!fileInfo) return null;
  if (props.selectedFileNames.length === 0) return null;
  // Exact view selection now triggers a server-side reinspection of that
  // scope. When its source manifest already contains exactly the selected
  // files, every returned row is selected; filtering those rows a second time
  // by display filenames can erase valid provider annotations whose internal
  // source name differs from the retained Data View name.
  if (
    collectionState.value.kind === "valid" &&
    collectionState.value.fileCount === props.selectedFileNames.length
  ) {
    return null;
  }
  const selected = new Set(props.selectedFileNames.map((name) => extractFileName(name)));
  // A file-path preview already contains only this file's rows. Provider
  // specimen labels need not encode the imported file's display name.
  if (
    fileInfo.metadata?.contents_file_count === 1 &&
    selected.size === 1 &&
    dataStore.activeFilePath &&
    selected.has(extractFileName(dataStore.activeFilePath))
  ) {
    return null;
  }
  // Only filter when retained row identities prove the requested file scope.
  // Provider sample labels are not necessarily imported filenames.
  return selectedDatasetRows(fileInfo, props.selectedFileNames);
});

function selectedRows<T>(values: T[]): T[] {
  const indexes = selectedRowIndexes.value;
  return indexes ? indexes.map((index) => values[index]) : values;
}

function selectedSampleTable(raw: unknown): unknown {
  if (!isRecord(raw) || selectedRowIndexes.value === null) return raw;
  return Object.fromEntries(
    Object.entries(raw).map(([column, values]) => [
      column,
      Array.isArray(values) ? selectedRows(values) : values,
    ]),
  );
}

const wireSampleTableState = computed<SampleTableState>(() => {
  const fileInfo = dataStore.fileInfo;
  if (!fileInfo) return { kind: "absent" };
  const mode = apiSerializationMetadata()?.mode;
  const complete = mode !== "bounded_preview";
  let rowCount = fileInfo.n_samples ?? 0;
  if (!complete) {
    const metadata = fileInfo.metadata;
    const previewShape = isRecord(metadata) ? metadata.preview_shape : null;
    if (
      !Array.isArray(previewShape) ||
      !Number.isInteger(previewShape[0]) ||
      Number(previewShape[0]) < 1
    ) {
      return { kind: "invalid", message: "The bounded API preview has no exact row projection." };
    }
    rowCount = Number(previewShape[0]);
  }
  const labels = Array.isArray(fileInfo.y_axis?.labels)
    ? selectedRows(fileInfo.y_axis.labels)
    : fileInfo.y_axis?.labels;
  const selectedCount = selectedRowIndexes.value?.length ?? rowCount;
  return buildSampleTableState(
    selectedSampleTable(fileInfo.y_axis?.sample_table),
    labels,
    selectedCount,
    selectedCount,
    complete,
  );
});

const sampleTableState = computed<SampleTableState>(() => {
  const payload = completeSampleTablePayload.value;
  if (!payload) return wireSampleTableState.value;
  const payloadScientificIdentity = payload.source_collection.scientific_collection_sha256;
  const expectedScientificIdentity =
    collectionState.value.kind === "valid" ? collectionState.value.scientificIdentity : null;
  if (
    payload.schema_version !== "spectrasherpa-collection-sample-table/1" ||
    payload.complete !== true ||
    !Number.isInteger(payload.row_count) ||
    payload.row_count !== dataStore.fileInfo?.n_samples ||
    !Array.isArray(payload.columns) ||
    !isRecord(payload.source_collection) ||
    collectionState.value.kind !== "valid" ||
    payload.source_collection.schema_version !== "spectrasherpa-source-collection/1" ||
    payload.source_collection.file_count !== collectionState.value.fileCount ||
    payload.source_collection.manifest_digest !== collectionState.value.manifestDigest ||
    (expectedScientificIdentity !== null &&
      (payload.source_collection.scientific_collection_schema_version !==
        expectedScientificIdentity.schemaVersion ||
        payload.source_collection.source_manifest_sha256 !==
          expectedScientificIdentity.sourceManifestDigest ||
        payload.source_collection.collection_definition_sha256 !==
          expectedScientificIdentity.definitionDigest ||
        (expectedScientificIdentity.datasetProjectionDigest !== null
          ? payload.source_collection.scientific_dataset_projection_sha256 !==
            expectedScientificIdentity.datasetProjectionDigest
          : payload.source_collection.scientific_dataset_projection_sha256 !== undefined) ||
        payloadScientificIdentity !== expectedScientificIdentity.scientificDigest)) ||
    (expectedScientificIdentity === null && payloadScientificIdentity !== undefined) ||
    !isRecord(payload.sample_table) ||
    Object.keys(payload.sample_table).length !== payload.columns.length ||
    payload.columns.some(
      (column) => typeof column !== "string" || !(column in payload.sample_table),
    )
  ) {
    return {
      kind: "invalid",
      message: "The retrieved complete sample table failed identity validation.",
    };
  }
  const labels = selectedRows(payload.labels);
  const selectedCount = selectedRowIndexes.value?.length ?? payload.row_count;
  return buildSampleTableState(
    selectedSampleTable(payload.sample_table),
    labels,
    selectedCount,
    selectedCount,
    true,
  );
});

type AnalysisTargetOption = {
  label: string;
  value: string;
  type: "categorical" | "continuous" | null;
  detail: string;
  disabled?: boolean;
};

type AnalysisGroupOption = {
  label: string;
  value: string;
  detail: string;
  disabled?: boolean;
};

const TARGET_FIELD_EXCLUSIONS = new Set([
  "sample_id",
  "curated_filename",
  "curated_sha256",
  "canonical_omnic_title",
  "acquired_at",
  "acquisition_order",
  "analysis_role",
  "evidence_status",
  "evidence_citation_id",
  "label_status",
]);
const GROUP_FIELD_NAMES = new Set(["block", "batch", "group", "instrument", "replicate_group"]);

const analysisTarget = ref("");
const analysisGroup = ref("");

function distinctValues(values: unknown[]): unknown[] {
  const seen = new Set<string>();
  const result: unknown[] = [];
  for (const value of values) {
    if (value == null || String(value).trim() === "") continue;
    const key = `${typeof value}:${String(value)}`;
    if (!seen.has(key)) {
      seen.add(key);
      result.push(value);
    }
  }
  return result;
}

function nonEmptyCount(values: unknown[]): number {
  let count = 0;
  for (const value of values) {
    if (value == null || String(value).trim() === "") continue;
    count += 1;
  }
  return count;
}

function analysisFieldLabel(name: string): string {
  const preferred: Record<string, string> = {
    specimen_id: "Specimen Identity",
    claimed_botanical_group: "Claimed Botanical Group",
    author_reported_authenticity_status: "Authenticity Status",
    block: "Blocks",
  };
  if (preferred[name]) return preferred[name];
  return name
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function completeSampleColumnValues(column: string): unknown[] {
  const completeValues = completeSampleTablePayload.value?.sample_table?.[column];
  if (Array.isArray(completeValues)) return completeValues;
  const sourceTable = dataStore.fileInfo?.y_axis?.sample_table;
  if (!isRecord(sourceTable)) return [];
  const sourceValues = sourceTable[column];
  return Array.isArray(sourceValues) ? sourceValues : [];
}

const analysisTargetOptions = computed<AnalysisTargetOption[]>(() => {
  const options: AnalysisTargetOption[] = [
    {
      label: "None",
      value: "",
      type: null,
      detail: "No response or class target.",
      disabled: false,
    },
  ];
  const table = sampleTableState.value;
  if (table.kind !== "valid") {
    const profile = dataStore.fileInfo?.analysis_readiness?.profile;
    for (const field of profile?.target_fields ?? []) {
      options.push({
        label: analysisFieldLabel(field),
        value: field,
        type: profile?.target_type === "continuous" ? "continuous" : "categorical",
        detail: `Admitted ${profile?.target_type ?? "target"} field.`,
        disabled: false,
      });
    }
    return options;
  }
  // The analysis profile is the authority for what may be a target. An identity
  // column is a per-row label, so fitting against one usually asks a model to
  // predict the name of the row it was handed -- corn offers 80 specimen ids
  // across 80 rows. But an identity that repeats can be a real question: the
  // Lavender corpus declares specimen_id a target because 11 specimens appear
  // across 3 acquisition blocks. So withhold identity columns unless this
  // dataset's profile declares them, rather than judging it from a local list.
  const profileFields = dataStore.fileInfo?.analysis_readiness?.profile;
  const identityFields = new Set(profileFields?.identity_fields ?? []);
  const declaredTargetFields = new Set(profileFields?.target_fields ?? []);
  for (const column of table.visibleColumns) {
    if (TARGET_FIELD_EXCLUSIONS.has(column) || GROUP_FIELD_NAMES.has(column)) continue;
    if (identityFields.has(column) && !declaredTargetFields.has(column)) continue;
    const selectedLevels = distinctValues(table.values[column]);
    const completeLevels = distinctValues(completeSampleColumnValues(column));
    if (completeLevels.length < 2) continue;
    // Text labels are categorical. Numeric sample annotations default to a
    // continuous response; scientists can explicitly declare numeric class
    // codes through the sample-metadata target editor.
    const declaredType = declaredTargetFields.has(column) ? profileFields?.target_type : null;
    const type =
      declaredType === "continuous" || declaredType === "categorical"
        ? declaredType
        : completeLevels.some((value) => typeof value !== "number")
          ? "categorical"
          : "continuous";
    // A declared identity may still be a real target -- Lavender's specimen_id is
    // the sample content, eleven specimens across three blocks -- but only while
    // it actually repeats. One value per row identifies rows rather than grouping
    // them, and no split can hold a class out that has a single member. So an
    // identity admitted above must also earn it in the data. The check is
    // confined to declared identity columns: an ordinary categorical annotation
    // with one sample per class is a thin pilot, not a row label, and hiding it
    // silently would be wrong.
    const completeRows = nonEmptyCount(completeSampleColumnValues(column));
    if (
      identityFields.has(column) &&
      type === "categorical" &&
      completeRows > 0 &&
      completeLevels.length >= completeRows
    ) {
      continue;
    }
    options.push({
      label: analysisFieldLabel(column),
      value: column,
      type,
      disabled: false,
      detail:
        selectedLevels.length < 2
          ? `The selected subset has ${selectedLevels.length} value or level. It may be used for exploratory labels, but supervised analyses require variation.`
          : type === "categorical"
            ? `${nonEmptyCount(table.values[column])} non-empty values across ${selectedLevels.length} categorical levels in the selected subset.`
            : `${nonEmptyCount(table.values[column])} non-empty numeric values, ${selectedLevels.length} distinct, in the selected subset; treated as a continuous response.`,
    });
  }
  // Native Y can live outside the sample annotation table. Keep the admitted
  // fields available even when that table contains only specimen metadata.
  for (const field of declaredTargetFields) {
    if (table.visibleColumns.includes(field) || options.some((option) => option.value === field))
      continue;
    if (profileFields?.target_type !== "continuous" && profileFields?.target_type !== "categorical")
      continue;
    options.push({
      label: analysisFieldLabel(field),
      value: field,
      type: profileFields.target_type,
      detail: `Admitted ${profileFields.target_type} field.`,
      disabled: false,
    });
  }
  return options;
});

const analysisGroupOptions = computed<AnalysisGroupOption[]>(() => {
  const options: AnalysisGroupOption[] = [
    { label: "None", value: "", detail: "No grouped validation." },
  ];
  const table = sampleTableState.value;
  if (table.kind !== "valid") {
    for (const field of dataStore.fileInfo?.analysis_readiness?.profile?.group_fields ?? []) {
      options.push({
        label: analysisFieldLabel(field),
        value: field,
        detail: "Admitted grouping field.",
      });
    }
    return options;
  }
  const declaredGroupFields = new Set(
    dataStore.fileInfo?.analysis_readiness?.profile?.group_fields ?? [],
  );
  for (const column of table.visibleColumns) {
    if (!GROUP_FIELD_NAMES.has(column) && !declaredGroupFields.has(column)) continue;
    if (column === analysisTarget.value) continue;
    const levels = distinctValues(table.values[column]);
    const completeLevels = distinctValues(completeSampleColumnValues(column));
    const completeRowCount = completeSampleColumnValues(column).filter(
      (value) => value != null && String(value).trim() !== "",
    ).length;
    // A grouping authority must define repeated, non-constant groups. A unique
    // sample identity is useful as a group only when multiple instrument views
    // of the same specimens are selected together.
    if (completeLevels.length < 2 || completeLevels.length >= completeRowCount) continue;
    options.push({
      label: `${analysisFieldLabel(column)}: ${completeLevels.length}`,
      value: column,
      disabled: levels.length < 2,
      detail: `${levels.length} repeated groups in the selected subset; ${completeLevels.length} in the complete dataset. Grouped validation keeps every row from one group on the same side of a split.`,
    });
  }
  return options;
});

const effectiveAnalysisReadiness = ref<DatasetAnalysisReadiness | null>(null);
const analysisReadinessLoading = ref(false);
const analysisReadinessError = ref<string | null>(null);
const displayedAnalysisReadiness = computed(
  () => effectiveAnalysisReadiness.value ?? dataStore.fileInfo?.analysis_readiness ?? null,
);
let analysisReadinessRequest = 0;

watch(
  () => ({
    experimentId: dataStore.activeExperimentId,
    hydrated: props.analysisSelectionHydrated,
    requestedTarget: props.initialAnalysisTarget,
    requestedGroup: props.initialAnalysisGroup,
    enabledTargetValues: analysisTargetOptions.value
      .filter((option) => !option.disabled)
      .map((option) => option.value),
    groupValues: analysisGroupOptions.value
      .filter((option) => !option.disabled)
      .map((option) => option.value),
    boundTarget: dataStore.fileInfo?.analysis_binding?.selected_target ?? "",
  }),
  (current, previous) => {
    if (!current.hydrated) return;
    const boundTarget = dataStore.fileInfo?.analysis_binding?.selected_target ?? "";
    const requestedTarget = current.requestedTarget || boundTarget;
    if (
      !previous ||
      !previous.hydrated ||
      current.experimentId !== previous.experimentId ||
      current.requestedTarget !== previous.requestedTarget ||
      current.requestedGroup !== previous.requestedGroup ||
      (current.enabledTargetValues.includes(requestedTarget) &&
        !previous.enabledTargetValues.includes(requestedTarget)) ||
      (current.groupValues.includes(current.requestedGroup) &&
        !previous.groupValues.includes(current.requestedGroup))
    ) {
      analysisTarget.value = current.enabledTargetValues.includes(requestedTarget)
        ? requestedTarget
        : "";
      analysisGroup.value = current.groupValues.includes(current.requestedGroup)
        ? current.requestedGroup
        : "";
      return;
    }
    if (!current.enabledTargetValues.includes(analysisTarget.value)) {
      analysisTarget.value = current.enabledTargetValues.includes(requestedTarget)
        ? requestedTarget
        : "";
    }
    if (!current.groupValues.includes(analysisGroup.value)) {
      analysisGroup.value = current.groupValues.includes(current.requestedGroup)
        ? current.requestedGroup
        : "";
    }
  },
  { immediate: true },
);

watch(
  [
    analysisTarget,
    analysisTargetOptions,
    () => dataStore.fileInfo?.analysis_readiness ?? null,
    () => props.analysisSelectionHydrated,
  ],
  async () => {
    const request = ++analysisReadinessRequest;
    if (!props.analysisSelectionHydrated) return;
    const base = dataStore.fileInfo?.analysis_readiness ?? null;
    const target = analysisTargetOptions.value.find(
      (option) => option.value === analysisTarget.value,
    );
    if (!base?.profile) {
      effectiveAnalysisReadiness.value = base;
      analysisReadinessLoading.value = false;
      analysisReadinessError.value = null;
      return;
    }
    const selectedTargetProfile =
      analysisTarget.value && target?.type
        ? {
            ...base.profile,
            target_type: target.type,
            target_fields: [analysisTarget.value],
          }
        : null;
    const previewProfile =
      selectedTargetProfile ??
      (base.profile.target_type !== null
        ? {
            ...base.profile,
            target_type: null,
            target_fields: [],
          }
        : null);
    if (!previewProfile) {
      effectiveAnalysisReadiness.value = base;
      analysisReadinessLoading.value = false;
      analysisReadinessError.value = null;
      return;
    }
    analysisReadinessLoading.value = true;
    analysisReadinessError.value = null;
    try {
      const read = async () =>
        (
          await api.post<DatasetAnalysisReadiness>("/workflow-templates/compatibility-preview", {
            analysis_profile: previewProfile,
          })
        ).data;
      const result = dataStore.fileInfo
        ? await retainedInspection(
            dataStore.fileInfo,
            `readiness:${JSON.stringify(previewProfile)}`,
            read,
          )
        : await read();
      if (request === analysisReadinessRequest) {
        effectiveAnalysisReadiness.value = result;
        analysisReadinessLoading.value = false;
      }
    } catch (error: unknown) {
      if (request === analysisReadinessRequest) {
        effectiveAnalysisReadiness.value = null;
        analysisReadinessLoading.value = false;
        analysisReadinessError.value = getErrorMessage(
          error,
          "Compatibility could not be recomputed for this target.",
        );
      }
    }
  },
  { immediate: true },
);

watch(
  [
    analysisTarget,
    analysisGroup,
    displayedAnalysisReadiness,
    analysisReadinessLoading,
    analysisReadinessError,
    collectionState,
    () => dataStore.fileInfoLoading,
    () => dataStore.fileInfo?.target_context?.target_units,
  ],
  () => {
    if (!props.analysisSelectionHydrated) return;
    if (!analysisTarget.value && analysisGroup.value) {
      analysisGroup.value = "";
      return;
    }
    emit("analysisChoice", currentAnalysisChoice());
  },
  { immediate: true },
);

function currentAnalysisChoice(): AnalysisChoice {
  const target = analysisTargetOptions.value.find(
    (option) => option.value === analysisTarget.value,
  );
  const nativeTarget = dataStore.fileInfo?.target_context;
  const nativeNames = nativeTarget?.target_names ??
    (nativeTarget?.target_name ? [nativeTarget.target_name] : []);
  return {
    target: analysisTarget.value,
    targetType: target?.type ?? null,
    targetUnits:
      nativeNames.includes(analysisTarget.value) &&
      typeof nativeTarget?.target_units === "string"
        ? nativeTarget.target_units
        : null,
    sourceDigest:
      !dataStore.fileInfoLoading && collectionState.value.kind === "valid"
        ? (collectionState.value.scientificIdentity?.scientificDigest ??
          collectionState.value.manifestDigest)
        : null,
    group: analysisTarget.value ? analysisGroup.value : "",
    readiness:
      analysisReadinessLoading.value || analysisReadinessError.value
        ? null
        : displayedAnalysisReadiness.value,
  };
}

function commitAnalysisTarget(value: string): void {
  analysisTarget.value = value;
  if (!value) analysisGroup.value = "";
  emit("analysisSelectionCommit", currentAnalysisChoice());
}

function commitAnalysisGroup(value: string): void {
  analysisGroup.value = value;
  emit("analysisSelectionCommit", currentAnalysisChoice());
}

function formatSampleColumn(value: string): string {
  return value.split("_").join(" ");
}

function formatSampleValue(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "[structured value]";
}

function isLosslessSampleTableScalar(value: unknown): boolean {
  if (value == null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value !== "number" || !Number.isFinite(value)) return false;
  return !Number.isInteger(value) || Number.isSafeInteger(value);
}

const canPrepareSamples = computed(
  () =>
    dataStore.activeExperimentId != null &&
    dataStore.activeFileId != null &&
    (dataStore.fileInfo?.n_samples ?? 0) > 0,
);

async function saveSampleTable(payload: SampleTableSavePayload): Promise<void> {
  if (
    dataStore.activeExperimentId == null ||
    dataStore.activeFileId == null ||
    dataStore.activeFilePath == null
  ) {
    sampleTableMessage.value = {
      kind: "error",
      text: "Select one source file before saving and binding its sample-table CSV.",
    };
    return;
  }
  const sourceFileId = dataStore.activeFileId;
  const sourceFilePath = dataStore.activeFilePath;
  const experimentId = dataStore.activeExperimentId;
  sampleTableSaving.value = true;
  clearSampleTableSaveError();
  sampleTableMessage.value = null;
  try {
    const savedFile = await dataStore.uploadFile(experimentId, payload.file, "preprocessed", {
      dataRole: "X_features",
      targetColumn: payload.targetColumn,
      targetType: payload.targetType,
      refresh: false,
    });
    sampleTableMessage.value = {
      kind: "success",
      fileId: savedFile.id,
      filePath: savedFile.file_path,
      targetColumn: payload.targetColumn,
      summary: payload.summary,
    };
    try {
      await dataStore.bindDatasetAnalysisCsv({
        sourceFileId,
        sampleTableFileId: savedFile.id,
        expectedRevision: payload.expectedRevision,
        selectedTarget: payload.targetColumn,
        targetType: payload.targetType,
      });
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : "binding failed";
      sampleTableMessage.value = {
        kind: "error",
        text: `The CSV was saved as file #${savedFile.id}, but was not bound to the dataset: ${detail}`,
      };
      sampleTableSaveError.value = `Save was not completed: ${detail}`;
      sampleTableSaveConflict.value = axios.isAxiosError(error) && error.response?.status === 409;
      return;
    }
    sampleTableEditorRef.value?.markSaved();
    emit("measuredSamplesPublished");
    await Promise.all([dataStore.selectExperiment(experimentId), dataStore.fetchCatalog()]);
    // A refresh failure must not misreport the already-durable save and bind.
    await dataStore.inspectFile(sourceFileId, sourceFilePath, experimentId).catch(() => null);
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : "Failed to save sample table";
    sampleTableMessage.value = { kind: "error", text: detail };
    sampleTableSaveError.value = detail;
    sampleTableSaveConflict.value = false;
  } finally {
    sampleTableSaving.value = false;
  }
}

async function unbindSampleTable(): Promise<void> {
  if (
    dataStore.activeExperimentId == null ||
    dataStore.activeFileId == null ||
    dataStore.activeFilePath == null
  )
    return;
  sampleTableSaving.value = true;
  sampleTableMessage.value = null;
  try {
    const expectedRevision = dataStore.fileInfo?.analysis_binding?.revision;
    if (expectedRevision == null) return;
    await dataStore.unbindDatasetAnalysisCsv(dataStore.activeFileId, expectedRevision);
    await dataStore.inspectFile(
      dataStore.activeFileId,
      dataStore.activeFilePath,
      dataStore.activeExperimentId,
    );
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : "Failed to remove target binding";
    sampleTableMessage.value = { kind: "error", text: detail };
  } finally {
    sampleTableSaving.value = false;
  }
}

function targetNamesFromContext(context: unknown): string[] {
  if (!context || typeof context !== "object") return [];
  const record = context as Record<string, unknown>;
  const raw = record.target_names ?? record.class_names;
  return Array.isArray(raw) ? raw.map((item) => String(item)).filter(Boolean) : [];
}

const targetOptions = computed(() => {
  const fileTargets = targetNamesFromContext(dataStore.fileInfo?.target_context);
  if (fileTargets.length) return fileTargets;
  const catalogTargets = dataStore.catalogDatasetInfo?.target_names ?? [];
  return Array.isArray(catalogTargets)
    ? catalogTargets.map((item) => String(item)).filter(Boolean)
    : [];
});

const showTargetControls = computed(() => targetOptions.value.length > 1);

function syncTargetControls(metadata: Record<string, unknown> | undefined, targetNames: string[]) {
  const mode = metadata?.target_mode === "multi" ? "multi" : "single";
  targetMode.value = targetNames.length > 1 ? mode : "single";
  const savedTarget = typeof metadata?.selected_target === "string" ? metadata.selected_target : "";
  selectedTarget.value =
    savedTarget && targetNames.includes(savedTarget) ? savedTarget : (targetNames[0] ?? "");
}

let metadataHydration = 0;
let metadataHydrating = false;
let _persistTimer: ReturnType<typeof setTimeout> | null = null;
let pendingMetadataWrite: (() => Promise<void>) | null = null;
function beginMetadataHydration() {
  const request = ++metadataHydration;
  metadataHydrating = true;
  flushMetadataWrite();
  void nextTick(() => {
    if (request === metadataHydration) metadataHydrating = false;
  });
}

function _syncFromFileInfo(fi: { metadata?: Record<string, unknown> } | null) {
  beginMetadataHydration();
  const m = fi?.metadata as Record<string, unknown> | undefined;
  editXTitle.value = (m?.x_title ?? "") as string;
  editXUnits.value = (m?.x_units ?? "") as string;
  editYTitle.value = (m?.data_quantity ?? "") as string;
  isTimeSeriesToggle.value = !!m?.is_time_series;
  syncTargetControls(
    m,
    targetNamesFromContext((fi as Record<string, unknown> | null)?.target_context),
  );
}

function _syncFromCatalog(info: CatalogDatasetInfo | null) {
  beginMetadataHydration();
  const m = info?.metadata as Record<string, unknown> | undefined;
  editXTitle.value = (info?.x_title ?? "") as string;
  editXUnits.value = (info?.x_units ?? "") as string;
  editYTitle.value = (info?.data_quantity ?? "") as string;
  isTimeSeriesToggle.value = !!m?.is_time_series || !!info?.is_time_series;
  syncTargetControls(
    m,
    Array.isArray(info?.target_names) ? info.target_names.map((item) => String(item)) : [],
  );
}

watch(
  [() => dataStore.fileInfo, () => dataStore.catalogDatasetInfo],
  ([fileInfo, catalogInfo]) => {
    if (fileInfo) _syncFromFileInfo(fileInfo);
    else _syncFromCatalog(catalogInfo);
  },
  { immediate: true },
);

function prepareMetadataOverride(): (() => Promise<void>) | null {
  const xTitle = editXTitle.value;
  const xUnits = editXUnits.value;
  const yTitle = editYTitle.value;
  const isTimeSeries = isTimeSeriesToggle.value;
  const targetNames = targetOptions.value;
  const targetModeValue = targetNames.length > 1 ? targetMode.value : null;
  const selectedTargetValue =
    targetModeValue === "single" ? selectedTarget.value || targetNames[0] || null : null;
  const body: Record<string, unknown> = {
    x_title: xTitle,
    x_units: xUnits,
    y_title: yTitle,
    is_time_series: isTimeSeries,
    target_mode: targetModeValue,
    selected_target: selectedTargetValue,
  };

  const catInfo = dataStore.catalogDatasetInfo;
  if (catInfo?.source && catInfo?.name) {
    body.source = catInfo.source;
    body.name = catInfo.name;
  } else if (dataStore.activeFilePath) {
    body.file_path = dataStore.activeFilePath;
    if (dataStore.activeExperimentId) body.experiment_id = dataStore.activeExperimentId;
  } else {
    return null;
  }

  const fi = dataStore.fileInfo;
  return async () => {
    try {
      await api.patch("/builder/file-metadata", body);
      if (fi && typeof fi === "object") {
        const fiAny = fi as Record<string, unknown> & { metadata?: Record<string, unknown> };
        if (fiAny.metadata && typeof fiAny.metadata === "object") {
          fiAny.metadata.x_title = xTitle;
          fiAny.metadata.x_units = xUnits;
          fiAny.metadata.data_quantity = yTitle;
          fiAny.metadata.is_time_series = isTimeSeries;
          fiAny.metadata.target_mode = targetModeValue;
          fiAny.metadata.selected_target = selectedTargetValue;
        }
        fiAny.x_title = xTitle;
        fiAny.x_units = xUnits;
        fiAny.data_quantity = yTitle;
        fiAny.is_time_series = isTimeSeries;
      }
      if (catInfo) {
        const ciAny = catInfo as Record<string, unknown>;
        ciAny.x_title = xTitle;
        ciAny.x_units = xUnits;
        ciAny.data_quantity = yTitle;
        ciAny.is_time_series = isTimeSeries;
        const ciMeta = (ciAny.metadata ?? {}) as Record<string, unknown>;
        ciMeta.target_mode = targetModeValue;
        ciMeta.selected_target = selectedTargetValue;
        ciAny.metadata = ciMeta;
      }
    } catch (err) {
      console.warn("Failed to persist metadata override", err);
    }
  };
}

function flushMetadataWrite() {
  if (_persistTimer) clearTimeout(_persistTimer);
  _persistTimer = null;
  const write = pendingMetadataWrite;
  pendingMetadataWrite = null;
  if (write) void write();
}

function schedulePersist() {
  if (metadataHydrating) return;
  if (_persistTimer) clearTimeout(_persistTimer);
  pendingMetadataWrite = prepareMetadataOverride();
  _persistTimer = setTimeout(flushMetadataWrite, 500);
}

watch(editXTitle, schedulePersist);
watch(editXUnits, schedulePersist);
watch(editYTitle, schedulePersist);
watch(isTimeSeriesToggle, schedulePersist);
watch(targetMode, schedulePersist);
watch(selectedTarget, schedulePersist);
onBeforeUnmount(flushMetadataWrite);

const sdMeta = computed(() => {
  const m = dataStore.fileInfo?.metadata as Record<string, unknown> | undefined;
  const xAxis = dataStore.fileInfo?.x_axis;
  const axisData = Array.isArray(xAxis?.data) ? xAxis.data : [];
  const metadataWavenumbers = Array.isArray(m?.wavenumbers) ? m.wavenumbers : [];
  const selectedValues = featureAxisDisplay.value?.values ?? [];
  const usesAlternateScale = selectedFeatureScale.value !== PRIMARY_AXIS_SET;
  const usesAlternateTitle = selectedFeatureTitle.value !== PRIMARY_AXIS_SET;
  return {
    wavenumbers: (selectedValues.length
      ? selectedValues
      : metadataWavenumbers.length
        ? metadataWavenumbers
        : axisData) as number[],
    labels: displaySampleLabels.value,
    x_title:
      usesAlternateScale || usesAlternateTitle
        ? featureAxisDisplay.value?.title || editXTitle.value
        : editXTitle.value,
    x_units: usesAlternateScale
      ? featureAxisDisplay.value?.units || editXUnits.value
      : editXUnits.value,
    spectral_technique: (m?.spectral_technique ?? null) as string | null,
    data_quantity: editYTitle.value,
    value_units: (m?.value_units ?? null) as string | null,
    prop_names: (m?.prop_names ?? []) as string[],
    properties: (m?.properties ?? null) as Record<string, number[]> | null,
  };
});

const propertyStats = computed(() => {
  const { properties, prop_names } = sdMeta.value;
  if (!properties || !prop_names.length) return [];
  return prop_names.map((name) => {
    const vals = selectedRows(properties[name] ?? []).filter((v) => v != null && isFinite(v));
    if (!vals.length) return { name, min: null, max: null, mean: null };
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    return { name, min, max, mean };
  });
});

const hasMatrixData = computed(() => {
  const fi = dataStore.fileInfo;
  return !!fi?.data?.length && (fi.ndim ?? fi.shape?.length ?? 2) === 2;
});

const requiresDimensionProjection = computed(
  () => (dataStore.fileInfo?.ndim ?? dataStore.fileInfo?.shape?.length ?? 2) > 2,
);

const boxPlotData = computed(() => {
  const fi = dataStore.fileInfo;
  const metadata = fi?.metadata as Record<string, unknown> | undefined;
  if (
    fi?.data_role === "X_spectra" ||
    metadata?.data_role === "X_spectra" ||
    metadata?.is_spectra === true
  ) {
    return [];
  }
  const matrix = completeMatrix.value;
  const rows = fi?.data?.length ? selectedRows(fi.data) : (matrix?.matrix ?? []);
  const labels = featureAxisDisplay.value?.labels?.length
    ? featureAxisDisplay.value.labels
    : matrix?.col_labels?.length
      ? matrix.col_labels
      : fi?.x_axis?.labels;
  if (!labels?.length || !rows.length) return [];
  return labels.map((col, colIdx) => ({
    type: "box" as const,
    y: rows
      .map((row) => row[colIdx])
      .filter((v): v is number => v !== null && typeof v === "number"),
    name: col,
    marker: { color: PLOT_COLORS[colIdx % PLOT_COLORS.length] },
    boxpoints: false,
  }));
});

const boxPlotLayout = computed(() => ({
  title: { text: "Property Distributions", font: { size: 14 } },
  xaxis: { title: "Property" },
  yaxis: { title: sdMeta.value.value_units || sdMeta.value.x_title || "" },
  autosize: true,
  height: 400,
  margin: { t: 40, r: 20, b: 50, l: 60 },
  showlegend: false,
  plot_bgcolor: "#fafafa",
  paper_bgcolor: "#ffffff",
}));

const catalogPreviewPlotData = computed(() => {
  const info = dataStore.catalogDatasetInfo;
  const spectra = info?.preview_spectra;
  if (!spectra?.length || info?.feature_labels?.length) return [];
  const firstRow = spectra[0] ?? [];
  const wavelengths = info?.wavelengths?.length
    ? info.wavelengths
    : Array.from({ length: firstRow.length }, (_, i) => i);
  return spectra.map((spectrum, i) => ({
    x: wavelengths,
    y: spectrum,
    type: "scatter" as const,
    mode: "lines" as const,
    name: `Spectrum ${i + 1}`,
    line: { color: PLOT_COLORS[i % PLOT_COLORS.length], width: 1.2 },
  }));
});

const catalogPreviewPlotLayout = computed(() => {
  const info = dataStore.catalogDatasetInfo;
  const xTitle = editXTitle.value || info?.x_title || "";
  const xUnits = editXUnits.value || info?.x_units || "";
  return {
    title: { text: "Spectra Preview", font: { size: 14 } },
    xaxis: {
      title: xTitle && xUnits ? `${xTitle} (${xUnits})` : xTitle,
      autorange: shouldReverseFeatureAxis({
        title: xTitle,
        units: xUnits,
        quantity: info?.x_quantity ?? undefined,
      })
        ? ("reversed" as const)
        : (true as const),
    },
    yaxis: { title: editYTitle.value || info?.data_quantity || "" },
    autosize: true,
    height: 380,
    margin: { t: 40, r: 20, b: 50, l: 60 },
    showlegend: (catalogPreviewPlotData.value.length ?? 0) <= 20,
    legend: { font: { size: 10 }, orientation: "h" as const, y: -0.25 },
    plot_bgcolor: "#fafafa",
    paper_bgcolor: "#ffffff",
  };
});

const catalogBoxPlotData = computed(() => {
  const info = dataStore.catalogDatasetInfo;
  const labels = info?.feature_labels;
  const spectra = info?.preview_spectra;
  if (!labels?.length || !spectra?.length) return [];
  return labels.map((col, colIdx) => ({
    type: "box" as const,
    y: spectra
      .map((row) => row[colIdx])
      .filter((v): v is number => v !== null && typeof v === "number"),
    name: col,
    marker: { color: PLOT_COLORS[colIdx % PLOT_COLORS.length] },
    boxpoints: false,
  }));
});

const catalogBoxPlotLayout = computed(() => ({
  title: { text: "Feature Distributions", font: { size: 14 } },
  xaxis: { title: "Feature" },
  yaxis: { title: editYTitle.value || "" },
  autosize: true,
  height: 400,
  margin: { t: 40, r: 20, b: 80, l: 60 },
  showlegend: false,
  plot_bgcolor: "#fafafa",
  paper_bgcolor: "#ffffff",
}));

const isDataStoryButtonDisabled = computed(() => sherpaStore.isSyncing || sherpaStore.isChatting);
const dataStoryButtonLabel = computed(() =>
  dataStore.dataStoryText ? "Regenerate Data Story" : "Generate Data Story",
);
const dataStoryButtonHoverText = computed(() =>
  isDataStoryButtonDisabled.value ? "Available when Sherpa Advisor finishes" : "",
);

function extractFileName(filePath: string): string {
  return filePath.split("/").pop() || filePath;
}

const PropertyStatsTable = defineComponent({
  name: "PropertyStatsTable",
  props: {
    stats: { type: Array as () => DataStoryPropertyStat[], required: true },
  },
  setup(props) {
    return () =>
      h(
        DataTable,
        { value: props.stats, size: "small", stripedRows: true, class: "prop-stats-table" },
        {
          default: () => [
            h(Column, { field: "name", header: "Property" }),
            h(
              Column,
              { header: "Range" },
              {
                body: ({ data }: { data: DataStoryPropertyStat }) =>
                  data.min != null ? `${data.min.toFixed(2)} - ${data.max?.toFixed(2)}` : "N/A",
              },
            ),
            h(
              Column,
              { header: "Mean" },
              {
                body: ({ data }: { data: DataStoryPropertyStat }) =>
                  data.mean != null ? data.mean.toFixed(2) : "N/A",
              },
            ),
          ],
        },
      );
  },
});

const MetadataEditor = defineComponent({
  name: "MetadataEditor",
  props: {
    xTitle: { type: String, default: "" },
    xUnits: { type: String, default: "" },
    yTitle: { type: String, default: "" },
    isTimeSeries: { type: Boolean, default: false },
    targetMode: { type: String as () => "single" | "multi", default: "single" },
    selectedTarget: { type: String, default: "" },
    xTitleOptions: { type: Array as () => string[], required: true },
    xUnitsOptions: { type: Array as () => string[], required: true },
    yTitleOptions: { type: Array as () => string[], required: true },
    targetOptions: { type: Array as () => string[], default: () => [] },
    showTargetControls: { type: Boolean, default: false },
  },
  emits: [
    "update:xTitle",
    "update:xUnits",
    "update:yTitle",
    "update:isTimeSeries",
    "update:targetMode",
    "update:selectedTarget",
  ],
  setup(props, { emit }) {
    const row = (label: string, control: VNodeChild) =>
      h("div", { class: "meta-row" }, [h("span", { class: "meta-key" }, label), control]);
    return () => [
      row(
        "X-Axis",
        h(Dropdown, {
          modelValue: props.xTitle,
          options: props.xTitleOptions,
          editable: true,
          placeholder: "Select or type...",
          class: "meta-dropdown",
          "onUpdate:modelValue": (value: string) => emit("update:xTitle", value),
        }),
      ),
      row(
        "X Units",
        h(Dropdown, {
          modelValue: props.xUnits,
          options: props.xUnitsOptions,
          editable: true,
          placeholder: "Units",
          class: "meta-dropdown",
          "onUpdate:modelValue": (value: string) => emit("update:xUnits", value),
        }),
      ),
      row(
        "Y-Axis",
        h(Dropdown, {
          modelValue: props.yTitle,
          options: props.yTitleOptions,
          editable: true,
          placeholder: "Select or type...",
          class: "meta-dropdown",
          "onUpdate:modelValue": (value: string) => emit("update:yTitle", value),
        }),
      ),
      row(
        "Time Series",
        h(InputSwitch, {
          modelValue: props.isTimeSeries,
          "onUpdate:modelValue": (value: boolean) => emit("update:isTimeSeries", value),
        }),
      ),
      props.showTargetControls
        ? row(
            "Target Mode",
            h(Dropdown, {
              modelValue: props.targetMode,
              options: [
                { label: "Single property", value: "single" },
                { label: "Multi-target complete-case", value: "multi" },
              ],
              optionLabel: "label",
              optionValue: "value",
              class: "meta-dropdown",
              "onUpdate:modelValue": (value: "single" | "multi") =>
                emit("update:targetMode", value),
            }),
          )
        : null,
      props.showTargetControls && props.targetMode === "single"
        ? row(
            "Target Property",
            h(Dropdown, {
              modelValue: props.selectedTarget,
              options: props.targetOptions,
              placeholder: "Select property",
              class: "meta-dropdown",
              "onUpdate:modelValue": (value: string) => emit("update:selectedTarget", value),
            }),
          )
        : null,
    ];
  },
});

const DataStorySection = defineComponent({
  name: "DataStorySection",
  setup() {
    return () => {
      if (!isFeatureEnabled("sherpaDataStory")) return null;
      return h("div", { class: "data-story-panel" }, [
        h("div", { class: "data-story-header" }, [
          h("h4", { class: "panel-title" }, [h("i", { class: "pi pi-book" }), " Data Story"]),
          h("div", { class: "data-story-actions" }, [
            h("span", { class: "ai-feature-note" }, "AI Feature"),
            h("span", { class: "data-story-button-wrap", title: dataStoryButtonHoverText.value }, [
              h(Button, {
                label: dataStoryButtonLabel.value,
                icon: "pi pi-sparkles",
                class: "p-button-sm p-button-outlined",
                loading: dataStore.dataStoryLoading,
                disabled: isDataStoryButtonDisabled.value,
                onClick: () => dataStore.generateDataStory(),
              }),
            ]),
          ]),
        ]),
        h("div", { class: "data-story-context" }, [
          h(
            "label",
            { class: "data-story-context-label", for: "contents-data-story-context" },
            "Additional Context",
          ),
          h(Textarea, {
            id: "contents-data-story-context",
            modelValue: dataStore.dataStoryContext,
            rows: 3,
            autoResize: true,
            class: "data-story-context-input",
            placeholder:
              "Optional: add domain context, process background, sample type, or what you want the story to emphasize.",
            "onUpdate:modelValue": (value: string) => {
              dataStore.dataStoryContext = value;
            },
          }),
          h(
            "p",
            { class: "data-story-context-hint" },
            "This will be passed to the LLM as extra context for a more relevant narrative.",
          ),
        ]),
        dataStore.dataStoryLoading
          ? h("div", { class: "data-story-loading" }, [
              h(ProgressSpinner, { style: "width: 24px; height: 24px" }),
              h("span", "Generating narrative..."),
            ])
          : dataStore.dataStoryText
            ? h("div", { class: "data-story-text" }, [
                h(MemoryAttribution, { scopes: dataStore.dataStoryMemoryScopes }),
                dataStore.dataStoryText,
              ])
            : h(
                "p",
                { class: "data-story-hint" },
                'Click "Generate Data Story" to create an LLM-powered narrative describing this dataset\'s scientific context and characteristics.',
              ),
      ]);
    };
  },
});
</script>

<style>
.contents-panel {
  border-top: 1px solid var(--surface-border);
  padding-top: 1.25rem;
  margin-top: 1.5rem;
}

.contents-panel details > summary {
  align-items: center;
  cursor: pointer;
  display: flex;
  gap: 0.7rem;
  list-style: none;
}

.contents-panel details > summary::-webkit-details-marker {
  display: none;
}

.contents-panel details > summary::before {
  border-bottom: 2px solid currentColor;
  border-right: 2px solid currentColor;
  content: "";
  flex: 0 0 auto;
  height: 0.42rem;
  transform: rotate(-45deg);
  transition: transform 120ms ease;
  width: 0.42rem;
}

.contents-panel details[open] > summary::before {
  transform: rotate(45deg);
}

.global-display-metadata {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  margin: 0 0 1rem;
  padding: 0.35rem 0.75rem;
}

.global-display-metadata > summary {
  color: var(--text-color);
  font-size: 0.9rem;
  font-weight: 600;
  padding: 0.55rem 0;
}

.global-display-metadata-controls {
  border-top: 1px solid var(--surface-border);
  padding: 0.45rem 0 0.2rem;
}

.contents-panel-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.contents-panel-header h3 {
  margin: 0 0 0.2rem;
  font-size: 1rem;
  font-weight: 600;
}

.contents-panel-header p {
  margin: 0;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.explore-loading,
.explore-error,
.explore-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 24px;
  color: #94a3b8;
  text-align: center;
}

.explore-empty i {
  font-size: 2.5rem;
}

.explore-empty h3 {
  margin: 0;
  color: #475569;
}

.explore-empty p {
  max-width: 400px;
  line-height: 1.5;
  color: #64748b;
}

.explore-error i {
  font-size: 2rem;
  color: #f59e0b;
}

.explore-error span {
  color: #dc2626;
}

.explore-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.focused-dataset-details {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  margin-bottom: 1rem;
}

.focused-dataset-details > summary {
  align-items: center;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  padding: 0.85rem 1rem;
}

.focused-dataset-details > summary > span {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.18rem;
}

.focused-dataset-details > summary strong {
  color: var(--text-color);
  font-size: 0.9rem;
  line-height: 1.25;
}

.focused-dataset-details > summary small {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  line-height: 1.35;
}

.focused-dataset-details[open] > summary {
  border-bottom: 1px solid var(--surface-border);
}

.focused-dataset-details .explore-content {
  padding: 1rem;
}

.explore-header,
.data-story-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.explore-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 1.1rem;
  font-weight: 600;
  color: #1e293b;
}

.explore-title i {
  color: #64748b;
}

.essential-card-number {
  align-items: center;
  background: #2563eb;
  border-radius: 999px;
  color: #ffffff;
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 0.75rem;
  height: 1.5rem;
  justify-content: center;
  width: 1.5rem;
}

.loaded-file-title {
  display: flex;
  flex-direction: column;
}

.loaded-file-title small {
  color: var(--text-color-secondary);
  font-size: 0.72rem;
  font-weight: 500;
}

.selected-files-details {
  padding: 0.55rem 0.7rem;
  border-radius: 7px;
  background: var(--surface-ground);
  font-size: 0.8rem;
}

.selected-files-details summary {
  font-weight: 600;
  padding: 0.1rem 0;
}

.selected-files-details ul {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.25rem 1rem;
  margin: 0.55rem 0 0;
  padding-left: 1.1rem;
}

.explore-table {
  margin-bottom: 16px;
}

.table-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.explore-plot {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  width: 100%;
  box-sizing: border-box;
}

.plot-display-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: 0.75rem 1rem;
  margin-bottom: 0.75rem;
  padding: 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.45rem;
  background: #f8fafc;
}

.plot-display-options,
.technical-details {
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  background: #ffffff;
}

.plot-display-options > summary,
.technical-details > summary {
  color: #475569;
  font-size: 0.84rem;
  font-weight: 600;
  gap: 0.5rem;
  padding: 0.7rem 0.85rem;
}

.plot-display-options .plot-display-controls {
  border: 0;
  border-top: 1px solid #e2e8f0;
  border-radius: 0;
  margin: 0;
}

.multi-dataset-style-authority {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  color: #334155;
  font-size: 0.8rem;
}

.multi-dataset-style-authority span {
  color: #64748b;
}

.multi-dataset-plot-status {
  align-items: flex-start;
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem 1rem;
  justify-content: space-between;
  margin: 0.75rem 0;
  padding: 0.7rem 0.85rem;
}

.multi-dataset-plot-status > div:first-child {
  align-items: center;
  color: #334155;
  display: flex;
  gap: 0.5rem;
}

.multi-dataset-tags {
  display: flex;
  flex: 1 1 24rem;
  flex-wrap: wrap;
  gap: 0.35rem;
  justify-content: flex-end;
}

.technical-details[open] {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding-bottom: 1rem;
}

.technical-details[open] > summary {
  border-bottom: 1px solid #e2e8f0;
}

.technical-details > section {
  margin-left: 1rem;
  margin-right: 1rem;
}

.essential-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 0.6rem;
  padding: 1rem;
}

.essential-card-heading {
  align-items: flex-start;
  display: flex;
  gap: 0.65rem;
}

.essential-card-heading > div {
  flex: 1;
}

.essential-card-heading h4,
.essential-card-heading p {
  margin: 0;
}

.essential-card-heading p {
  color: #64748b;
  font-size: 0.8rem;
  margin-top: 0.15rem;
}

.essential-fact-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
  gap: 0.75rem 1.25rem;
  margin: 1rem 0 0;
}

.essential-fact-grid dt {
  color: #64748b;
  font-size: 0.75rem;
}

.essential-fact-grid dd {
  color: #1e293b;
  font-size: 0.88rem;
  font-weight: 600;
  margin: 0.15rem 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sample-label-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.85rem;
}

.priority-card {
  padding: 1rem;
}

.dimension-projection-notice {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.9rem 1rem;
  border-left: 3px solid #6366f1;
  background: #eef2ff;
  color: #3730a3;
}

.dimension-projection-notice p {
  margin: 0.25rem 0 0;
  color: #475569;
  line-height: 1.45;
}

.axis-inventory {
  padding: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  background: #ffffff;
}

.axis-inventory-header,
.axis-card > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.axis-inventory-header p,
.axis-card span {
  margin: 0.2rem 0 0;
  color: #64748b;
  font-size: 0.8rem;
}

.axis-inventory-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  gap: 0.75rem;
  margin-top: 0.8rem;
}

.axis-card {
  padding: 0.75rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.4rem;
  background: #f8fafc;
}

.axis-card > div:first-child {
  align-items: flex-start;
  flex-direction: column;
  gap: 0;
}

.axis-card dl {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.3rem 0.75rem;
  margin: 0.65rem 0 0;
  font-size: 0.78rem;
}

.axis-card dt {
  color: #64748b;
}

.axis-card dd {
  margin: 0;
  color: #334155;
  font-weight: 600;
}

.scientific-context {
  display: grid;
  grid-template-columns: minmax(14rem, 1fr) minmax(18rem, 2fr);
  gap: 1rem 2rem;
  padding: 1rem;
  border-left: 3px solid #0f766e;
  background: #f0fdfa;
}

.scientific-context p {
  margin: 0.35rem 0 0;
  color: #475569;
  line-height: 1.45;
}

.scientific-context dl {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 0.35rem 0.9rem;
  margin: 0;
  font-size: 0.8rem;
}

.scientific-context dt {
  color: #64748b;
}

.scientific-context dd {
  margin: 0;
  overflow-wrap: anywhere;
  color: #334155;
  font-weight: 600;
}

.scientific-context dd.digest {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.72rem;
}

.plot-display-notice,
.sample-table-retrieval-error {
  margin: 0.5rem 0 0;
  font-size: 0.82rem;
}

.plot-display-notice {
  color: #475569;
}

.sample-table-retrieval-error {
  color: #b91c1c;
}

.plot-grouping-legend {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: 0.8rem 1.5rem;
  padding: 0.75rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.4rem;
  background: #f8fafc;
  font-size: 0.78rem;
}

.plot-grouping-legend > div {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem 0.8rem;
}

.plot-grouping-legend strong {
  width: 100%;
  color: #334155;
}

.plot-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  color: #475569;
}

.plot-legend-item i {
  display: inline-block;
  width: 0.85rem;
  height: 0.85rem;
  border-radius: 50%;
}

.plot-legend-item .plot-line-swatch {
  width: 1.2rem;
  height: 0;
  border-top-width: 2px;
  border-top-color: #475569;
  border-radius: 0;
  background: transparent;
}

.collection-identity {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.75rem 1rem;
  border-left: 3px solid var(--primary-color);
  background: #f8fafc;
}

.collection-identity div {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.collection-identity span,
.collection-sample-table-header p,
.sample-table-omission-note {
  margin: 0;
  color: #64748b;
  font-size: 0.82rem;
}

.collection-identity code {
  max-width: 50%;
  overflow-wrap: anywhere;
  color: #334155;
  font-size: 0.72rem;
}

.collection-sample-table-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.collection-sample-table-header .panel-title {
  margin-bottom: 0.2rem;
}

.collection-sample-table-scroll {
  overflow-x: auto;
  border: 1px solid #e2e8f0;
  border-radius: 0.4rem;
}

.collection-sample-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  white-space: nowrap;
}

.collection-sample-table th,
.collection-sample-table td {
  padding: 0.45rem 0.6rem;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
}

.collection-sample-table th {
  background: #f8fafc;
  color: #475569;
  font-weight: 650;
  text-transform: capitalize;
}

.collection-sample-table tbody tr:last-child td {
  border-bottom: none;
}

.sample-table-omission-note {
  margin-top: 0.5rem;
}

.explore-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.metadata-panel {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
}

.panel-title {
  margin: 0 0 12px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #1e293b;
}

.metadata-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metadata-editor-details {
  border-top: 1px solid #e2e8f0;
  margin-top: 0.35rem;
  padding-top: 0.5rem;
}

.metadata-editor-details > summary {
  color: #475569;
  font-size: 0.8rem;
  font-weight: 600;
  padding: 0.35rem 0;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 6px 0;
  border-bottom: 1px solid #f1f5f9;
}

.meta-row:last-child {
  border-bottom: none;
}

.meta-key {
  font-size: 0.85rem;
  color: #64748b;
}

.meta-val {
  font-size: 0.9rem;
  color: #1e293b;
  font-weight: 500;
}

.meta-dropdown {
  width: 160px;
  font-size: 0.85rem;
}

.data-story-panel {
  margin-top: 1rem;
  padding: 0.25rem 0 0.25rem 1rem;
  background: transparent;
  border: none;
  border-left: 3px solid var(--primary-color);
  border-radius: 0;
}

.data-story-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.data-story-button-wrap {
  display: inline-flex;
}

.data-story-header .panel-title {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.data-story-context {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.data-story-context-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
}

.data-story-context-input {
  width: 100%;
}

.data-story-context-hint {
  margin: 0;
  font-size: 0.8rem;
  color: #64748b;
  line-height: 1.4;
}

.ai-feature-note {
  font-size: 0.6875rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  text-transform: lowercase;
  color: #8b5cf6;
  background: transparent;
  border: 1px solid color-mix(in srgb, #8b5cf6 35%, transparent);
  padding: 0.05rem 0.45rem;
  border-radius: 4px;
}

.data-story-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 0.9rem;
}

.data-story-text {
  font-size: 0.9rem;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
}

.data-story-hint {
  color: #94a3b8;
  font-size: 0.85rem;
  font-style: italic;
  margin: 0;
}

.dataset-description {
  font-size: 0.9rem;
  color: #475569;
  line-height: 1.6;
  margin: 0;
  white-space: pre-line;
}

.sample-table-message {
  display: flex;
  gap: 0.65rem;
  margin: 0 0 1rem;
  padding: 0.85rem 1rem;
  border: 1px solid;
  border-radius: 0.65rem;
}

.sample-table-message.success {
  display: block;
  color: #047857;
  border-color: #a7f3d0;
  background: #ecfdf5;
}

.sample-table-message.error {
  color: #b91c1c;
  border-color: #fecaca;
  background: #fef2f2;
}

.sample-table-receipt-heading {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
}

.sample-table-receipt-heading i {
  margin-top: 0.15rem;
  font-size: 1.1rem;
}

.sample-table-receipt-heading p,
.sample-table-next-step {
  margin: 0.2rem 0 0;
}

.sample-table-receipt-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.7rem;
}

.sample-table-receipt-details {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 0.2rem 0.65rem;
  margin: 0.65rem 0 0;
  font-size: 0.84rem;
}

.sample-table-receipt-details dt {
  font-weight: 650;
}

.sample-table-receipt-details dd {
  margin: 0;
  color: #334155;
}

.sample-table-next-step {
  color: #334155;
  font-size: 0.84rem;
}

@media (max-width: 800px) {
  .explore-panels {
    grid-template-columns: 1fr;
  }

  .plot-grouping-legend {
    grid-template-columns: 1fr;
  }
}
</style>
