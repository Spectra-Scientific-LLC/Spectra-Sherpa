<template>
  <section class="source-preview">
    <div v-if="!sourceRef && !acquisitionRequired" class="preview-empty">
      <i class="pi pi-table"></i>
      <span>Select a data source name to preview the matrix and metadata before adding it.</span>
    </div>
    <template v-else-if="acquisitionRequired">
      <header class="source-preview-title">
        <strong class="meta-name" :title="title">{{ title }}</strong>
      </header>
      <div class="preview-acquisition" role="status">
        <i class="pi pi-file-import" aria-hidden="true"></i>
        <div>
          <strong>Provider file required</strong>
          <span>
            Import the downloaded provider ZIP to inspect its exact files, matrix, metadata, and
            plots.
          </span>
        </div>
      </div>
    </template>
    <template v-else>
      <header class="source-preview-title">
        <strong class="meta-name" :title="title">{{ title }}</strong>
        <small v-if="matrix">{{
          matrix.shape.map((value) => value.toLocaleString()).join(" × ")
        }}</small>
      </header>
      <section class="preview-section source-files">
        <button
          type="button"
          class="section-toggle"
          :aria-expanded="!filesCollapsed"
          :aria-controls="`source-preview-${sourceDomId}-files`"
          @click="filesCollapsed = !filesCollapsed"
        >
          <span class="section-title">
            <i :class="['pi', filesCollapsed ? 'pi-chevron-right' : 'pi-chevron-down']"></i>
            <span>Files</span>
          </span>
          <small class="section-summary">{{ filesSummary }}</small>
        </button>
        <div
          :id="`source-preview-${sourceDomId}-files`"
          v-show="!filesCollapsed"
          class="section-body"
        >
          <div v-if="previewFiles.length" class="preview-files-list">
            <div v-for="file in previewFiles" :key="file.key" class="preview-file-row">
              <span class="preview-file-name" :title="file.name">{{ file.name }}</span>
              <span class="preview-file-extension">{{ file.extension }}</span>
            </div>
          </div>
          <div v-else class="preview-files-empty">
            <span>No source file metadata is available for this dataset.</span>
          </div>
        </div>
      </section>
      <section v-if="csvPlan" class="preview-section source-csv">
        <button
          type="button"
          class="section-toggle"
          :aria-expanded="!csvCollapsed"
          :aria-controls="`source-preview-${sourceDomId}-csv`"
          @click="csvCollapsed = !csvCollapsed"
        >
          <span class="section-title">
            <i :class="['pi', csvCollapsed ? 'pi-chevron-right' : 'pi-chevron-down']"></i>
            <span>CSV Inspector</span>
          </span>
          <small class="section-summary">{{ csvSummary }}</small>
        </button>
        <div
          :id="`source-preview-${sourceDomId}-csv`"
          v-show="!csvCollapsed"
          class="section-body csv-inspector-body"
        >
          <div v-if="csvLayoutOptions.length" class="field csv-layout-field">
            <label>CSV interpretation</label>
            <Dropdown
              v-model="localOverrides.csv_layout"
              :options="csvLayoutOptions"
              optionLabel="label"
              optionValue="value"
            />
            <small>
              This supplier-neutral interpretation is saved with the source and reused by previews,
              workflows, exports, and imports.
            </small>
          </div>
          <div class="csv-readout-grid">
            <div class="readout">
              <div class="readout-title">Layout</div>
              <dl>
                <div>
                  <dt>Shape</dt>
                  <dd>{{ csvPlan.layout_label || csvPlan.layout }}</dd>
                </div>
                <div>
                  <dt>Roles</dt>
                  <dd>{{ csvPlan.role_sequence || "n/a" }}</dd>
                </div>
                <div>
                  <dt>Result</dt>
                  <dd>{{ csvResultShape }}</dd>
                </div>
              </dl>
            </div>
            <div class="readout">
              <div class="readout-title">Feature Definition</div>
              <dl>
                <div>
                  <dt>X axis</dt>
                  <dd>{{ csvAxisLabel }}</dd>
                </div>
                <div>
                  <dt>Target</dt>
                  <dd>{{ csvTargetLabel }}</dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>
                    <span :class="['csv-confidence', `confidence-${csvPlan.confidence}`]">
                      {{ csvPlan.confidence }}
                    </span>
                  </dd>
                </div>
              </dl>
            </div>
          </div>
          <div v-if="csvPlan.warnings?.length" class="csv-warnings">
            <div v-for="warning in csvPlan.warnings" :key="warning" class="csv-warning-row">
              <i class="pi pi-exclamation-triangle"></i>
              <span>{{ warning }}</span>
            </div>
          </div>
          <div v-if="csvPlan.columns?.length" class="csv-column-roles">
            <div v-for="column in csvPlan.columns" :key="column.name" class="csv-column-role">
              <span :class="['csv-role-badge', `role-${column.role}`]">{{ column.role }}</span>
              <span class="csv-column-name" :title="column.reason || column.name">{{
                column.name
              }}</span>
            </div>
          </div>
          <small v-if="csvPlan.columns?.length" class="csv-role-legend">
            Admitted mapping: I identity · W coordinate · F model feature · P reference property ·
            M sample metadata · T explicit target. Only F columns contribute to the displayed
            feature count.
          </small>
        </div>
      </section>
      <section class="preview-section source-meta">
        <button
          type="button"
          class="section-toggle"
          :aria-expanded="!metaCollapsed"
          :aria-controls="`source-preview-${sourceDomId}-metadata`"
          @click="metaCollapsed = !metaCollapsed"
        >
          <span class="section-title">
            <i :class="['pi', metaCollapsed ? 'pi-chevron-right' : 'pi-chevron-down']"></i>
            <span>Metadata</span>
          </span>
          <small class="section-summary">Editable labels and target settings</small>
        </button>
        <div
          :id="`source-preview-${sourceDomId}-metadata`"
          v-show="!metaCollapsed"
          class="section-body"
        >
          <div class="source-meta-grid">
            <div v-if="matrix" class="readout">
              <div class="readout-title">Matrix</div>
              <dl>
                <div>
                  <dt>Missing</dt>
                  <dd>{{ matrix.stats.summary.total_missing_pct.toFixed(2) }}%</dd>
                </div>
                <div>
                  <dt>Mean</dt>
                  <dd>{{ formatStat(matrix.stats.summary.global_mean) }}</dd>
                </div>
                <div>
                  <dt>Range</dt>
                  <dd>
                    {{ formatStat(matrix.stats.summary.global_min) }} to
                    {{ formatStat(matrix.stats.summary.global_max) }}
                  </dd>
                </div>
              </dl>
            </div>
            <div v-if="matrix?.target" class="readout">
              <div class="readout-title">Target</div>
              <dl>
                <div>
                  <dt>Name</dt>
                  <dd>{{ matrix.target.target_name || "Label" }}</dd>
                </div>
                <div>
                  <dt>Type</dt>
                  <dd>{{ matrix.target.target_type || "auto" }}</dd>
                </div>
                <div v-if="matrix.target.n_classes">
                  <dt>Classes</dt>
                  <dd>{{ matrix.target.n_classes }}</dd>
                </div>
              </dl>
              <div v-if="matrix.target.classes?.length" class="class-list">
                <div
                  v-for="item in matrix.target.classes"
                  :key="`${item.value}-${item.label}`"
                  class="class-row"
                >
                  <span class="class-code">{{ item.value }}</span>
                  <span class="class-label">{{ item.label }}</span>
                  <span class="class-count">{{ item.count.toLocaleString() }}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="metadata-edit-grid">
            <div class="field">
              <label>Title</label>
              <InputText v-model="localOverrides.title" />
            </div>
            <div class="field">
              <label>X title</label>
              <InputText v-model="localOverrides.x_title" />
            </div>
            <div class="field">
              <label>X units</label>
              <InputText v-model="localOverrides.x_units" />
            </div>
            <div class="field">
              <label>Y title</label>
              <InputText v-model="localOverrides.y_title" />
            </div>
            <div class="field">
              <label>Data role</label>
              <Dropdown
                v-model="localOverrides.data_role"
                :options="dataRoleOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="Choose target type"
              />
              <small class="field-help">Required before using a supervised analysis starter.</small>
            </div>
            <div class="field">
              <label>Target column</label>
              <InputText v-model="localOverrides.target_column" placeholder="Optional" />
            </div>
            <div class="field">
              <label>Target type</label>
              <Dropdown
                v-model="localOverrides.target_type"
                :options="targetTypeOptions"
                optionLabel="label"
                optionValue="value"
              />
            </div>
          </div>
        </div>
      </section>
      <section class="preview-section source-content">
        <button
          type="button"
          class="section-toggle"
          :aria-expanded="!dataCollapsed"
          :aria-controls="`source-preview-${sourceDomId}-matrix`"
          @click="dataCollapsed = !dataCollapsed"
        >
          <span class="section-title">
            <i :class="['pi', dataCollapsed ? 'pi-chevron-right' : 'pi-chevron-down']"></i>
            <span>Data Matrix / Stats</span>
          </span>
          <small v-if="matrix?.truncated && !isNdPreview" class="section-summary">
            Showing {{ matrix.rows_shown.toLocaleString() }} x
            {{ matrix.cols_shown.toLocaleString() }}
          </small>
        </button>
        <div
          :id="`source-preview-${sourceDomId}-matrix`"
          v-show="!dataCollapsed"
          class="section-body"
        >
          <div
            v-if="!isNdPreview"
            class="preview-mode-row"
            role="radiogroup"
            aria-label="Preview display mode"
          >
            <label
              v-for="option in viewOptions"
              :key="option.value"
              class="preview-mode-option"
              :for="`source-preview-${sourceDomId}-${option.value}`"
            >
              <input
                v-model="viewMode"
                type="radio"
                :id="`source-preview-${sourceDomId}-${option.value}`"
                :name="`source-preview-view-mode-${sourceDomId}`"
                :value="option.value"
              />
              <span>{{ option.label }}</span>
            </label>
          </div>
          <div v-if="matrix?.truncated && !isNdPreview" class="preview-toolbar-note">
            <span class="truncate-note">
              Showing {{ matrix.rows_shown.toLocaleString() }} x
              {{ matrix.cols_shown.toLocaleString() }} of {{ matrix.total_rows.toLocaleString() }} x
              {{ matrix.total_cols.toLocaleString() }}.
            </span>
          </div>
          <div v-if="loading" class="preview-loading">
            <ProgressSpinner style="width: 24px; height: 24px" />
            <span>Loading preview...</span>
          </div>
          <div v-else-if="error" class="preview-error">
            <i class="pi pi-exclamation-triangle"></i>
            <span>{{ error }}</span>
          </div>
          <div v-else-if="matrix && isNdPreview" class="nd-preview-notice" role="status">
            <i class="pi pi-box"></i>
            <div>
              <strong>Native {{ matrix.rank }}-D dataset</strong>
              <p>{{ matrix.projection_message }}</p>
              <dl>
                <div v-for="(size, index) in matrix.shape" :key="index">
                  <dt>{{ matrix.dimension_roles?.[index] || `dimension ${index}` }}</dt>
                  <dd>{{ size.toLocaleString() }}</dd>
                </div>
              </dl>
            </div>
          </div>
          <DataStatsTable v-else-if="matrix && viewMode === 'stats'" :matrix="matrix" />
          <DataMatrixGrid v-else-if="matrix" :matrix="matrix" />
        </div>
      </section>
      <section class="preview-section source-plot">
        <div class="section-heading">
          <span class="section-title">
            <i class="pi pi-chart-line"></i>
            <span>Graph</span>
          </span>
        </div>
        <div v-if="loading" class="preview-loading">
          <ProgressSpinner style="width: 24px; height: 24px" />
          <span>Loading preview...</span>
        </div>
        <div v-else-if="error" class="preview-error">
          <i class="pi pi-exclamation-triangle"></i>
          <span>{{ error }}</span>
        </div>
        <PlotlyChart
          v-else-if="matrix && previewPlotData.length"
          :data="previewPlotData"
          :layout="previewPlotLayout"
          :config="plotConfig"
        />
        <div v-else class="plot-empty">
          <i class="pi pi-chart-line"></i>
          <span v-if="isNdPreview"
            >Project explicit inner dimensions before requesting a 2-D graph.</span
          >
          <span v-else>No numeric preview plot is available for this source.</span>
        </div>
        <p v-if="previewScope" class="plot-population-disclosure" role="status">
          {{ previewScope }}
        </p>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from "vue";
