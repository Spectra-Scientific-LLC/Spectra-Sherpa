<template>
  <section class="pls-applicability" aria-label="PLS predictor-space applicability">
    <h3>PLS predictor-space novelty</h3>
    <p>
      Scores describe position in the fitted predictor space. T² measures distance in retained score
      space; Q measures predictor signal not reconstructed by the model. Neither measures response
      error. Passing a global screen does not establish local support or prediction certainty.
    </p>
    <p v-if="stale" role="status">
      Previous-fit applicability is hidden while the workflow is changed or running. Reopen the
      intended saved run or rerun to inspect its predictor evidence.
    </p>
    <p v-else-if="!detail" role="status">
      {{
        unavailable ||
        "This saved run has no retained PLS applicability evidence. Rerun to enable scores and screening."
      }}
    </p>
    <template v-else>
      <p>
        Reference: {{ detail.reference_count }} retained calibration observations ·
        {{ detail.components }} latent variables · score covariance rank
        {{ detail.score_covariance_rank }} of {{ detail.components }}. {{ detail.space }}. Score
        units: {{ detail.score_units }}. Q units: {{ detail.q_units }}. Preprocessing:
        {{ preprocessingLabel }}. Global screening is provisional and uses
        {{ format(100 * detail.confidence) }}% nominal limits, not prediction confidence.
      </p>
      <p>
        Solid T² limit: calibration {{ format(detail.calibration_t2_limit) }}. Dashed T² limit:
        held-out and excluded applications {{ format(detail.application_t2_limit) }}. Q limit:
        {{ format(detail.q_limit) }}, derived from the calibration reference. Groups retain their
        colours; sample role and scientist marks retain their symbols.
      </p>
      <p v-if="detail.t2_unavailable_reason" role="status">
        T² unavailable: {{ detail.t2_unavailable_reason }}. Q and scores remain available where
        retained.
      </p>
      <p v-if="detail.q_unavailable_reason" role="status">
        Q screening unavailable: {{ detail.q_unavailable_reason }}.
      </p>
      <p>
        Local neighborhood support: unavailable from the retained aggregate state. Investigate
        independent spectral and reference evidence before judging a prediction.
      </p>
      <div class="component-controls">
        <label
          >PLS score X component
          <select v-model.number="xComponent" aria-label="PLS score X component">
            <option v-for="i in detail.components" :key="i" :value="i - 1">LV {{ i }}</option>
          </select></label
        >
        <label v-if="detail.components > 1"
          >PLS score Y component
          <select v-model.number="yComponent" aria-label="PLS score Y component">
            <option v-for="i in detail.components" :key="i" :value="i - 1">LV {{ i }}</option>
          </select></label
        >
      </div>
      <p v-if="detail.components === 1">
        One latent variable was retained. The score plot uses zero vertical position for display
        only; it is not a second latent variable.
      </p>
      <p>
        Changing displayed score components does not change the all-component T²/Q values or
        screening decisions.
      </p>
      <div class="applicability-plots">
        <PlotlyChart
          :data="scoreTraces"
          :layout="scoreLayout"
          :config="config"
          :selected-point-ids="selected"
          @selected="emit('selected', $event)"
          @deselect="emit('deselect')"
        />
        <PlotlyChart
          :data="diagnosticTraces"
          :layout="diagnosticLayout"
          :config="config"
          :selected-point-ids="selected"
          @selected="emit('selected', $event)"
          @deselect="emit('deselect')"
        />
      </div>
      <p v-if="missingScores || missingQ" role="status">
        {{ missingScores }} observations lack the displayed score pair; {{ missingQ }} lack Q. They
        remain in the linked sample table with their unavailable reason.
      </p>
      <details>
        <summary>Explain selected predictor-space novelty</summary>
        <p>
          Choose a selected observation. These terms explain predictor-space novelty, separately
          from the response-specific prediction contributions below.
        </p>
        <label
          >Applicability sample
          <select v-model="sample" aria-label="Applicability sample">
            <option value="">Select an observation</option>
            <option v-for="id in selected" :key="id" :value="id">{{ reviewRowLabel(review.rows.find((row) => row.id === id), id) }}</option>
          </select></label
        >
        <template v-if="observation">
          <p>
            <strong>{{ reviewRowLabel(review.rows.find((row) => row.id === sample), sample) }}</strong> · {{ roleLabel(observation) }} ·
            {{ plsScreeningLabel(observation) }}.
          </p>
          <p>
            Applicable T² limit:
            {{
              format(
                observation.role === "calibration"
                  ? detail.calibration_t2_limit
                  : detail.application_t2_limit,
              )
            }}
            · Q limit: {{ format(detail.q_limit) }}.
          </p>
          <p v-if="observation.role === 'held_out_test'">
            Held-out inspection does not change its cohort or full-test metrics. Using this evidence
            to tune a model is adaptive development, not independent validation.
          </p>
        </template>
        <template v-if="terms">
          <p>
            Full Q: {{ format(terms.q_total) }} · Full T²: {{ format(terms.t2_total) }}. The
            contributions use all retained latent variables and the fitted reference center.
          </p>
          <p v-if="terms.decomposition_unavailable_reason" role="status">
            Variable explanation unavailable: {{ terms.decomposition_unavailable_reason }}.
          </p>
          <template v-else>
            <p>
              Showing {{ terms.variables.length }} of {{ detail.feature_count }} variables: union of
              the leading {{ detail.top_per_statistic }} Q and absolute signed T² terms. Omitted
              variables are not zero.
            </p>
            <p>
              Omitted Q: {{ format(terms.omitted_q) }} · Omitted signed T²:
              {{ format(terms.omitted_t2) }} · Omitted absolute T² mass:
              {{ format(terms.omitted_t2_absolute) }}. A small signed remainder may hide
              cancellation.
            </p>
            <p>
              Q terms are squared predictor residuals. Negative T² terms mean signed cancellation,
              not negative distance. These are model-space descriptions, not chemical causes or
              prediction-error attributions.
            </p>
            <div class="applicability-plots">
              <PlotlyChart
                v-for="statistic in ['q', 't2'] as const"
                :key="`${statistic}:${plotReset}`"
                :data="contributionTraces(statistic)"
                :layout="contributionLayout(statistic)"
                :config="config"
                :selected-point-ids="features"
                @selected="selectFeatures"
                @deselect="features = []"
              />
            </div>
            <div class="variable-table">
              <table>
                <caption>
                  Leading applicability variables
                </caption>
                <thead>
                  <tr>
                    <th>Highlight</th>
                    <th>Variable / column</th>
                    <th>Q term</th>
                    <th>Signed T² term</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="term in rankedTerms" :key="term[0]">
                    <td>
                      <input
                        type="checkbox"
                        :aria-label="`Highlight applicability variable ${term[0] + 1}`"
                        :checked="features.includes(featureId(term[0]))"
                        @change="toggleFeature(term[0])"
                      />
                    </td>
                    <td>{{ featureLabel(term[0]) }}</td>
                    <td>{{ format(term[1]) }}</td>
                    <td>{{ format(term[2]) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p aria-live="polite">
              {{ features.length }} applicability variables highlighted. Use “Explain these
              applicability variables” in Ask Sherpa above. Variable highlights do not mark or
              exclude observations.
            </p>
            <button type="button" @click="resetFeatures">
              Reset applicability variable highlights
            </button>
          </template>
        </template>
        <p v-else-if="sample" role="status">
          {{
            observation?.projection_error ||
            observation?.applicability_unavailable_reason ||
            "No exact variable explanation was retained for this observation."
          }}
        </p>
      </details>
      <details>
        <summary>Applicability methods and retained evidence</summary>
        <p>
          Calibration T²: {{ detail.calibration_t2_limit_method }}. Application T²:
          {{ detail.application_t2_limit_method }}. Q: {{ detail.q_limit_method }}.
        </p>
        <p>
          Rank tolerance: {{ format(detail.rank_tolerance) }} · Q numerical tolerance:
          {{ format(detail.q_numerical_tolerance) }}.
        </p>
        <p>{{ detail.formula }}</p>
        <p>{{ detail.contribution_formula }}</p>
        <p class="digest">
          Model {{ detail.model_digest }}<br />Feature identity {{ detail.feature_identity
          }}<br />Reference {{ detail.reference_digest }}<br />Source
          {{ detail.source_contract_digest }}
        </p>
      </details>
    </template>
  </section>
</template>
<script setup lang="ts">
import { reviewRowLabel } from "@/utils/sampleReview";
import { escapeScientificText } from "@/utils/validationReportPlots";
import { SCIENTIFIC_COLORS } from "@/theme/plotTheme";
import { computed, ref, watch } from "vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import {
  plsScreeningLabel,
  selectedSampleIds,
  type PcaReview,
  type ReviewRow,
} from "@/utils/sampleReview";
const props = defineProps<{
  review: PcaReview;
  selected: string[];
  colors: Map<string, string>;
  stale: boolean;
  responseIndex?: number;
}>();
const emit = defineEmits<{
  selected: [event: unknown];
  deselect: [];
  "advisor-selection": [
    value: { variables: string[]; sample: string; response: number; activate?: boolean },
  ];
}>();
const detail = computed(() =>
  props.review.pls_applicability && !("unavailable_reason" in props.review.pls_applicability)
    ? props.review.pls_applicability
    : null,
);
const unavailable = computed(() =>
  props.review.pls_applicability && "unavailable_reason" in props.review.pls_applicability
    ? props.review.pls_applicability.unavailable_reason
    : "",
);
const xComponent = ref(0),
  yComponent = ref(1),
  sample = ref("");
const features = ref<string[]>([]),
  plotReset = ref(0);
const format = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? "Unavailable" : value.toPrecision(5);
const preprocessingLabel = computed(
  () =>
    detail.value?.preprocessing
      .map((value) => value.replace(/^preprocess\./, "").replace(/_/g, " "))
      .join(" → ") || "none before the PLS fit",
);
const terms = computed(() => detail.value?.rows[sample.value]);
const observation = computed(() => props.review.rows.find((row) => row.id === sample.value));
watch(
  () => props.selected,
  (ids) => {
    if (!ids.includes(sample.value)) sample.value = ids[0] || "";
  },
  { immediate: true },
);
watch(
  () => [
    props.review.run_id,
    detail.value?.model_digest,
    detail.value?.feature_identity,
    props.stale,
  ],
  () => {
    xComponent.value = 0;
    yComponent.value = Math.min(1, (detail.value?.components || 1) - 1);
    sample.value = props.selected[0] || "";
    resetFeatures();
  },
  { immediate: true },
);
function emitAdvisorSelection(activate = false) {
  emit("advisor-selection", {
    variables: [...features.value],
    sample: sample.value,
    response: props.responseIndex ?? 0,
    ...(activate ? { activate: true } : {}),
  });
}
watch(
  () => [features.value, sample.value, props.responseIndex],
  () => emitAdvisorSelection(),
  { deep: true },
);
function resetFeatures() {
  features.value = [];
  plotReset.value++;
}
const marked = computed(() => new Set(props.review.state.marked));
const masked = computed(() => new Set(props.review.state.heldout_excluded || []));
function roleLabel(row: ReviewRow) {
  return row.role === "calibration"
    ? "Calibration"
    : row.role === "held_out_test"
      ? masked.value.has(row.id)
        ? "Held-out test — omitted from review subset"
        : "Held-out test"
      : "Excluded — projected into this fit";
}
function traces(
  x: (row: ReviewRow) => number | null | undefined,
  y: (row: ReviewRow) => number | null | undefined,
) {
  const groups = new Map<string, ReviewRow[]>();
  for (const row of props.review.rows) {
    if (x(row) == null || y(row) == null) continue;
    const key = `${row.group}\u0000${row.role}\u0000${marked.value.has(row.id)}\u0000${masked.value.has(row.id)}`;
    const rows = groups.get(key) || [];
    rows.push(row);
    groups.set(key, rows);
  }
  return [...groups.values()].map((rows) => ({
    type: "scatter",
    mode: "markers",
    name: `${rows[0].group} · ${roleLabel(rows[0])}${marked.value.has(rows[0].id) ? " · Scientist marked" : ""}`,
    x: rows.map(x),
    y: rows.map(y),
    customdata: rows.map((row) => row.id),
    text: rows.map((row) => escapeScientificText(reviewRowLabel(row))),
    hovertemplate: "%{text}<br>x=%{x:.5g}<br>y=%{y:.5g}<extra>%{fullData.name}</extra>",
    marker: {
      color: props.colors.get(rows[0].group),
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
    (row) => row.scores?.[xComponent.value],
    (row) => (detail.value?.components === 1 ? 0 : row.scores?.[yComponent.value]),
  ),
);
const qOnly = computed(() => !props.review.rows.some((row) => row.t2 != null));
const rowPositions = computed(() => new Map(props.review.rows.map((row, i) => [row.id, i + 1])));
const diagnosticTraces = computed(() =>
  traces(
    (row) => (qOnly.value ? rowPositions.value.get(row.id) : row.t2),
    (row) => row.q,
  ),
);
const missingScores = computed(
  () =>
    props.review.rows.filter(
      (row) => row.scores?.[xComponent.value] == null || row.scores?.[yComponent.value] == null,
    ).length,
);
const missingQ = computed(() => props.review.rows.filter((row) => row.q == null).length);
const baseLayout = {
  height: 360,
  dragmode: "lasso",
  margin: { t: 45, l: 65, r: 20, b: 85 },
  legend: { orientation: "h", y: -0.25 },
};
const scoreLayout = computed(() => ({
  ...baseLayout,
  title: "PLS predictor scores",
  xaxis: {
    title: `LV ${xComponent.value + 1} · ${detail.value?.score_units || "fitted score coordinates"}`,
  },
  yaxis: {
    title:
      detail.value?.components === 1 ? "Display position (one LV)" : `LV ${yComponent.value + 1}`,
  },
  uirevision: `pls-scores:${props.review.run_id}:${xComponent.value}:${yComponent.value}`,
}));
const diagnosticLayout = computed(() => ({
  ...baseLayout,
  title: qOnly.value ? "Q by retained observation (T² unavailable)" : "PLS T² / Q global screening",
  xaxis: { title: qOnly.value ? "Retained observation order" : "Predictor T²" },
  yaxis: {
    title: `Predictor Q / SPE · ${detail.value?.q_units || "fitted predictor units squared"}`,
  },
  uirevision: `pls-diagnostics:${props.review.run_id}`,
  shapes: [
    ...(!qOnly.value && detail.value?.calibration_t2_limit != null
      ? [
          {
            type: "line",
            x0: detail.value.calibration_t2_limit,
            x1: detail.value.calibration_t2_limit,
            y0: 0,
            y1: 1,
            yref: "paper",
            line: { color: SCIENTIFIC_COLORS.referenceLine },
          },
        ]
      : []),
    ...(!qOnly.value && detail.value?.application_t2_limit != null
      ? [
          {
            type: "line",
            x0: detail.value.application_t2_limit,
            x1: detail.value.application_t2_limit,
            y0: 0,
            y1: 1,
            yref: "paper",
            line: { color: SCIENTIFIC_COLORS.referenceLine, dash: "dash" },
          },
        ]
      : []),
    ...(detail.value?.q_limit != null
      ? [
          {
            type: "line",
            x0: 0,
            x1: 1,
            xref: "paper",
            y0: detail.value.q_limit,
            y1: detail.value.q_limit,
            line: { color: SCIENTIFIC_COLORS.referenceLine },
          },
        ]
      : []),
  ],
}));
const config = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["autoScale2d"] };
const featureId = (index: number) => `${detail.value?.feature_identity}:${index}`;
const featureLabel = (index: number) =>
  `${detail.value?.feature_values?.[index] ?? "Variable"} ${detail.value?.feature_units || ""} (column ${index + 1})`;
const allowedFeatures = computed(
  () => new Set((terms.value?.variables || []).map((term) => featureId(term[0]))),
);
const rankedTerms = computed(() =>
  [...(terms.value?.variables || [])].sort((a, b) => b[1] - a[1] || a[0] - b[0]),
);
watch(allowedFeatures, (allowed) => {
  features.value = features.value.filter((id) => allowed.has(id));
});
function selectFeatures(event: unknown) {
  features.value = selectedSampleIds(event, allowedFeatures.value);
  emitAdvisorSelection(true);
}
function toggleFeature(index: number) {
  const id = featureId(index);
  features.value = features.value.includes(id)
    ? features.value.filter((value) => value !== id)
    : [...features.value, id];
  emitAdvisorSelection(true);
}
function contributionTraces(statistic: "q" | "t2") {
  const index = statistic === "q" ? 1 : 2;
  const rows = (terms.value?.variables || []).filter((row) => row[index] != null);
  return [
    {
      type: "scatter",
      mode: "markers",
      x: rows.map((row) => detail.value?.feature_values?.[row[0]] ?? row[0] + 1),
      y: rows.map((row) => row[index]),
      customdata: rows.map((row) => featureId(row[0])),
      text: rows.map((row) => featureLabel(row[0])),
      hovertemplate: "%{text}<br>%{y:.5g}<extra></extra>",
      marker: { color: SCIENTIFIC_COLORS.positive, size: 9 },
      selected: { marker: { size: 13, opacity: 1 } },
      unselected: { marker: { opacity: 0.25 } },
    },
  ];
}
function contributionLayout(statistic: "q" | "t2") {
  return {
    ...baseLayout,
    height: 300,
    title:
      statistic === "q"
        ? "Q predictor residual contributions"
        : "Signed T² predictor contributions",
    xaxis: { title: detail.value?.feature_units || "Original column" },
    yaxis: {
      title:
        statistic === "q"
          ? detail.value?.q_units || "Squared predictor residual"
          : "Signed T² term (dimensionless)",
    },
    uirevision: `pls-app-terms:${props.review.run_id}:${sample.value}:${statistic}:${plotReset.value}`,
  };
}
</script>
<style scoped>
.pls-applicability {
  border: 1px solid var(--surface-border, var(--ss-border-strong));
  padding: 1rem;
  margin: 1rem 0;
  display: grid;
  gap: 0.6rem;
}
h3,
p {
  margin: 0;
}
.component-controls {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}
label {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}
.applicability-plots {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}
details > p {
  margin: 0.6rem 0;
}
.variable-table {
  max-height: 300px;
  overflow: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  text-align: left;
  padding: 0.35rem;
  border-bottom: 1px solid var(--surface-border, var(--ss-border-strong));
}
.digest {
  overflow-wrap: anywhere;
}
@media (max-width: 900px) {
  .applicability-plots {
    grid-template-columns: 1fr;
  }
}
</style>
