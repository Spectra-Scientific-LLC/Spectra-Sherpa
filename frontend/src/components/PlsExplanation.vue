<template>
  <section class="pls-explanation" aria-label="PLS prediction explanations">
    <h3>Why does this prediction differ from the calibration reference?</h3>
    <p v-if="stale" role="status">
      Rerun the current workflow. Previous-fit explanations are hidden.
    </p>
    <p v-else-if="!detail" role="status">
      {{ unavailable || "This run has no PLS explanation evidence. Rerun to enable explanations." }}
    </p>
    <template v-else>
      <p>
        Select observations in the review charts or table, then choose one to explain. Variable
        highlights below do not mark or exclude observations.
      </p>
      <label
        >Sample to explain
        <select v-model="sample" aria-label="Sample to explain">
          <option value="">Select a sample</option>
          <option v-for="id in selected" :key="id" :value="id">{{ id }}</option>
        </select>
      </label>
      <label
        >Response
        <select v-model.number="target" aria-label="Explanation response">
          <option v-for="(name, i) in responseNames" :key="i" :value="i">{{ name }}</option>
        </select>
      </label>
      <p>
        Reference: {{ detail.reference_count }} retained calibration observations. Fitted Y mean for
        {{ responseNames[target] }}: {{ format(detail.baseline[target]) }} {{ units }}.
        Contributions use the input to PLS after workflow preprocessing:
        {{ detail.preprocessing.map(preprocessorLabel).join(" → ") || "none before PLS" }}. Internal
        autoscaling is {{ detail.internal_scale ? "on" : "off" }}; the saved coefficients already
        account for it. Contributions are in response units, relative to the fitted X mean.
      </p>
      <template v-if="row">
        <p>
          <strong>{{ sample }}</strong> · {{ role }}
        </p>
        <p v-if="observation?.role === 'held_out_test'" role="note">
          Held-out inspection: using this explanation to tune the model makes subsequent development
          adaptive. Every original test observation remains in full-test metrics.
        </p>
        <p>
          Prediction: {{ format(row.prediction) }} {{ units }} = fitted reference
          {{ format(detail.baseline[target]) }} + total signed contribution
          {{ format(row.contribution_total) }}. Observed reference:
          {{ format(observation?.reference?.[target]) }}; residual (reference − prediction):
          {{ format(observation?.residual?.[target]) }} {{ units }}.
        </p>
        <p>
          These terms explain the prediction, not the residual error or chemical causation.
          Correlated variables can cancel; smoothing and derivatives mix neighboring variables.
        </p>
        <p>
          Showing {{ row.variables.length }} of {{ detail.feature_count }} variables, ranked by
          absolute contribution. Omitted signed sum: {{ format(row.omitted_signed) }}; omitted
          absolute mass: {{ format(row.omitted_absolute) }} {{ units }}. Omitted variables are not
          zero; a small signed remainder can hide cancellation.
        </p>
        <PlotlyChart
          :key="`contribution:${plotReset}`"
          :data="contributionTrace"
          :layout="contributionLayout"
          :config="config"
          :selected-point-ids="features"
          @selected="selectFeatures"
          @deselect="features = []"
        />
        <div class="variable-table">
          <table>
            <caption>
              Leading contributions to
              {{
                responseNames[target]
              }}
            </caption>
            <thead>
              <tr>
                <th>Highlight</th>
                <th>Variable (original column)</th>
                <th>Signed contribution ({{ units }})</th>
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
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <p v-else-if="sample" role="status">
        Explanation unavailable for {{ sample }}:
        {{ observation?.projection_error || "No exact projected observation was retained." }}
      </p>
      <p v-else role="status">Select an observation to see its prediction contributions.</p>
      <p aria-live="polite">
        {{ features.length }} variables highlighted; {{ absentFeatures }} are outside this
        response's leading contribution list.
      </p>
      <button type="button" @click="clearFeatures">Reset variable highlights and plots</button>
      <template v-if="detail.coefficients">
        <label
          >Fitted variable profile
          <select v-model="profile" aria-label="Fitted variable profile">
            <option value="coefficients">Response coefficients</option>
            <option value="loadings">PLS X loadings</option>
            <option value="vip">Combined VIP</option>
          </select>
        </label>
        <label v-if="profile === 'loadings'"
          >Loading component
          <select v-model.number="component" aria-label="Loading component">
            <option v-for="(_, i) in detail.loadings" :key="i" :value="i">LV {{ i + 1 }}</option>
          </select>
        </label>
        <p v-if="profile === 'coefficients'">
          Coefficients are in {{ units }} per
          {{ detail.signal_units || "model-input signal unit (unspecified)" }}. Feature-coordinate
          units such as wavelength do not define coefficient units.
        </p>
        <p v-else-if="profile === 'loadings'">
          PLS X loadings describe the centered{{ detail.internal_scale ? "/autoscaled" : "" }}
          latent model. They are not response coefficients or orthonormal PCA directions. Switching
          components does not change the prediction contributions.
        </p>
        <p v-else>
          Combined VIP summarizes all fitted responses; it is neither response-specific nor a signed
          contribution, and is not a significance test or automatic variable-selection rule.
        </p>
        <PlotlyChart
          :key="`profile:${plotReset}`"
          :data="profileTrace"
          :layout="profileLayout"
          :config="config"
          :selected-point-ids="features"
          link-line-selection
          @selected="selectFeatures"
          @deselect="features = []"
        />
        <p>
          All {{ detail.feature_count }} fitted variables shown. Lasso highlights variables only.
        </p>
      </template>
      <p v-else>{{ detail.profiles_unavailable_reason }}</p>
      <details>
        <summary>Explanation provenance and formula</summary>
        <p>
          Run {{ runId }} · {{ detail.formula }}. B is feature × response; loadings are displayed
          component × feature.
        </p>
        <p class="digest">
          Model {{ detail.model_digest }}<br />Feature identity {{ detail.feature_identity }}<br />
          Calibration reference {{ detail.reference_digest }}
        </p>
      </details>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { selectedSampleIds, type PlsExplanations, type ReviewRow } from "@/utils/sampleReview";