import InputText from "primevue/inputtext";
import Dropdown from "primevue/dropdown";
import ProgressSpinner from "primevue/progressspinner";
import { getErrorMessage } from "@/utils/errors";
import { shouldReverseFeatureAxis } from "@/utils/plotLabels";
import {
  useDataStore,
  type CsvImportPlan,
  type DataMatrixRef,
  type DataMatrixResponse,
  type PreparedDataOverrides,
} from "@/stores/data";
import PlotlyChart from "@/components/PlotlyChart.vue";
import DataMatrixGrid from "./DataMatrixGrid.vue";
import DataStatsTable from "./DataStatsTable.vue";

const props = defineProps<{
  sourceRef: DataMatrixRef | null;
  title?: string;
  overrides?: PreparedDataOverrides;
  files?: SourcePreviewFile[];
  csvPlan?: CsvImportPlan | null;
  acquisitionRequired?: boolean;
}>();
const emit = defineEmits<{ "update:overrides": [PreparedDataOverrides] }>();

interface SourcePreviewFile {
  name: string;
  extension?: string | null;
}

const dataStore = useDataStore();
const matrix = ref<DataMatrixResponse | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const filesCollapsed = ref(false);
const csvCollapsed = ref(true);
const metaCollapsed = ref(true);
const dataCollapsed = ref(true);
const viewMode = ref<"matrix" | "stats">("matrix");
const viewOptions: { label: string; value: "matrix" | "stats" }[] = [
  { label: "Matrix", value: "matrix" },
  { label: "Stats", value: "stats" },
];
const PLOT_COLORS = [
  "#2563eb",
  "#dc2626",
  "#16a34a",
  "#d97706",
  "#7c3aed",
  "#db2777",
  "#0891b2",
  "#ea580c",
  "#0d9488",
  "#4f46e5",
];
const plotConfig = { responsive: true, displaylogo: false, displayModeBar: true };
const dataRoleOptions = [
  { label: "Spectra", value: "X_spectra" },
  { label: "Feature table", value: "X_features" },
];
const targetTypeOptions = [
  // Legacy prepared data may still report an inferred "auto" type, but new
  // supervised selections must state their target semantics explicitly.
  { label: "Categorical", value: "categorical" },
  { label: "Continuous", value: "continuous" },
];
const localOverrides = reactive<PreparedDataOverrides>({
  title: "",
  x_title: "",
  x_units: "",
  y_title: "",
  data_role: "",
  target_column: "",
  target_type: "",
  is_time_series: false,
  csv_layout: "",
});

