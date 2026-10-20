<template>
  <Dialog
    v-model:visible="visible"
    modal
    :header="isPls ? 'PLS diagnostic workbench' : 'PCA diagnostic workbench'"
    :style="{ width: '95vw', maxWidth: '1500px' }"
  >
    <section :aria-label="isPls ? 'PLS sample review' : 'PCA sample review'" class="pca-review">
      <p>
        Review calibration samples in this analysis. Marking does not exclude them. Exclusion refits
        preprocessing and the model; it does not edit My Dataset or existing optimization seeds.
      </p>
      <p v-if="error" role="alert" class="review-error">{{ error }}</p>
      <p v-if="busy" role="status">{{ progress }}</p>
      <template v-if="review">
        <p>
          Run {{ review.run_id }} · {{ review.n_calibration }} calibration samples ·
          {{ review.n_components }} components.
          <span v-if="!isPls">Limits: 95%; Q: {{ review.q_limit_method }}.</span>
          Screening after inspection is adaptive model development, not independent validation.
        </p>
        <p v-if="review.stale" role="alert">
          The graph has changed or the run is incomplete. Rerun before new exclusions. The plots
          below belong to run {{ review.run_id }}.
        </p>
        <div class="review-controls">
          <label v-if="!isPls"
            >X component
            <select v-model.number="xComponent">
              <option v-for="i in review.n_components" :key="i" :value="i - 1">PC {{ i }}</option>
            </select></label
          >
          <label v-if="!isPls"
            >Y component
            <select v-model.number="yComponent">
              <option v-for="i in review.n_components" :key="i" :value="i - 1">PC {{ i }}</option>
            </select></label
          >
          <label v-if="isPls"
            >Response
            <select v-model.number="targetIndex">
              <option v-for="(name, i) in review.target_names" :key="name" :value="i">
                {{ name }} {{ review.target_units?.[i] || "" }}
              </option>
            </select>
          </label>
          <button type="button" @click="selected = []">Clear selection</button>
          <button
            type="button"
            :disabled="busy || store.hasUnsavedChanges || store.isExecuting"
            @click="rerun"
          >
            Rerun current workflow
          </button>
        </div>
        <section
          v-if="isPls && review.full_test_statistics"
          aria-label="Held-out validation metrics"
        >
          <p>
            <strong v-if="review.state.post_review">Post-review analysis.</strong> Full-test metrics
            include every original held-out observation, including review omissions. Test review
            never refits the model or changes workflow predictions. A lower subset RMSEP is not
            independent evidence of improvement.
          </p>
          <table>
            <caption>
              Response:
              {{
                review.target_names?.[targetIndex]
              }}
              — RMSE / RMSEP
            </caption>
            <thead>
              <tr>
                <th>Population</th>
                <th>Count</th>
                <th>RMSE</th>
                <th>R²</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in metricRows" :key="item.label">
                <td>{{ item.label }}</td>
                <td>{{ item.metrics?.n_samples ?? "—" }}</td>
                <td>{{ number(item.metrics?.rmse ?? null) }}</td>
                <td>{{ number(item.metrics?.r2 ?? null) }}</td>
              </tr>
            </tbody>
          </table>
          <p>
            {{ review.state.heldout_excluded?.length || 0 }} original test observations omitted only
            from the post-review subset. Baseline run:
            {{ review.state.test_baseline?.run_id || review.run_id }}.
          </p>
        </section>
        <DiagnosticAdvisor
          :review="review"
          :workflow-id="store.workflowId"
          :node-id="props.nodeId"
          :selected="selected"
          :variables="advisorVariables"
          :response-index="targetIndex"
          :variable-response-index="advisorResponse ?? targetIndex"
          :focused-sample="advisorSample"
          :variable-context="advisorVariableContext"
          :stale="review.stale || store.hasUnsavedChanges || store.isExecuting"
          @opened="visible = false"
        />
        <div class="review-plots">
          <PlotlyChart
            :data="scoreTraces"
            :layout="scoreLayout"
            :config="config"
            :selected-point-ids="selected"
            @selected="selectPoints"
            @deselect="selected = []"
          />
          <PlotlyChart
            :data="diagnosticTraces"
            :layout="diagnosticLayout"
            :config="config"
            :selected-point-ids="selected"
            @selected="selectPoints"
            @deselect="selected = []"
          />
        </div>
        <PlsApplicability
          v-if="isPls"
          :review="review"
          :selected="selected"
          :colors="groupColors"
          :response-index="targetIndex"
          :stale="review.stale || store.hasUnsavedChanges || store.isExecuting"
          @selected="selectPoints"
          @deselect="selected = []"
          @advisor-selection="updateAdvisorSelection($event, 'applicability')"
        />
        <details
          :open="showExplanation"
          @toggle="showExplanation = ($event.target as HTMLDetailsElement).open"
        >
          <summary>
            Explain selected samples:
            {{ isPls ? "PLS predictions and fitted profiles" : "PCA contributions and loadings" }}
          </summary>
          <PlsExplanation
            @advisor-selection="updateAdvisorSelection($event, 'prediction')"
            v-if="showExplanation && isPls"
            :key="`${review.run_id}:${review.graph_digest}`"
            :evidence="review.pls_explanations"
            :selected="selected"
            :rows="review.rows"
            :run-id="review.run_id"
            :stale="review.stale || store.hasUnsavedChanges || store.isExecuting"
          />
          <PcaExplanation
            @advisor-selection="updateAdvisorSelection"
            v-if="showExplanation && !isPls"
            :key="`${review.run_id}:${review.explanations && 'model_digest' in review.explanations ? review.explanations.model_digest : ''}`"
            :evidence="review.explanations"
            :selected="selected"
            :rows="review.rows"
            :run-id="review.run_id"
            :components="review.n_components"
            :stale="review.stale || store.hasUnsavedChanges || store.isExecuting"
          />
        </details>
        <ReviewSpectra
          v-if="review.spectra"
          :key="`${store.workflowId}:${props.nodeId}`"
          :spectra="review.spectra"
          :rows="review.rows"
          :selected="selected"
          :marked="review.state.marked"
          :masked="review.state.heldout_excluded || []"
          :colors="groupColors"
          @selected="selectPoints"
          @deselect="selected = []"
        />
        <section v-if="isPls && review.preprocessing?.length" aria-label="Executed preprocessing">
          <h3>Executed preprocessing</h3>
          <p v-if="review.executed_split">
            Executed {{ review.executed_split.method }} split:
            {{ review.executed_split.n_train }} original calibration observations,
            {{ review.executed_split.n_test }} original held-out observations.
            <template v-if="review.executed_split.groups_content_digest">
              Bound to {{ review.executed_split.n_groups }} sample-table groups.
            </template>
          </p>
          <ol>
            <li v-for="step in review.preprocessing" :key="step.node_id">
              {{ step.operation }} · parameters: {{ displayParameters(step.parameters) }} ·
              {{
                step.fitting_population === "retained_calibration"
                  ? `fit on ${step.fitting_count} retained calibration observations`
                  : "applied per observation"
              }}.
              <span v-if="step.fitted_state_sha256">
                Saved fitted state: {{ step.fitted_state_sha256.slice(0, 12) }}.</span
              >
            </li>
          </ol>
          <p>
            <template
              v-if="
                review.heldout_ids?.length &&
                review.preprocessing.some((step) =>
                  ['preprocess.scale', 'preprocess.shared_reference_scale'].includes(
                    step.operation,
                  ),
                )
              "
            >
              The held-out branch uses the saved calibration fit.
            </template>
            Source curves are before this chain; model-input curves are after it.
          </p>
          <p v-if="review.spectra">
            Source space: {{ review.source_spectral_space || "Saved source input" }} · axis
            {{ review.spectra.units }} · signal {{ review.spectra.signal_units || "unspecified" }}.
            <template v-if="review.model_input_spectra && 'rows' in review.model_input_spectra">
              Model input: {{ review.model_input_spectra.space }} · axis
              {{ review.model_input_spectra.units }} · signal
              {{ review.model_input_spectra.signal_units || "unspecified" }}.
            </template>
          </p>
        </section>
        <ReviewSpectra
          v-if="isPls && review.model_input_spectra && 'rows' in review.model_input_spectra"
          :key="`${store.workflowId}:${props.nodeId}:model-input`"
          title="Linked model-input spectra"
          :spectra="review.model_input_spectra"
          :rows="review.rows"
          :selected="selected"
          :marked="review.state.marked"
          :masked="review.state.heldout_excluded || []"
          :colors="groupColors"
          @selected="selectPoints"
          @deselect="selected = []"
        />
        <p
          v-if="
            isPls &&
            review.model_input_spectra &&
            'unavailable_reason' in review.model_input_spectra
          "
        >
          Model-input curves unavailable: {{ review.model_input_spectra.unavailable_reason }}
          <template v-if="review.model_input_spectral_space">
            The executed model-input space was {{ review.model_input_spectral_space }}; axis
            {{ review.model_input_axis_units || "unspecified" }}, signal
            {{ review.model_input_signal_units || "unspecified" }}.
          </template>
        </p>
        <p v-if="isPls">
          Residual = reference − predicted. ○ Calibration · □ Held-out test · ◇ Scientist-marked
          outlier · × Excluded projection / omitted test subset. Colours preserve sample groups.
          Calibration fit is not validation.
        </p>
        <p v-else>
          ○ Calibration · ◇ Scientist-marked outlier · × Excluded — projected. Colour preserves
          sample group. Statistical screening is shown separately in the table. Dashed T² is the
          application limit for excluded projections; solid T² is the calibration limit.
        </p>
        <p role="status" aria-live="polite">
          {{ selected.length }} samples selected across charts and the table.
        </p>
        <label class="review-reason"
          >Scientific reason
          <input
            v-model="reason"
            maxlength="1000"
            placeholder="For example: high Q; inspect acquisition record"
        /></label>
        <div class="review-controls">
          <button type="button" :disabled="!canAct || review.stale" @click="apply('mark')">
            Mark as outlier
          </button>
          <button type="button" :disabled="!canAct || review.stale" @click="apply('unmark')">
            Clear outlier mark
          </button>
          <button
            type="button"
            :disabled="!canAct || review.stale || !activeSelected"
            @click="apply('exclude')"
          >
            Exclude from this analysis and rerun
          </button>
          <button type="button" :disabled="!canAct || !excludedSelected" @click="apply('restore')">
            Restore selected and rerun
          </button>
        </div>
        <div v-if="isPls && review.full_test_statistics" class="review-controls">
          <label
            ><input v-model="acknowledgePostReview" type="checkbox" /> I understand this is a
            post-review test subset, not independent validation.</label
          >
          <button
            type="button"
            :disabled="!canAct || review.stale || !testSelected || !acknowledgePostReview"
            @click="apply('exclude_test')"
          >
            Omit selected test observations from review subset
          </button>
          <button
            type="button"
            :disabled="!canAct || review.stale || !testSelected || !acknowledgePostReview"
            @click="apply('restore_test')"
          >
            Restore selected test observations to review subset
          </button>
        </div>
        <details v-if="curationSource">
          <summary>Dataset correction: Exclude from My Dataset</summary>
          <DatasetCurationPanel
            :source="curationSource"
            :seed-ids="selected"
            :disabled="busy || review.stale || store.hasUnsavedChanges || store.isExecuting"
            @applied="onCurationApplied"
          />
        </details>
        <p v-else>
          Dataset correction requires retained source-row identity. Rerun to enable Exclude from My
          Dataset.
        </p>
        <label>Find sample <input v-model="query" type="search" /></label>
        <label><input v-model="selectedOnly" type="checkbox" /> Selected only</label>
        <table>
          <caption>
            Linked sample review table —
            {{
              filteredRows.length
            }}
            observations
          </caption>
          <thead>
            <tr>
              <th>Select</th>
              <th>
                <button type="button" @click="descending = !descending">
                  Sample {{ descending ? "↓" : "↑" }}
                </button>
              </th>
              <th>Group</th>
              <th>Role / decision</th>
              <th>{{ isPls ? "Reference" : "T²" }}</th>
              <th>{{ isPls ? "Predicted" : "Q" }}</th>
              <th>{{ isPls ? "Residual (reference − predicted)" : "Screening / projection" }}</th>
              <template v-if="isPls && review.pls_applicability">
                <th>T² predictor distance</th>
                <th>Q predictor residual</th>
                <th>Predictor screening</th>
              </template>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in pageRows"
              :key="row.id"
              :class="{
                selected: selectedSet.has(row.id),
                excluded: row.role === 'excluded_projected',
              }"
            >
              <td>
                <input
                  type="checkbox"
                  :aria-label="`Select sample ${row.id}`"
                  :checked="selectedSet.has(row.id)"
                  @change="toggle(row.id)"
                />
              </td>
              <td>{{ row.id }}</td>
              <td :style="{ color: groupColors.get(row.group) }">{{ row.group }}</td>
              <td>{{ roleLabel(row) }}{{ marked.has(row.id) ? " · ◇ Marked outlier" : "" }}</td>
              <td>{{ number(isPls ? (row.reference?.[targetIndex] ?? null) : row.t2) }}</td>
              <td>{{ number(isPls ? (row.predicted?.[targetIndex] ?? null) : row.q) }}</td>
              <td>
                {{
                  isPls
                    ? row.projection_error || number(row.residual?.[targetIndex] ?? null)
                    : row.projection_error || (row.screened ? "Above calibration limit" : "—")
                }}
              </td>
              <template v-if="isPls && review.pls_applicability">
                <td>{{ number(row.t2) }}</td>
                <td>{{ number(row.q) }}</td>
                <td>{{ plsScreeningLabel(row) }}</td>
              </template>
            </tr>
          </tbody>
        </table>
        <div class="review-controls">
          <button type="button" :disabled="page === 0" @click="page--">Previous</button
          ><span>Page {{ page + 1 }} / {{ pages }}</span
          ><button type="button" :disabled="page + 1 >= pages" @click="page++">Next</button>
        </div>
        <details>
          <summary>Scientist review history (latest 100 decisions)</summary>
          <ol>
            <li v-for="entry in review.history" :key="entry.revision">
              Revision {{ entry.revision }}: {{ entry.action }}
              {{ entry.sample_ids.length }} samples from run {{ entry.run_id }} — {{ entry.reason }}
            </li>
          </ol>
        </details>
      </template>
      <button v-else type="button" :disabled="busy" @click="load">Refresh review evidence</button>
    </section>
  </Dialog>
