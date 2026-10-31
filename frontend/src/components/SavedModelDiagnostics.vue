<template>
  <section class="saved-diagnostics" aria-label="Saved model diagnostics">
    <h3>Diagnostic workbench <MethodHelp topic="diagnostics" label="Reviewing model diagnostics" /></h3>
    <p v-if="loading" role="status">Loading exact saved-run evidence…</p>
    <p v-else-if="error" role="status">{{ error }}</p>
    <template v-else-if="review">
      <p>
        Run #{{ review.run_id }} · {{ review.n_calibration }} retained calibration samples ·
        {{ review.n_components }} components. ○ Calibration · □ Held-out test · ◇ Marked outlier · ×
        Excluded projection or test review omission. Colours identify sample groups.
      </p>
      <p v-if="decisionUnavailable" role="status">{{ decisionUnavailable }}</p>
      <div class="saved-diagnostics__controls">
        <label
          >Score X component
          <select v-model.number="scoreX">
            <option v-for="i in review.n_components" :key="i" :value="i - 1">
              {{ axisPrefix }} {{ i }}
            </option>
          </select>
        </label>
        <label v-if="review.n_components > 1"
          >Score Y component
          <select v-model.number="scoreY">
            <option v-for="i in review.n_components" :key="i" :value="i - 1">
              {{ axisPrefix }} {{ i }}
            </option>
          </select>
        </label>
        <label v-if="isPls"
          >Response
          <select v-model.number="responseIndex">
            <option v-for="(name, i) in review.target_names" :key="i" :value="i">
              {{ name }} {{ review.target_units?.[i] || "" }}
            </option>
          </select>
        </label>
        <label v-if="loadingRows"
          >Loading component
          <select v-model.number="loadingComponent">
            <option v-for="(_, i) in loadingRows" :key="i" :value="i">
              {{ axisPrefix }} {{ i + 1 }}
            </option>
          </select>
        </label>
        <button type="button" @click="selected = []">Clear sample selection</button>
      </div>
      <p v-if="review.n_components === 1">
        The vertical score coordinate is zero for display only; it is not a second component.
      </p>
      <div class="saved-diagnostics__plots">
        <PlotlyChart
          :data="scoreTraces"
          :layout="scoreLayout"
          :config="config"
          :selected-point-ids="selected"
          @selected="selectPoints"
          @deselect="selected = []"
        />
        <PlotlyChart
          :data="influenceTraces"
          :layout="influenceLayout"
          :config="config"
          :selected-point-ids="selected"
          @selected="selectPoints"
          @deselect="selected = []"
        />
        <PlotlyChart
          v-if="isPls"
          :data="predictionTraces"
          :layout="predictionLayout"
          :config="config"
          :selected-point-ids="selected"
          @selected="selectPoints"
          @deselect="selected = []"
        />
        <PlotlyChart
          v-if="isPls"
          :data="residualTraces"
          :layout="residualLayout"
          :config="config"
          :selected-point-ids="selected"
          @selected="selectPoints"
          @deselect="selected = []"
        />
        <PlotlyChart
          v-if="loadingRows"
          :data="loadingTraces"
          :layout="loadingLayout"
          :config="config"
          empty-message="No exact fitted loadings were retained."
        />
      </div>
      <p v-if="!loadingRows" role="status">Fitted loadings are unavailable for this saved model.</p>
      <p>
        Influence limits: fitted calibration T² {{ number(t2Limit ?? null) }}; projected application
        T² {{ number(applicationT2Limit ?? null) }}; Q {{ number(qLimit ?? null) }}. Each
        observation is assessed against the limit for its role. Dashed T² line marks the application
        limit.
      </p>
      <p aria-live="polite">{{ selected.length }} observations selected.</p>
      <label>Find observation <input v-model="query" type="search" /></label>
      <label><input v-model="selectedOnly" type="checkbox" /> Selected only</label>
      <table>
        <caption>
          Linked sample table —
          {{
            filteredRows.length
          }}
          observations
        </caption>
        <thead>
          <tr>
            <th>Select</th>
            <th>Observation</th>
            <th>Group</th>
            <th>Role / decision</th>
            <th>T²</th>
            <th>Q</th>
            <template v-if="isPls"
              ><th>Measured</th>
              <th>Predicted</th>
              <th>Residual</th></template
            >
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in pageRows"
            :key="row.id"
            :class="{ 'is-selected': selectedSet.has(row.id) }"
          >
            <td>
              <input
                type="checkbox"
                :aria-label="`Select sample ${reviewRowLabel(row)}`"
                :checked="selectedSet.has(row.id)"
                @change="toggle(row.id)"
              />
            </td>
            <td :title="row.id">{{ reviewRowLabel(row) }}</td>
            <td :style="{ color: groupColors.get(row.group) }">{{ row.group }}</td>
            <td>{{ roleLabel(row) }}{{ marked.has(row.id) ? " · marked outlier" : "" }}</td>
            <td>{{ number(row.t2) }}</td>
            <td>{{ number(row.q) }}</td>
            <template v-if="isPls">
              <td>{{ number(row.reference?.[responseIndex] ?? null) }}</td>
              <td>{{ number(row.predicted?.[responseIndex] ?? null) }}</td>
              <td>{{ number(row.residual?.[responseIndex] ?? null) }}</td>
            </template>
          </tr>
        </tbody>
      </table>
      <div class="saved-diagnostics__controls">
        <button type="button" :disabled="page === 0" @click="page--">Previous</button>
        <span>Page {{ page + 1 }} / {{ pages }}</span>
        <button type="button" :disabled="page + 1 >= pages" @click="page++">Next</button>
      </div>
      <PcaExplanation
        v-if="!isPls"
        :evidence="review.explanations"
        :selected="selected"
        :rows="review.rows"
        :run-id="review.run_id"
        :components="review.n_components"
        :stale="false"
        @advisor-selection="setPcaAdvisorFocus($event)"
      />
      <template v-else>
        <PlsApplicability
          :review="review"
          :selected="selected"
          :colors="groupColors"
          :response-index="responseIndex"
          :stale="false"
          @selected="selectPoints"
          @deselect="selected = []"
          @advisor-selection="setAdvisorFocus($event, 'applicability')"
        />
        <PlsExplanation
          :evidence="review.pls_explanations"
          :selected="selected"
          :rows="review.rows"
          :run-id="review.run_id"
          :stale="false"
          @advisor-selection="setAdvisorFocus($event, 'prediction')"
        />
      </template>
      <DiagnosticAdvisor
        v-if="workflowId && !decisionUnavailable"
        :review="review"
        :workflow-id="workflowId"
        :node-id="nodeId"
        :selected="selected"
        :variables="advisorVariables"
        :response-index="responseIndex"
        :variable-response-index="advisorResponse ?? responseIndex"
        :focused-sample="advisorSample"
        :variable-context="advisorContext"
        :stale="false"
      />
      <p v-else-if="decisionUnavailable" role="note">
        Ask Sherpa for this selection is unavailable until the exact fit-time review state can be
        verified.
      </p>
      <details v-if="curationSource && selected.length">
        <summary>Exclude selected observations from My Dataset</summary>
        <DatasetCurationPanel :source="curationSource" :seed-ids="selected" />
      </details>
      <p v-else-if="selected.length">Dataset correction requires retained source-row identity.</p>
      <button v-if="workflowId" type="button" @click="emit('open-workflow')">
        Open source workflow to mark, exclude or restore and refit
      </button>
    </template>
  </section>