const title = computed(() => props.title || "Dataset preview");
const isNdPreview = computed(() => matrix.value?.kind === "nd_dataset");
const previewFiles = computed(() =>
  (props.files ?? [])
    .map((file, index) => {
      const name = file.name.trim();
      if (!name) return null;
      return {
        key: `${name}-${index}`,
        name,
        extension: normalizeExtension(file.extension ?? extensionFromName(name)),
      };
    })
    .filter((file): file is { key: string; name: string; extension: string } => file !== null),
);
const filesSummary = computed(() => {
  const count = previewFiles.value.length;
  if (count === 0) return "No file metadata";
  if (count === 1) return "1 file";
  return `${count.toLocaleString()} files`;
});
const csvPlan = computed(() => props.csvPlan ?? null);
const csvLayoutOptions = computed(() => csvPlan.value?.layout_options ?? []);
const csvSummary = computed(() => {
  const plan = csvPlan.value;
  if (!plan) return "";
  const confidence = plan.confidence ? `${plan.confidence} confidence` : "review";
  return `${plan.layout_label || plan.layout} · ${confidence}`;
});
const csvResultShape = computed(() => {
  const shape = csvPlan.value?.shape;
  if (!shape) return "n/a";
  const samples = shape.samples ?? shape.rows;
  const features = shape.features ?? shape.columns;
  if (samples === null || samples === undefined || features === null || features === undefined)
    return "n/a";
  return `${samples.toLocaleString()} samples x ${features.toLocaleString()} features`;
});
const csvAxisLabel = computed(() => {
  const axis = csvPlan.value?.axis;
  if (!axis) return "not detected";
  const title = axis.title || "";
  const units = axis.units ? ` (${axis.units})` : "";
  const column = axis.column ? ` · ${axis.column}` : "";
  return `${title}${units}${column}` || "not detected";
});
const csvTargetLabel = computed(() => {
  const target = csvPlan.value?.target;
  if (!target?.column) return "none";
  return target.type ? `${target.column} · ${target.type}` : target.column;
});
const sourceIdentity = computed(() => {
  const source = props.sourceRef;
  if (!source) return "";
  if (source.kind === "reference") return `reference:${source.source}:${source.name}`;
  if (source.kind === "staged") return `staged:${source.staging_id}:${source.asset_id ?? "auto"}`;
  return `experiment_file:${source.experiment_id}:${source.file_id}:${source.asset_id ?? "auto"}`;
});
const sourceDomId = computed(
  () => sourceIdentity.value.replace(/[^A-Za-z0-9_-]+/g, "-") || "empty",
);
const matrixRequestSignature = computed(() => {
  const overrides = props.sourceRef?.overrides ?? props.overrides ?? {};
  return JSON.stringify({
    source: sourceIdentity.value,
    data_role: overrides?.data_role ?? null,
    target_column: overrides?.target_column ?? null,
    target_type: overrides?.target_type ?? null,
    is_time_series: overrides?.is_time_series ?? null,
    csv_layout: overrides?.csv_layout ?? null,
  });
});

