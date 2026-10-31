<template>
  <section class="pca-explanation" aria-label="PCA outlier explanations">
    <h3>Variable contributions <MethodHelp topic="diagnostics" label="Interpreting contributions" context="Contributions describe the fitted model, not chemical causes. Signed T² contributions can cancel; negative contributions are not negative distances. Q contributions are squared residuals." /></h3>
    <p v-if="stale" role="status">
      Rerun the current workflow to explain its fitted model. Previous-fit explanations are hidden.
    </p>
    <p v-else-if="!evidence || unavailable" role="status">
      {{ unavailable || "This run has no PCA explanation evidence. Rerun to enable explanations." }}
    </p>
    <template v-else-if="detail">
      <p v-if="!selected.length">Select an observation in the scores, diagnostics, or sample table.</p>
      <label
        >Sample to explain
        <select v-model="sample" aria-label="Sample to explain">
          <option value="">Select a sample</option>
          <option v-for="id in selected" :key="id" :value="id">{{ reviewRowLabel(rows.find((row) => row.id === id), id) }}</option>
        </select>
      </label>
      <p>{{ detail.reference_count }} calibration samples · {{ components }} components · {{ detail.space }}</p>
      <template v-if="row">
        <p>
          <strong>{{ reviewRowLabel(rows.find((row) => row.id === sample), sample) }}</strong> · {{ role }} · Full Q: {{ format(row.q_total) }} · Full T²:
          {{ format(row.t2_total) }}
        </p>
        <p>{{ row.variables.length }} / {{ detail.feature_count }} variables shown · top Q and |T²| contributions</p>
        <details><summary>Omitted contributions</summary>
        <p>
          Omitted Q: {{ format(row.omitted_q) }} · Omitted signed T²: {{ format(row.omitted_t2) }} ·
          Omitted absolute T² mass: {{ format(row.omitted_t2_absolute) }}. A small signed remainder
          can hide cancellation.
        </p>
        <p>Top {{ detail.top_per_statistic }} per statistic; omitted variables are not zero. Totals use all fitted components.</p>
        </details>
        <div class="explanation-plots">
          <PlotlyChart
            v-for="statistic in ['q', 't2'] as const"
            :key="`${statistic}:${plotReset}`"
            :data="contributionTraces[statistic]"
            :layout="contributionLayouts[statistic]"
            :config="config"
            :selected-point-ids="features"
            @selected="selectFeatures"
            @deselect="features = []"
          />
        </div>
        <label
          >Rank variables by
          <select v-model="rank" aria-label="Rank contribution variables">
            <option value="q">Q contribution</option>
            <option value="t2">Absolute T² contribution</option>
          </select>
        </label>
        <div class="variable-table">
          <table>
            <caption>
              Leading model-space variables
            </caption>
            <thead>
              <tr>
                <th>Highlight</th>
                <th>Variable (original column)</th>
                <th>Q contribution</th>
                <th>Signed T² contribution</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in ranked" :key="item[0]">
                <td>
                  <input
                    type="checkbox"
                    :aria-label="`Highlight variable ${item[0] + 1}`"
                    :checked="features.includes(featureId(item[0]))"
                    @change="toggleFeature(item[0])"
                  />
                </td>
                <td>{{ featureLabel(item[0]) }}</td>
                <td>{{ format(item[1]) }}</td>
                <td>{{ format(item[2]) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <p v-else-if="sample" role="status">
        Explanation unavailable for {{ reviewRowLabel(rows.find((row) => row.id === sample), sample) }}:
        {{ projectionError || "No exact projected observation was retained." }}
      </p>
      <p v-else role="status">Select an observation to see its variable contributions.</p>
      <p aria-live="polite">
        {{ features.length }} variables highlighted; {{ absentFeatures }} are outside this sample's
        leading contribution list.
      </p>
      <button type="button" @click="clearFeatures">Reset variable highlights and plots</button>
      <template v-if="detail.loadings">
        <label
          >Loading component
          <select v-model.number="component" aria-label="Loading component">
            <option v-for="(_, i) in detail.loadings" :key="i" :value="i">PC {{ i + 1 }}</option>
          </select>
        </label>
        <PlotlyChart
          :key="`loadings:${plotReset}`"
          :data="loadingTrace"
          :layout="loadingLayout"
          :config="config"
          :selected-point-ids="features"
          link-line-selection
          @selected="selectFeatures"
          @deselect="features = []"
        />
        <p>{{ detail.feature_count }} fitted variables · highlights only</p>
      </template>
      <p v-else>{{ detail.loadings_unavailable_reason }}</p>
      <details>
        <summary>Explanation provenance and formula</summary>
        <p>Calibration centroid · preprocessing: {{ detail.preprocessing.map(preprocessorLabel).join(" → ") || "none before PCA" }}. Smoothing and derivatives mix neighboring variables. Highlights do not exclude samples or infer omitted contributions.</p>
        <p>
          Run {{ runId }} · {{ detail.formula }}. P denotes component × feature loadings in this
          formula.
        </p>
        <p class="digest">
          Model {{ detail.model_digest }}<br />Feature axis {{ detail.feature_identity
          }}<br />Calibration reference {{ detail.reference_digest }}
        </p>
      </details>
    </template>
  </section>
</template>
<script setup lang="ts">
import { reviewRowLabel } from "@/utils/sampleReview";
import { SCIENTIFIC_COLORS } from "@/theme/plotTheme";
import { computed, ref, watch } from "vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import MethodHelp from "@/components/MethodHelp.vue";
import { selectedSampleIds, type PcaExplanations, type ReviewRow } from "@/utils/sampleReview";
const props = defineProps<{
  evidence?: PcaExplanations;
  selected: string[];
  rows: ReviewRow[];
  runId: number;
  components: number;
  stale: boolean;
}>();
const detail = computed(() =>
  props.evidence && !("unavailable_reason" in props.evidence) ? props.evidence : null,
);
const unavailable = computed(() =>
  props.evidence && "unavailable_reason" in props.evidence ? props.evidence.unavailable_reason : "",
);
const sample = ref("");
const features = ref<string[]>([]);
const emit = defineEmits<{
  "advisor-selection": [value: { variables: string[]; response: number; sample: string }];
}>();
watch(
  () => [features.value, 0, sample.value],
  () =>
    emit("advisor-selection", {
      variables: [...features.value],
      response: 0,
      sample: sample.value,
    }),
  { deep: true, immediate: true },
);
const component = ref(0);
const plotReset = ref(0);
function clearFeatures() {
  features.value = [];
  // Plotly can retain native lasso geometry across component/trace redraws.
  // A deliberate reset creates fresh variable plots with no native selection.
  plotReset.value++;
}
const rank = ref<"q" | "t2">("q");
watch(
  () => props.selected,
  (ids) => {
    if (!ids.includes(sample.value)) sample.value = ids[0] || "";
  },
  { immediate: true },
);
watch(
  () => [props.runId, detail.value?.model_digest, detail.value?.feature_identity, props.stale],
  () => {
    features.value = [];
    sample.value = props.selected[0] || "";
    component.value = 0;
  },
);
const row = computed(() => detail.value?.rows[sample.value]);
const observation = computed(() => props.rows.find((r) => r.id === sample.value));
const role = computed(() =>
  observation.value?.role === "excluded_projected"
    ? "Excluded — projected into this fit, not used to fit it"
    : "Calibration observation",
);
const projectionError = computed(() => observation.value?.projection_error);
const ranked = computed(() =>
  [...(row.value?.variables || [])].sort(
    (a, b) => (rank.value === "q" ? b[1] - a[1] : Math.abs(b[2]) - Math.abs(a[2])) || a[0] - b[0],
  ),
);
const featureId = (i: number) => `${detail.value?.feature_identity}:${i}`;
const featureLabel = (i: number) =>
  `${detail.value?.feature_labels?.[i] || detail.value?.feature_values?.[i] || (detail.value?.feature_values?.[i] === 0 ? "0" : "Variable")} ${detail.value?.feature_units || ""} (column ${i + 1})`;
const allowed = computed(
  () => new Set(Array.from({ length: detail.value?.feature_count || 0 }, (_, i) => featureId(i))),
);
const absentFeatures = computed(
  () =>
    features.value.filter((id) => !row.value?.variables.some((v) => featureId(v[0]) === id)).length,
);
function selectFeatures(event: unknown) {
  features.value = selectedSampleIds(event, allowed.value);
}
function toggleFeature(i: number) {
  const id = featureId(i);
  features.value = features.value.includes(id)
    ? features.value.filter((f) => f !== id)
    : [...features.value, id];
}
const preprocessorLabel = (operation: string) =>
  (
    ({
      "preprocess.scale": "Scale/center",
      "preprocess.normalize": "Normalization",
      "preprocess.smooth": "Smoothing",
      "preprocess.derivative": "Derivative",
    }) as Record<string, string>
  )[operation] || operation;
const format = (value: number) => value.toPrecision(5);
const config = { responsive: true, displaylogo: false };
const baseLayout = { height: 350, dragmode: "lasso", margin: { t: 45, l: 65, r: 20, b: 70 } };
function contributionTrace(statistic: "q" | "t2") {
  const values = [...(row.value?.variables || [])].sort((a, b) => a[0] - b[0]);
  return [
    {
      type: "scatter",
      mode: "markers",
      x: values.map((v) => v[0] + 1),
      y: values.map((v) => v[statistic === "q" ? 1 : 2]),
      customdata: values.map((v) => featureId(v[0])),
      text: values.map((v) => featureLabel(v[0])),
      marker: { color: statistic === "q" ? SCIENTIFIC_COLORS.positive : SCIENTIFIC_COLORS.negative, size: 8 },
      selected: { marker: { size: 12, opacity: 1 } },
      unselected: { marker: { opacity: 0.3 } },
      hovertemplate: "%{text}<br>Contribution: %{y:.5g}<extra></extra>",
    },
  ];
}
function contributionLayout(statistic: "q" | "t2") {
  return {
    ...baseLayout,
    title: statistic === "q" ? "Leading Q contributions" : "Leading signed T² contributions",
    xaxis: { title: "Original fitted column (sparse selection)" },
    yaxis: { title: statistic === "q" ? "Squared residual" : "Signed T² contribution" },
    uirevision: `${props.runId}:${sample.value}:${statistic}`,
  };
}
const contributionTraces = computed(() => ({
  q: contributionTrace("q"),
  t2: contributionTrace("t2"),
}));
const contributionLayouts = computed(() => ({
  q: contributionLayout("q"),
  t2: contributionLayout("t2"),
}));
const loadingTrace = computed(() => [
  {
    type: "scatter",
    mode: "lines+markers",
    x: Array.from(
      { length: detail.value?.feature_count || 0 },
      (_, i) => detail.value?.feature_values?.[i] ?? i + 1,
    ),
    y: detail.value?.loadings?.[component.value],
    customdata: Array.from(allowed.value),
    text: Array.from({ length: detail.value?.feature_count || 0 }, (_, i) => featureLabel(i)),
    marker: { size: 3, color: SCIENTIFIC_COLORS.positive },
    line: { width: 1, color: SCIENTIFIC_COLORS.positive },
    selected: { marker: { size: 7, opacity: 1 } },
    unselected: { marker: { opacity: 0.2 } },
    hovertemplate: "%{text}<br>Loading: %{y:.5g}<extra></extra>",
  },
]);
const loadingLayout = computed(() => ({
  ...baseLayout,
  title: `Fitted PC ${component.value + 1} loadings — variables only`,
  xaxis: {
    title: detail.value?.feature_values
      ? detail.value?.feature_units || "Fitted feature coordinate"
      : "Original fitted column",
  },
  yaxis: { title: "Loading" },
  uirevision: `${props.runId}:${component.value}`,
}));
</script>
<style scoped>
.pca-explanation {
  border: 1px solid var(--surface-border, var(--ss-border-strong));
  padding: 1rem;
  display: grid;
  gap: 0.6rem;
}
.explanation-plots {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
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
label {
  display: flex;
  gap: 0.6rem;
  align-items: center;
}
button {
  justify-self: start;
}
@media (max-width: 900px) {
  .explanation-plots {
    grid-template-columns: 1fr;
  }
}
</style>