</template>

<script setup lang="ts">
import { SCIENTIFIC_COLORS } from "@/theme/plotTheme";
import { seriesPalette } from "@/utils/colors";
import { computed, ref, watch } from "vue";
import DatasetCurationPanel from "@/components/DatasetCurationPanel.vue";
import Dialog from "primevue/dialog";
import PlsApplicability from "@/components/PlsApplicability.vue";
import DiagnosticAdvisor from "@/components/DiagnosticAdvisor.vue";
import PcaExplanation from "@/components/PcaExplanation.vue";
import PlsExplanation from "@/components/PlsExplanation.vue";
import ReviewSpectra from "@/components/ReviewSpectra.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import api from "@/api/client";
import { useWorkflowStore } from "@/stores/workflow";
import {
  selectedSampleIds,
  plsScreeningLabel,
  type PcaReview,
  type ReviewRow,
} from "@/utils/sampleReview";

const advisorVariables = ref<string[]>([]);
const advisorResponse = ref<number | null>(null);
const advisorSample = ref("");
const advisorVariableContext = ref<"prediction" | "applicability" | undefined>();
function updateAdvisorSelection(
  value: { variables: string[]; response: number; sample: string; activate?: boolean },
  context?: "prediction" | "applicability",
) {
  // Synchronization from an inactive panel cannot replace explicit variable focus.
  if (advisorVariableContext.value !== context && !value.activate) return;
  advisorVariableContext.value = context;
  advisorVariables.value = value.variables;
  advisorResponse.value = value.response;
  advisorSample.value = value.sample;
}
const props = defineProps<{ modelValue: boolean; nodeId: string }>();
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();
const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});
const store = useWorkflowStore();
const review = ref<PcaReview | null>(null);
const selected = ref<string[]>([]);
const curationSource = computed(() => {
  const binding = review.value?.dataset_curation_source;
  if (!binding) return null;
  const { observations, ...source } = binding;
  return {
    ...source,
    review_origin: {
      workflow_id: store.workflowId!,
      run_id: review.value!.run_id,
      node_id: props.nodeId,
      revision: review.value!.revision,
    },
    seed_observations: observations.filter((row) => selected.value.includes(row.sample_id)),
  };
});
async function onCurationApplied(workflowId: number) {
  if (workflowId === store.workflowId) {
    await store.loadWorkflow(workflowId);
    await load();
  }
}
const showExplanation = ref(false);
const targetIndex = ref(0);
function resetAdvisorVariables() {
  advisorVariables.value = [];
  advisorResponse.value = null;
  advisorSample.value = "";
  advisorVariableContext.value = undefined;
}
watch([() => review.value?.run_id, () => props.nodeId], resetAdvisorVariables);
watch(showExplanation, (open) => {
  if (!open && advisorVariableContext.value !== "applicability") resetAdvisorVariables();
});
const isPls = computed(() => review.value?.model_kind === "pls");
const acknowledgePostReview = ref(false);
const masked = computed(() => new Set(review.value?.state.heldout_excluded || []));
const metricRows = computed(() =>
  [
    {
      label: "Current model — full original test set",
      statistics: review.value?.full_test_statistics,
    },
    {
      label: "Post-review subset — descriptive only",
      statistics: review.value?.review_subset_statistics,
    },
    {
      label: "Original reviewed run — full test baseline",
      statistics:
        review.value?.state.test_baseline?.statistics || review.value?.full_test_statistics,
    },
    {
      label: "Current calibration fit — not validation",
      statistics: review.value?.calibration_statistics,
    },
  ].map((item) => ({
    label: item.label,
    metrics: item.statistics?.targets[targetIndex.value]?.metrics,
  })),
);
function roleLabel(row: ReviewRow) {
  if (row.role === "held_out_test")
    return masked.value.has(row.id) ? "× Test — omitted from review subset" : "□ Held-out test";
  return row.role === "excluded_projected" ? "× Excluded — projected" : "Calibration";
}
const reason = ref("");
const error = ref("");
const busy = ref(false);
const progress = ref("");
const query = ref("");
const selectedOnly = ref(false);
const descending = ref(false);
const page = ref(0);
const xComponent = ref(0);
const yComponent = ref(1);
const selectedSet = computed(() => new Set(selected.value));
const allowed = computed(() => new Set(review.value?.rows.map((r) => r.id) || []));
const marked = computed(() => new Set(review.value?.state.marked || []));
const canAct = computed(
  () =>
    !busy.value &&
    !store.isExecuting &&
    !store.hasUnsavedChanges &&
    selected.value.length > 0 &&
    !!reason.value.trim(),
);
const activeSelected = computed(
  () =>
    selected.value.length > 0 &&
    review.value?.rows
      .filter((r) => selectedSet.value.has(r.id))
      .every((r) => r.role === "calibration"),
);
const testSelected = computed(
  () =>
    selected.value.length > 0 &&
    review.value?.rows
      .filter((r) => selectedSet.value.has(r.id))
      .every((r) => r.role === "held_out_test"),
);
const excludedSelected = computed(() =>
  review.value?.state.excluded.some((id) => selectedSet.value.has(id)),
);
const filteredRows = computed(() =>
  (review.value?.rows || [])
    .filter(
      (r) =>
        r.id.toLowerCase().includes(query.value.toLowerCase()) &&
        (!selectedOnly.value || selectedSet.value.has(r.id)),
    )
    .slice()
    .sort((a, b) => a.id.localeCompare(b.id) * (descending.value ? -1 : 1)),
);
const pages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / 50)));
const pageRows = computed(() => filteredRows.value.slice(page.value * 50, (page.value + 1) * 50));
watch([query, selectedOnly, descending, pages], () => {
  page.value = 0;
});
const config = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["autoScale2d"] };