let suppressLocalOverrideEmit = false;
let localOverrideSyncRun = 0;
let matrixFetchRun = 0;
let lastFetchedSourceIdentity = "";
type TextOverrideKey = "title" | "x_title" | "x_units" | "y_title" | "data_role" | "target_column";

function hasOwnOverride(key: keyof PreparedDataOverrides): boolean {
  return Object.prototype.hasOwnProperty.call(props.overrides ?? {}, key);
}

function matrixFallbackForOverride(key: TextOverrideKey): string {
  const current = matrix.value;
  if (!current) return "";
  if (key === "x_title") return current.x_title ?? "";
  if (key === "x_units") return current.x_units ?? "";
  if (key === "y_title") return current.y_title ?? "";
  if (key === "data_role") return current.data_role ?? "";
  return "";
}

function resolvedTextOverride(key: TextOverrideKey, fallback = ""): string {
  const overrides = props.overrides;
  if (overrides && Object.prototype.hasOwnProperty.call(overrides, key)) {
    const value = overrides[key];
    return typeof value === "string" ? value : "";
  }
  return fallback;
}

function addTextOverride(
  overrides: PreparedDataOverrides,
  key: TextOverrideKey,
  value: unknown,
): void {
  const text = typeof value === "string" ? value : "";
  const trimmed = text.trim();
  if (trimmed) {
    overrides[key] = trimmed;
    return;
  }
  if (hasOwnOverride(key) || matrixFallbackForOverride(key).trim()) {
    overrides[key] = "";
  }
}