const props = defineProps<{
  evidence?: PlsExplanations;
  selected: string[];
  rows: ReviewRow[];
  runId: number;
  stale: boolean;
}>();
const detail = computed(() =>
  props.evidence && !("unavailable_reason" in props.evidence) ? props.evidence : null,
);
const unavailable = computed(() =>
  props.evidence && "unavailable_reason" in props.evidence ? props.evidence.unavailable_reason : "",
);
const sample = ref("");
const target = ref(0);
const features = ref<string[]>([]);
const emit = defineEmits<{
  "advisor-selection": [
    value: { variables: string[]; response: number; sample: string; activate?: boolean },
  ];
}>();
function emitAdvisorSelection(activate = false) {
  emit("advisor-selection", {
    variables: [...features.value],
    sample: sample.value,
    response: target.value,
    ...(activate ? { activate: true } : {}),
  });
}
watch(
  () => [features.value, target.value, sample.value],
  () => emitAdvisorSelection(),
  { deep: true },
);
const profile = ref<"coefficients" | "loadings" | "vip">("coefficients");
const component = ref(0);
const plotReset = ref(0);
function clearFeatures() {
  features.value = [];
  plotReset.value++;
}
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
    clearFeatures();
    sample.value = props.selected[0] || "";
    target.value = 0;
    component.value = 0;
    profile.value = "coefficients";
  },
);
const responseNames = computed(
  () =>
    detail.value?.response_identity.names ||
    detail.value?.baseline.map((_, i) => `Target ${i + 1}`) ||
    [],
);
const units = computed(
  () => detail.value?.response_identity.units[target.value] || "response units (unspecified)",
);
const row = computed(() => detail.value?.rows[sample.value]?.[target.value]);
const observation = computed(() => props.rows.find((r) => r.id === sample.value));
const role = computed(() =>
  observation.value?.role === "excluded_projected"
    ? "Excluded — projected into this fit, not used to fit it"
    : observation.value?.role === "held_out_test"
      ? "Held-out test observation"
      : "Calibration observation",
);
const ranked = computed(() =>
  [...(row.value?.variables || [])].sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]) || a[0] - b[0]),
);
const featureId = (i: number) => `${detail.value?.feature_identity}:${i}`;
const featureLabel = (i: number) =>
  `${detail.value?.feature_labels?.[i] || (detail.value?.feature_values?.[i] ?? "Variable")} ${detail.value?.feature_units || ""} (column ${i + 1})`;