</template>

<script setup lang="ts">
import { reviewRowLabel } from "@/utils/sampleReview";
import { escapeScientificText } from "@/utils/validationReportPlots";
import { useAuthStore } from "@/stores/auth";
import { useScopedRequest } from "@/composables/useScopedRequest";
import { SCIENTIFIC_COLORS } from "@/theme/plotTheme";
import { seriesPalette } from "@/utils/colors";
import MethodHelp from "@/components/MethodHelp.vue";
import { computed, ref, watch } from "vue";
import api from "@/api/client";
import PlotlyChart from "@/components/PlotlyChart.vue";
import PcaExplanation from "@/components/PcaExplanation.vue";
import PlsApplicability from "@/components/PlsApplicability.vue";
import PlsExplanation from "@/components/PlsExplanation.vue";
import DiagnosticAdvisor from "@/components/DiagnosticAdvisor.vue";
import DatasetCurationPanel from "@/components/DatasetCurationPanel.vue";
import { selectedSampleIds, type PcaReview, type ReviewRow } from "@/utils/sampleReview";
import type { CurationSource } from "@/utils/datasetCuration";
import { buildAxisLabel } from "@/utils/plotLabels";

type SavedDiagnostics = {
  run_id: number;
  node_id: string;
  receipt: Omit<PcaReview, "run_id" | "latest_run_id" | "revision" | "stale" | "state" | "history">;
  decision: {
    marked: string[] | null;
    excluded: string[] | null;
    heldout_excluded: string[] | null;
  };
  review_revision: number | null;
  post_review: boolean;
  decision_unavailable_reason: string | null;
};
const props = defineProps<{
  artifactUid: string;
  projectId: number;
  workflowId: number | null;
  nodeId: string;
}>();
const emit = defineEmits<{ "open-workflow": [] }>();
const review = ref<PcaReview | null>(null);
const decisionUnavailable = ref<string | null>(null);
const error = ref("");
const loading = ref(false);
const selected = ref<string[]>([]);
const query = ref("");
const selectedOnly = ref(false);
const page = ref(0);
const scoreX = ref(0);
const scoreY = ref(1);
const loadingComponent = ref(0);
const responseIndex = ref(0);
const advisorVariables = ref<string[]>([]);
const advisorResponse = ref<number | null>(null);
const advisorSample = ref("");
const advisorContext = ref<"prediction" | "applicability" | undefined>();
const auth = useAuthStore();
const identity = () => [auth.user?.id, auth.sessionRevision, props.artifactUid, props.projectId, props.nodeId];
const reads = useScopedRequest(identity, () => { loading.value = false; });
watch(
  identity,
  async () => {
    const request = reads.begin();
    loading.value = true;
    error.value = "";
    review.value = null;
    decisionUnavailable.value = null;
    selected.value = [];
    query.value = "";
    selectedOnly.value = false;
    page.value = 0;
    advisorVariables.value = [];
    advisorResponse.value = null;
    advisorSample.value = "";
    advisorContext.value = undefined;
    try {
      const { data } = await api.get<SavedDiagnostics>(
        `/models/${encodeURIComponent(props.artifactUid)}/diagnostics`,
        {
          params: { project_id: props.projectId },
          signal: request.signal,
        },
      );
      if (!request.isCurrent()) return;
      if (data.node_id !== props.nodeId)
        throw new Error("Saved diagnostic identity does not match this model.");
      const marked = data.decision.marked ?? [];
      const excluded = data.decision.excluded ?? [];
      const heldoutExcluded = data.decision.heldout_excluded ?? [];
      decisionUnavailable.value = data.decision_unavailable_reason;
      review.value = {
        ...data.receipt,
        run_id: data.run_id,
        latest_run_id: data.run_id,
        revision: data.review_revision ?? 0,
        stale: false,
        state: {
          marked,
          excluded,
          heldout_excluded: heldoutExcluded,
          post_review: data.post_review,
        },
        history: [],
      };
      scoreX.value = 0;
      scoreY.value = Math.min(1, Math.max(0, review.value.n_components - 1));
      loadingComponent.value = 0;
      responseIndex.value = 0;
    } catch (cause) {
      if (request.isCurrent())
        error.value =
          (cause as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
          "Exact saved diagnostics are unavailable for this model.";
    } finally {
      if (request.isCurrent()) loading.value = false;
    }
  },
  { immediate: true },
);
const isPls = computed(() => review.value?.model_kind === "pls");
const axisPrefix = computed(() => (isPls.value ? "LV" : "PC"));
const allowed = computed(() => new Set(review.value?.rows.map((row) => row.id) || []));
const selectedSet = computed(() => new Set(selected.value));
const marked = computed(() => new Set(review.value?.state.marked || []));
const masked = computed(() => new Set(review.value?.state.heldout_excluded || []));

const groupColors = computed(
  () =>
    new Map(
      [...new Set(review.value?.rows.map((row) => row.group) || [])]
        .sort()
        .map((group, index) => [group, seriesPalette("diagnostics")[index % seriesPalette("diagnostics").length]]),
    ),
);
const config = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["autoScale2d"] };
const baseLayout = {
  height: 390,
  dragmode: "lasso",
  margin: { t: 45, l: 65, r: 20, b: 70 },
  legend: { orientation: "h", y: -0.2 },
};
function number(value: number | null | undefined) {
  return value == null ? "—" : Number(value).toPrecision(5);
}
function roleLabel(row: ReviewRow) {
  if (row.role === "excluded_projected") return "Excluded — projected";
  if (row.role === "held_out_test")
    return masked.value.has(row.id) ? "Held-out — omitted from review subset" : "Held-out test";
  return "Calibration";
}
function traces(x: (row: ReviewRow) => number | null, y: (row: ReviewRow) => number | null) {
  const grouped = new Map<string, ReviewRow[]>();
  for (const row of review.value?.rows || []) {
    if (x(row) == null || y(row) == null) continue;
    const key = [row.group, row.role, marked.value.has(row.id), masked.value.has(row.id)].join(
      "\u0000",
    );
    const rows = grouped.get(key) || [];
    rows.push(row);
    grouped.set(key, rows);
  }
  return [...grouped.values()].map((rows) => ({
    type: "scatter",
    mode: "markers",
    name: `${rows[0].group} · ${roleLabel(rows[0])}${marked.value.has(rows[0].id) ? " · marked" : ""}`,
    x: rows.map(x),
    y: rows.map(y),
    customdata: rows.map((row) => row.id),
    text: rows.map((row) => escapeScientificText(reviewRowLabel(row))),
    hovertemplate: "%{text}<br>x=%{x:.4g}<br>y=%{y:.4g}<extra>%{fullData.name}</extra>",
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
    },
    selected: { marker: { size: 12, opacity: 1 } },
    unselected: { marker: { opacity: 0.25 } },
  }));
}
const scoreTraces = computed(() =>
  traces(
    (row) => row.scores?.[scoreX.value] ?? null,
    (row) =>
      review.value?.n_components === 1 && row.scores?.[0] != null
        ? 0
        : (row.scores?.[scoreY.value] ?? null),
  ),
);
const scoreLayout = computed(() => ({
  ...baseLayout,
  title: `${axisPrefix.value} scores`,
  xaxis: { title: `${axisPrefix.value} ${scoreX.value + 1}` },
  yaxis: {
    title:
      review.value?.n_components === 1
        ? "Zero display axis"
        : `${axisPrefix.value} ${scoreY.value + 1}`,
  },
  uirevision: `saved-score:${review.value?.run_id}:${scoreX.value}:${scoreY.value}`,
}));
const influenceTraces = computed(() =>
  traces(
    (row) => row.t2,
    (row) => row.q,
  ),
);
const t2Limit = computed(() =>
  isPls.value &&
  review.value?.pls_applicability &&
  !("unavailable_reason" in review.value.pls_applicability)
    ? review.value.pls_applicability.calibration_t2_limit
    : review.value?.calibration_t2_limit,
);
const applicationT2Limit = computed(() =>
  isPls.value &&
  review.value?.pls_applicability &&
  !("unavailable_reason" in review.value.pls_applicability)
    ? review.value.pls_applicability.application_t2_limit
    : review.value?.application_t2_limit,
);
const qLimit = computed(() =>
  isPls.value &&
  review.value?.pls_applicability &&
  !("unavailable_reason" in review.value.pls_applicability)
    ? review.value.pls_applicability.q_limit
    : review.value?.q_limit,
);
const influenceLayout = computed(() => ({
  ...baseLayout,
  title: "Predictor influence — T² versus Q",
  xaxis: { title: "Hotelling T²" },
  yaxis: { title: "Q / squared prediction error" },
  uirevision: `saved-influence:${review.value?.run_id}`,
  shapes: [
    ...(Number.isFinite(t2Limit.value)
      ? [
          {
            type: "line",
            x0: t2Limit.value,
            x1: t2Limit.value,
            y0: 0,
            y1: 1,
            yref: "paper",
            line: { color: SCIENTIFIC_COLORS.referenceLine },
          },
        ]
      : []),
    ...(Number.isFinite(applicationT2Limit.value)
      ? [
          {
            type: "line",
            x0: applicationT2Limit.value,
            x1: applicationT2Limit.value,
            y0: 0,
            y1: 1,
            yref: "paper",
            line: { color: SCIENTIFIC_COLORS.referenceLine, dash: "dash" },
          },
        ]
      : []),
    ...(Number.isFinite(qLimit.value)
      ? [
          {
            type: "line",
            x0: 0,
            x1: 1,
            xref: "paper",
            y0: qLimit.value,
            y1: qLimit.value,
            line: { color: SCIENTIFIC_COLORS.referenceLine },
          },
        ]
      : []),
  ],
}));
const predictionTraces = computed(() =>
  traces(
    (row) => row.reference?.[responseIndex.value] ?? null,
    (row) => row.predicted?.[responseIndex.value] ?? null,
  ),
);
const responseLabel = computed(() => buildAxisLabel(
  review.value?.target_names?.[responseIndex.value] || "Response",
  review.value?.target_units?.[responseIndex.value],
));
const predictionLayout = computed(() => ({
  ...baseLayout,
  title: "Predicted versus measured",
  xaxis: { title: `Measured ${responseLabel.value}` },
  yaxis: { title: `Predicted ${responseLabel.value}` },
  uirevision: `saved-prediction:${review.value?.run_id}:${responseIndex.value}`,
}));
const residualTraces = computed(() =>
  traces(
    (row) => row.predicted?.[responseIndex.value] ?? null,
    (row) => row.residual?.[responseIndex.value] ?? null,
  ),
);
const residualLayout = computed(() => ({
  ...baseLayout,
  title: "Residuals",
  xaxis: { title: `Predicted ${responseLabel.value}` },
  yaxis: { title: `Residual ${responseLabel.value} (measured − predicted)` },
  uirevision: `saved-residual:${review.value?.run_id}:${responseIndex.value}`,
}));
const loadingDetail = computed(() => {
  const evidence = isPls.value ? review.value?.pls_explanations : review.value?.explanations;
  return evidence && !("unavailable_reason" in evidence) ? evidence : null;
});
const loadingRows = computed(() => loadingDetail.value?.loadings || null);
const loadingTraces = computed(() => {
  const values = loadingRows.value?.[loadingComponent.value];
  if (!values) return [];
  const axis = loadingDetail.value?.feature_values;
  return [
    {
      type: "scatter",
      mode: "lines+markers",
      name: "Component loadings",
      x: values.map((_, i) => axis?.[i] ?? i + 1),
      y: values,
    },
  ];
});
const loadingLayout = computed(() => ({
  ...baseLayout,
  dragmode: "zoom",
  title: `${axisPrefix.value} ${loadingComponent.value + 1} loadings`,
  xaxis: { title: loadingDetail.value?.feature_values
    ? buildAxisLabel("Fitted feature coordinate", loadingDetail.value.feature_units)
    : "Variable index" },
  yaxis: { title: "Fitted loading" },
  uirevision: `saved-loadings:${review.value?.run_id}:${loadingComponent.value}`,
}));
function selectPoints(event: unknown) {
  selected.value = selectedSampleIds(event, allowed.value);
}
function toggle(id: string) {
  selected.value = selectedSet.value.has(id)
    ? selected.value.filter((value) => value !== id)
    : [...selected.value, id];
}
const filteredRows = computed(() =>
  (review.value?.rows || []).filter(
    (row) =>
      (reviewRowLabel(row).toLowerCase().includes(query.value.toLowerCase()) || row.id.toLowerCase().includes(query.value.toLowerCase())) &&
      (!selectedOnly.value || selectedSet.value.has(row.id)),
  ),
);
const pages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / 50)));
const pageRows = computed(() => filteredRows.value.slice(page.value * 50, (page.value + 1) * 50));
watch([query, selectedOnly, pages], () => {
  page.value = 0;
});
const curationSource = computed<CurationSource | null>(() => {
  const source = review.value?.dataset_curation_source;
  if (!source || !props.workflowId || !review.value) return null;
  const { observations, ...binding } = source;
  return {
    ...binding,
    review_origin: {
      workflow_id: props.workflowId,
      run_id: review.value.run_id,
      node_id: props.nodeId,
      revision: review.value.revision,
    },
    seed_observations: observations.filter((row) => selectedSet.value.has(row.sample_id)),
  };
});
function setAdvisorFocus(
  value: { variables: string[]; response: number; sample: string; activate?: boolean },
  context: "prediction" | "applicability",
) {
  if (advisorContext.value !== context && !value.activate) return;
  advisorContext.value = context;
  advisorVariables.value = value.variables;
  advisorResponse.value = value.response;
  advisorSample.value = value.sample;
}
function setPcaAdvisorFocus(value: { variables: string[]; response: number; sample: string }) {
  advisorContext.value = undefined;
  advisorVariables.value = value.variables;
  advisorResponse.value = value.response;
  advisorSample.value = value.sample;
}
</script>

<style scoped>
.saved-diagnostics {
  margin-top: 1.5rem;
}
.saved-diagnostics__plots {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 1rem;
}
.saved-diagnostics__controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  margin: 0.75rem 0;
}
.saved-diagnostics table {
  width: 100%;
  border-collapse: collapse;
}
.saved-diagnostics th,
.saved-diagnostics td {
  padding: 0.4rem;
  border-bottom: 1px solid var(--surface-border);
  text-align: left;
}
.saved-diagnostics tr.is-selected {
  background: var(--ss-action-tint);
}
</style>