function setLocalOverrides(next: PreparedDataOverrides | undefined) {
  const syncRun = ++localOverrideSyncRun;
  suppressLocalOverrideEmit = true;
  Object.assign(localOverrides, {
    title: next?.title ?? "",
    x_title: next?.x_title ?? "",
    x_units: next?.x_units ?? "",
    y_title: next?.y_title ?? "",
    data_role: next?.data_role ?? "",
    target_column: next?.target_column ?? "",
    target_type: next?.target_type ?? "",
    is_time_series: next?.is_time_series ?? false,
    csv_layout: next?.csv_layout ?? props.csvPlan?.recommended_layout ?? "",
  });
  nextTick(() => {
    if (syncRun === localOverrideSyncRun) {
      suppressLocalOverrideEmit = false;
    }
  });
}

watch(
  () => props.overrides,
  (next) => {
    setLocalOverrides(next);
  },
  { immediate: true, deep: true },
);

watch(
  localOverrides,
  () => {
    if (suppressLocalOverrideEmit) return;
    const overrides: PreparedDataOverrides = {};
    addTextOverride(overrides, "title", localOverrides.title);
    addTextOverride(overrides, "x_title", localOverrides.x_title);
    addTextOverride(overrides, "x_units", localOverrides.x_units);
    addTextOverride(overrides, "y_title", localOverrides.y_title);
    addTextOverride(overrides, "data_role", localOverrides.data_role);
    addTextOverride(overrides, "target_column", localOverrides.target_column);
    if (localOverrides.target_type && localOverrides.target_type !== "auto") {
      overrides.target_type = localOverrides.target_type;
    }
    if (localOverrides.is_time_series || hasOwnOverride("is_time_series")) {
      overrides.is_time_series = Boolean(localOverrides.is_time_series);
    }
    if (localOverrides.csv_layout) {
      overrides.csv_layout = localOverrides.csv_layout;
    }
    emit("update:overrides", overrides);
  },
  { deep: true },
);