const groupColors = computed(
  () =>
    new Map(
      [...new Set(review.value?.rows.map((r) => r.group) || [])]
        .sort()
        .map((g, i) => [g, seriesPalette("diagnostics")[i % seriesPalette("diagnostics").length]]),
    ),
);
function traces(x: (r: ReviewRow) => number | null, y: (r: ReviewRow) => number | null) {
  const groups = new Map<string, ReviewRow[]>();
  for (const row of review.value?.rows || []) {
    if (x(row) == null || y(row) == null) continue;
    const key = `${row.group}\u0000${row.role}\u0000${masked.value.has(row.id)}\u0000${marked.value.has(row.id)}`;
    const rows = groups.get(key) || [];
    rows.push(row);
    groups.set(key, rows);
  }
  return [...groups.values()].map((rows) => ({
    type: "scatter",
    mode: "markers",
    name: `${rows[0].group} · ${roleLabel(rows[0])}${marked.value.has(rows[0].id) ? " · Marked outlier" : ""}`,
    x: rows.map(x),
    y: rows.map(y),
    customdata: rows.map((r) => r.id),
    hovertemplate: "%{customdata}<br>x=%{x:.4g}<br>y=%{y:.4g}<extra>%{fullData.name}</extra>",
    marker: {
      color: groupColors.value.get(rows[0].group),
      size: 8,
      symbol:
        rows[0].role === "excluded_projected" || masked.value.has(rows[0].id)
          ? "x"
          : marked.value.has(rows[0].id)
            ? "diamond-open"
            : rows[0].role === "held_out_test"
              ? "square-open"
              : "circle",
      opacity: rows[0].role === "excluded_projected" ? 0.65 : 1,
    },
    selected: { marker: { size: 12, opacity: 1 } },
    unselected: { marker: { opacity: 0.25 } },
  }));
}
const scoreTraces = computed(() =>
  traces(
    (r) =>
      isPls.value
        ? (r.reference?.[targetIndex.value] ?? null)
        : (r.scores?.[xComponent.value] ?? null),
    (r) =>
      isPls.value
        ? (r.predicted?.[targetIndex.value] ?? null)
        : (r.scores?.[yComponent.value] ?? null),
  ),
);
const diagnosticTraces = computed(() =>
  traces(
    (r) => (isPls.value ? (r.predicted?.[targetIndex.value] ?? null) : r.t2),
    (r) => (isPls.value ? (r.residual?.[targetIndex.value] ?? null) : r.q),
  ),
);
const baseLayout = {
  height: 390,
  dragmode: "lasso",
  margin: { t: 40, l: 65, r: 20, b: 70 },
  legend: { orientation: "h", y: -0.2 },
  uirevision: "pca-review",
};
const scoreLayout = computed(() => ({
  ...baseLayout,
  title: isPls.value ? "Predicted / reference" : "PCA scores",
  xaxis: { title: isPls.value ? "Reference" : `PC ${xComponent.value + 1}` },
  yaxis: { title: isPls.value ? "Predicted" : `PC ${yComponent.value + 1}` },
}));
const diagnosticLayout = computed(() => ({
  ...baseLayout,
  title: isPls.value ? "Residuals / predicted" : "T² / Q diagnostics",
  xaxis: { title: isPls.value ? "Predicted" : "Hotelling T²" },
  yaxis: { title: isPls.value ? "Residual (reference − predicted)" : "Q / SPE" },
  shapes:
    review.value && !isPls.value
      ? [
          {
            type: "line",
            x0: review.value.calibration_t2_limit,
            x1: review.value.calibration_t2_limit,
            y0: 0,
            y1: 1,
            yref: "paper",
            line: { color: SCIENTIFIC_COLORS.referenceLine },
          },
          {
            type: "line",
            x0: review.value.application_t2_limit,
            x1: review.value.application_t2_limit,
            y0: 0,
            y1: 1,
            yref: "paper",
            line: { color: SCIENTIFIC_COLORS.referenceLine, dash: "dash" },
          },
          {
            type: "line",
            x0: 0,
            x1: 1,
            xref: "paper",
            y0: review.value.q_limit,
            y1: review.value.q_limit,
            line: { color: SCIENTIFIC_COLORS.referenceLine },
          },
        ]
      : [],
}));
function selectPoints(event: unknown) {
  selected.value = selectedSampleIds(event, allowed.value);
}
function toggle(id: string) {
  selected.value = selectedSet.value.has(id)
    ? selected.value.filter((x) => x !== id)
    : [...selected.value, id];
}
function displayParameters(parameters: Record<string, unknown>): string {
  const text = Object.entries(parameters)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, value]) => `${name}=${JSON.stringify(value)}`)
    .join(", ");
  return text.length > 300 ? `${text.slice(0, 300)}…` : text || "defaults";
}