const allowed = computed(
  () => new Set(Array.from({ length: detail.value?.feature_count || 0 }, (_, i) => featureId(i))),
);
const absentFeatures = computed(
  () =>
    features.value.filter((id) => !row.value?.variables.some((v) => featureId(v[0]) === id)).length,
);
function selectFeatures(event: unknown) {
  features.value = selectedSampleIds(event, allowed.value);
  emitAdvisorSelection(true);
}
function toggleFeature(i: number) {
  const id = featureId(i);
  features.value = features.value.includes(id)
    ? features.value.filter((f) => f !== id)
    : [...features.value, id];
  emitAdvisorSelection(true);
}
const preprocessorLabel = (op: string) =>
  (
    ({
      "preprocess.scale": "Scale/center",
      "preprocess.normalize": "Normalization",
      "preprocess.smooth": "Smoothing",
      "preprocess.derivative": "Derivative",
    }) as Record<string, string>
  )[op] || op;
const format = (value?: number) => (value === undefined ? "unavailable" : value.toPrecision(5));
const config = { responsive: true, displaylogo: false };
const baseLayout = { height: 350, dragmode: "lasso", margin: { t: 45, l: 85, r: 20, b: 70 } };
const contributionTrace = computed(() => {
  const values = [...(row.value?.variables || [])].sort((a, b) => a[0] - b[0]);
  return [
    {
      type: "scatter",
      mode: "markers",
      x: values.map((v) => v[0] + 1),
      y: values.map((v) => v[1]),
      customdata: values.map((v) => featureId(v[0])),
      text: values.map((v) => featureLabel(v[0])),
      marker: { size: 8, color: values.map((v) => (v[1] < 0 ? "#D55E00" : "#0072B2")) },
      selected: { marker: { size: 12, opacity: 1 } },
      unselected: { marker: { opacity: 0.3 } },
      hovertemplate: "%{text}<br>Signed contribution: %{y:.5g}<extra></extra>",
    },
  ];
});
const contributionLayout = computed(() => ({
  ...baseLayout,
  title: `Leading contributions to ${responseNames.value[target.value]}`,
  xaxis: { title: "Original fitted column (sparse selection)" },
  yaxis: { title: units.value },
  uirevision: `${props.runId}:${sample.value}:${target.value}`,
}));
const profileTitle = computed(() =>
  profile.value === "loadings"
    ? `Fitted LV ${component.value + 1} X loadings`
    : profile.value === "vip"
      ? "Combined VIP — all responses"
      : `Coefficients for ${responseNames.value[target.value]}`,
);
const profileTrace = computed(() => [
  {
    type: "scatter",
    mode: "lines+markers",
    x: Array.from(
      { length: detail.value?.feature_count || 0 },
      (_, i) => detail.value?.feature_values?.[i] ?? i + 1,
    ),
    y:
      profile.value === "loadings"
        ? detail.value?.loadings?.[component.value]
        : profile.value === "vip"
          ? detail.value?.vip
          : detail.value?.coefficients?.[target.value],
    customdata: Array.from(allowed.value),
    text: Array.from({ length: detail.value?.feature_count || 0 }, (_, i) => featureLabel(i)),
    marker: { size: 3, color: "#0072B2" },
    line: { width: 1, color: "#0072B2" },
    selected: { marker: { size: 7, opacity: 1 } },
    unselected: { marker: { opacity: 0.2 } },
    hovertemplate: "%{text}<br>Value: %{y:.5g}<extra></extra>",
  },
]);
const profileLayout = computed(() => ({
  ...baseLayout,
  title: profileTitle.value,
  xaxis: {
    title: detail.value?.feature_values
      ? detail.value.feature_units || "Fitted feature coordinate"
      : "Original fitted column",
  },
  yaxis: {
    title:
      profile.value === "coefficients"
        ? "Response units / model-input signal unit"
        : profile.value === "vip"
          ? "Combined VIP"
          : "X loading",
  },
  uirevision: `${props.runId}:${profile.value}:${component.value}:${target.value}`,
}));
</script>
<style scoped>
.pls-explanation {
  border: 1px solid var(--surface-border, #ccc);
  padding: 1rem;
  display: grid;
  gap: 0.6rem;
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
  border-bottom: 1px solid var(--surface-border, #ccc);
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
</style>