watch(
  matrixRequestSignature,
  async () => {
    const fetchRun = ++matrixFetchRun;
    const identityChanged = sourceIdentity.value !== lastFetchedSourceIdentity;
    if (identityChanged) matrix.value = null;
    error.value = null;
    const next = props.sourceRef;
    if (!next) return;
    loading.value = true;
    try {
      const fetched = await dataStore.fetchDataMatrix(next);
      if (fetchRun !== matrixFetchRun) return;
      matrix.value = fetched;
      lastFetchedSourceIdentity = sourceIdentity.value;
      setLocalOverrides({
        ...props.overrides,
        x_title: resolvedTextOverride("x_title", matrix.value.x_title || ""),
        x_units: resolvedTextOverride("x_units", matrix.value.x_units || ""),
        y_title: resolvedTextOverride("y_title", matrix.value.y_title || ""),
        data_role: resolvedTextOverride("data_role", matrix.value.data_role || ""),
      });
    } catch (err: unknown) {
      if (fetchRun !== matrixFetchRun) return;
      error.value = getErrorMessage(err, "Could not load data preview");
    } finally {
      if (fetchRun === matrixFetchRun) {
        loading.value = false;
      }
    }
  },
  { immediate: true },
);

function formatStat(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toPrecision(5) : "";
}

function extensionFromName(name: string): string | null {
  const baseName = name.split(/[\\/]/).pop() ?? name;
  const match = baseName.match(/\.([^.]+)$/);
  return match ? match[1] : null;
}

function normalizeExtension(extension: string | null | undefined): string {
  const cleaned = extension?.replace(/^\./, "").trim().toLowerCase();
  return cleaned || "none";
}

function numericCell(value: number | string | null): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function axisValues(labels: string[], count: number): Array<number | string> {
  if (labels.length >= count) {
    const numeric = labels.slice(0, count).map((label) => Number(label));
    if (numeric.every((value) => Number.isFinite(value))) return numeric;
    return labels.slice(0, count);
  }
  return Array.from({ length: count }, (_, idx) => idx);
}

const previewPlotData = computed(() => {
  const current = matrix.value;
  if (!current?.matrix.length || !current.cols_shown) return [];
  if (current.is_spectra || current.data_role === "X_spectra") {
    const x = axisValues(current.col_labels, current.cols_shown);
    const maxTraces = Math.min(current.matrix.length, 50);
    return current.matrix.slice(0, maxTraces).map((row, idx) => ({
      x,
      y: row.slice(0, current.cols_shown).map(numericCell),
      type: "scatter",
      mode: "lines",
      name: current.row_labels[idx] || `Sample ${current.row_start + idx + 1}`,
      line: { color: PLOT_COLORS[idx % PLOT_COLORS.length], width: 1.2 },
      connectgaps: false,
    }));
  }

  const maxColumns = Math.min(current.cols_shown, 40);
  return current.col_labels.slice(0, maxColumns).map((label, colIdx) => ({
    type: "box",
    y: current.matrix
      .map((row) => numericCell(row[colIdx] ?? null))
      .filter((value): value is number => value !== null),
    name: `${label || `Feature ${current.col_start + colIdx + 1}`} (n=${current.matrix.filter((row) => numericCell(row[colIdx] ?? null) !== null).length})`,
    marker: { color: PLOT_COLORS[colIdx % PLOT_COLORS.length] },
    boxpoints: false,
    meta: {
      finite_count: current.matrix.filter((row) => numericCell(row[colIdx] ?? null) !== null)
        .length,
    },
  }));
});

const previewScope = computed(() => {
  const current = matrix.value;
  if (!current || isNdPreview.value || !current.matrix.length) return "";
  const spectral = current.is_spectra || current.data_role === "X_spectra";
  const shownRows = spectral ? Math.min(current.matrix.length, 50) : current.matrix.length;
  const shownCols = spectral ? current.cols_shown : Math.min(current.cols_shown, 40);
  const cells = current.matrix.slice(0, shownRows).flatMap((row) => row.slice(0, shownCols));
  const missing = cells.filter((value) => numericCell(value) === null).length;
  return (
    `Plot shows first ${shownRows} of ${current.matrix.length} available preview rows and first ${shownCols} of ${current.cols_shown} preview features (${current.total_rows} source rows, ${current.total_cols} source features). ` +
    (spectral
      ? `${missing} missing/nonfinite cells remain gaps; no interpolation.`
      : `${cells.length - missing} finite values across displayed features; ${missing} missing/nonfinite cells omitted from distributions. Each feature uses its own finite-value count.`)
  );
});