function number(value: number | null) {
  return value == null ? "Unavailable" : value.toPrecision(5);
}
function message(e: unknown) {
  return (
    (e as { response?: { data?: { detail?: string } }; message?: string }).response?.data?.detail ||
    (e as Error).message ||
    "Review failed."
  );
}
let generation = 0;
async function load() {
  const token = ++generation;
  const workflowId = store.workflowId;
  const nodeId = props.nodeId;
  error.value = "";
  if (!workflowId) {
    error.value = "Save and run this workflow to enable sample review.";
    return;
  }
  try {
    const { data } = await api.get<PcaReview>(
      `/workflows/${workflowId}/sample-review/${encodeURIComponent(nodeId)}`,
    );
    if (token !== generation || workflowId !== store.workflowId || nodeId !== props.nodeId) return;
    review.value = data;
    targetIndex.value = Math.min(
      targetIndex.value,
      Math.max(0, (data.target_names?.length || 1) - 1),
    );
    xComponent.value = Math.min(xComponent.value, data.n_components - 1);
    yComponent.value = Math.min(yComponent.value, data.n_components - 1);
    selected.value = selected.value.filter((id) => data.rows.some((r) => r.id === id));
  } catch (e) {
    if (token === generation) {
      review.value = null;
      error.value = message(e);
    }
  }
}
async function rerun() {
  busy.value = true;
  progress.value = "Running the current workflow…";
  let failure = "";
  try {
    await store.executeWorkflow();
  } catch (e) {
    failure = message(e);
  } finally {
    await load();
    if (failure) error.value = failure;
    busy.value = false;
  }
}
async function apply(
  action: "mark" | "unmark" | "exclude" | "restore" | "exclude_test" | "restore_test",
) {
  if (!review.value || !canAct.value) return;
  const workflowId = store.workflowId;
  const nodeId = props.nodeId;
  busy.value = true;
  error.value = "";
  progress.value = "Saving scientist review…";
  let failure = "";
  try {
    const r = review.value;
    await api.post(`/workflows/${workflowId}/sample-review/${encodeURIComponent(nodeId)}`, {
      run_id: r.run_id,
      expected_latest_run_id: r.latest_run_id,
      expected_revision: r.revision,
      expected_graph_digest: r.graph_digest,
      source_digest: r.source_digest,
      action,
      sample_ids: selected.value,
      reason: reason.value,
      acknowledge_post_review: acknowledgePostReview.value,
    });
    if (store.workflowId !== workflowId || props.nodeId !== nodeId) return;
    if (action === "exclude" || action === "restore") {
      progress.value = "Refitting on the retained cohort; projecting excluded samples…";
      await store.loadWorkflow(workflowId!);
      await store.executeWorkflow();
    }
  } catch (e) {
    failure = message(e);
  } finally {
    if (store.workflowId === workflowId && props.nodeId === nodeId) {
      await load();
      if (failure) error.value = failure;
    }
    busy.value = false;
  }
}
watch(
  () => [props.modelValue, props.nodeId, store.workflowId],
  () => {
    review.value = null;
    selected.value = [];
    showExplanation.value = false;
    reason.value = "";
    acknowledgePostReview.value = false;
    if (props.modelValue) void load();
    else generation++;
  },
  { immediate: true },
);
</script>

<style scoped>
.pca-review {
  display: grid;
  gap: 0.7rem;
}
.review-plots {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}
.review-controls {
  display: flex;
  gap: 0.7rem;
  flex-wrap: wrap;
  align-items: center;
}
.review-reason {
  display: flex;
  gap: 0.7rem;
  align-items: center;
}
.review-reason input {
  flex: 1;
}
button,
input,
select {
  padding: 0.4rem;
  font: inherit;
}
button {
  cursor: pointer;
}
button:disabled {
  cursor: default;
  opacity: 0.5;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  text-align: left;
  padding: 0.45rem;
  border-bottom: 1px solid var(--surface-border, var(--ss-border));
}
tr.selected {
  outline: 2px solid var(--ss-info);
  outline-offset: -2px;
  background: color-mix(in srgb, var(--ss-info) 10.196%, transparent);
}
tr.excluded td {
  font-style: italic;
}
.review-error {
  color: var(--red-600, var(--ss-excluded));
}
@media (max-width: 900px) {
  .review-plots {
    grid-template-columns: 1fr;
  }
}
</style>