const previewPlotLayout = computed(() => {
  const current = matrix.value;
  const xTitle = localOverrides.x_title || current?.x_title || "";
  const xUnits = localOverrides.x_units || current?.x_units || "";
  const yTitle = localOverrides.y_title || current?.y_title || "";
  const isSpectra = !!current && (current.is_spectra || current.data_role === "X_spectra");
  return {
    title: { text: isSpectra ? "Spectra Preview" : "Feature Distributions", font: { size: 14 } },
    xaxis: {
      title: xUnits ? `${xTitle} (${xUnits})` : xTitle,
      autorange: shouldReverseFeatureAxis({
        title: xTitle,
        units: xUnits,
        quantity: current?.x_quantity ?? undefined,
      })
        ? "reversed"
        : true,
    },
    yaxis: { title: yTitle },
    autosize: true,
    height: 340,
    margin: { t: 42, r: 20, b: 58, l: 62 },
    showlegend: isSpectra && previewPlotData.value.length <= 20,
    legend: { font: { size: 10 }, orientation: "h", y: -0.28 },
    plot_bgcolor: "#fafafa",
    paper_bgcolor: "#ffffff",
  };
});
</script>

<style scoped>
.source-preview {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-height: 0;
}

.preview-empty,
.preview-loading,
.preview-error {
  min-height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  color: var(--text-color-secondary);
  border: 1px dashed var(--surface-border);
  border-radius: 6px;
}

.preview-error {
  color: var(--red-600);
}

.preview-acquisition {
  align-items: flex-start;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  color: var(--text-color-secondary);
  display: flex;
  gap: 0.75rem;
  padding: 1rem;
}

.preview-acquisition > i {
  color: var(--primary-color);
  font-size: 1.1rem;
  margin-top: 0.1rem;
}

.preview-acquisition > div {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.preview-acquisition strong {
  color: var(--text-color);
}

.source-preview-title {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
  padding-bottom: 0.65rem;
  border-bottom: 1px solid var(--surface-border);
}

.source-preview-title small,
.section-summary,
.truncate-note {
  color: var(--text-color-secondary);
  font-size: 0.8rem;
}

.preview-section {
  min-width: 0;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  background: var(--surface-card);
}

.section-toggle,
.section-heading {
  width: 100%;
  min-height: 2.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.55rem 0.75rem;
  border: none;
  border-radius: 6px 6px 0 0;
  background: var(--surface-ground);
  color: var(--text-color);
  text-align: left;
}

.section-toggle {
  cursor: pointer;
}

.section-toggle:hover {
  background: color-mix(in srgb, var(--surface-ground) 82%, var(--primary-color) 18%);
}

.section-title {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
  font-weight: 700;
  font-size: 0.86rem;
}

.section-title i {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

.section-summary {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.section-body {
  padding: 0.75rem;
}

.source-meta .field {
  margin-bottom: 0;
}

.source-meta label {
  display: block;
  font-size: 0.78rem;
  color: var(--text-color-secondary);
  margin-bottom: 0.25rem;
}

.source-meta :deep(.p-inputtext),
.source-meta :deep(.p-dropdown) {
  width: 100%;
}

.field-help {
  display: block;
  margin-top: 0.25rem;
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

/* Long single-token filenames must wrap inside the meta column instead of
   overflowing across the grid gap onto the Matrix/Stats toggle. */
.meta-name {
  font-weight: 700;
  overflow-wrap: anywhere;
  word-break: break-word;
  min-width: 0;
}

.readout {
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  padding: 0.7rem;
  background: var(--surface-ground);
}

.source-meta-grid,
.metadata-edit-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}

.metadata-edit-grid {
  margin-top: 0.75rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.readout-title {
  font-weight: 700;
  font-size: 0.82rem;
  margin-bottom: 0.5rem;
}

.readout dl {
  margin: 0;
  display: grid;
  gap: 0.45rem;
}

.readout dl > div {
  display: grid;
  grid-template-columns: minmax(72px, 0.42fr) minmax(0, 1fr);
  gap: 0.5rem;
}

.readout dt {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

.readout dd {
  margin: 0;
  font-size: 0.82rem;
  min-width: 0;
  overflow-wrap: anywhere;
}

.preview-files-list {
  display: grid;
  gap: 0.45rem;
  max-height: 14rem;
  overflow-y: auto;
  padding-right: 0.25rem;
}

.preview-file-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.65rem;
  min-width: 0;
  padding: 0.45rem 0;
  border-bottom: 1px solid var(--surface-border);
}

.preview-file-row:last-child {
  border-bottom: none;
}

.preview-file-name {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 0.84rem;
}

.preview-file-extension {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 3.25rem;
  padding: 0.15rem 0.45rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  background: var(--surface-ground);
  color: var(--text-color-secondary);
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
}

.preview-files-empty {
  color: var(--text-color-secondary);
  font-size: 0.82rem;
}

.csv-inspector-body {
  display: grid;
  gap: 0.75rem;
}

.csv-readout-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}

.csv-confidence {
  text-transform: capitalize;
  font-weight: 700;
}

.confidence-high {
  color: var(--green-600);
}

.confidence-medium {
  color: var(--orange-600);
}

.confidence-low {
  color: var(--red-600);
}

.csv-warnings {
  display: grid;
  gap: 0.4rem;
}

.csv-warning-row {
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  color: var(--orange-700);
  font-size: 0.8rem;
}

.csv-column-roles {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.csv-column-role {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  max-width: 100%;
  padding: 0.2rem 0.45rem 0.2rem 0.25rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  background: var(--surface-ground);
  font-size: 0.76rem;
}

.csv-role-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.3rem;
  height: 1.3rem;
  border-radius: 4px;
  color: #ffffff;
  font-weight: 800;
  font-size: 0.68rem;
}

.role-I {
  background: #475569;
}

.role-W {
  background: #4f46e5;
}

.role-F {
  background: #0891b2;
}

.role-P {
  background: #7c3aed;
}

.role-M {
  background: #0f766e;
}

.role-T {
  background: #b45309;
}

.role-E,
.role-\? {
  background: #94a3b8;
}

.csv-column-name {
  min-width: 0;
  max-width: 15rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.csv-role-legend {
  color: var(--text-color-secondary);
  line-height: 1.4;
}

.class-list {
  margin-top: 0.65rem;
  display: grid;
  gap: 0.35rem;
}

.class-row {
  display: grid;
  grid-template-columns: 2.5rem minmax(0, 1fr) auto;
  gap: 0.45rem;
  align-items: center;
  font-size: 0.8rem;
}

.class-code {
  font-variant-numeric: tabular-nums;
  color: var(--text-color-secondary);
}

.class-label {
  min-width: 0;
  overflow-wrap: anywhere;
}

.class-count {
  color: var(--text-color-secondary);
  font-variant-numeric: tabular-nums;
}

.source-content {
  min-width: 0;
}

.source-plot {
  min-width: 0;
  overflow: hidden;
}

.source-plot > :not(.section-heading) {
  margin: 0.75rem;
}

.plot-empty {
  min-height: 180px;
  border: 1px dashed var(--surface-border);
  border-radius: 6px;
  color: var(--text-color-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.nd-preview-notice {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.9rem;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  background: var(--surface-ground);
}

.nd-preview-notice p {
  margin: 0.3rem 0 0.7rem;
  color: var(--text-color-secondary);
}

.nd-preview-notice dl {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
  gap: 0.45rem;
  margin: 0;
}

.nd-preview-notice dl div {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
  background: var(--surface-card);
}

.nd-preview-notice dt {
  color: var(--text-color-secondary);
}

.nd-preview-notice dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}

.preview-mode-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.9rem;
  width: 100%;
  margin-bottom: 0.5rem;
}

.preview-mode-option {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.86rem;
  cursor: pointer;
  color: var(--text-color);
  white-space: nowrap;
}

.preview-mode-option input {
  margin: 0;
}

.preview-toolbar-note {
  width: 100%;
  margin-bottom: 0.75rem;
}

@media (max-width: 900px) {
  .source-meta-grid,
  .metadata-edit-grid,
  .csv-readout-grid {
    grid-template-columns: 1fr;
  }
}
</style>
