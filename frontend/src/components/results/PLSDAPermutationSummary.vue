<template>
  <section
    v-if="isPermutation"
    class="permutation-summary"
    aria-label="PLS-DA response permutation"
  >
    <h4>PLS-DA random-response check</h4>
    <p v-if="!valid">Complete permutation evidence is unavailable or inconsistent.</p>
    <template v-else>
      <p>
        Observed out-of-fold calibration-label component-search balanced accuracy:
        <strong>{{ format(observed) }}</strong
        >. {{ scores.length }} seeded label shuffles; {{ exceedances }} matched or exceeded the
        observed score. Finite-sample p-value: <strong>{{ format(probability) }}</strong
        >.
      </p>
      <p>
        Observed label search selected {{ selectedLv }} latent variable{{
          selectedLv === 1 ? "" : "s"
        }}
        from 1–{{ maximumLv }}. The connected saved model has {{ savedLv }} latent variable{{
          savedLv === 1 ? "" : "s"
        }}. The same component search was repeated for every shuffle.
      </p>
      <p>
        Design: {{ folds }} stratified folds, seed {{ seed }}, {{ calibrationRows }} calibration
        rows.
      </p>
      <svg viewBox="0 0 240 112" role="img" :aria-label="plotDescription" class="null-histogram">
        <line x1="0" y1="85" x2="240" y2="85" class="axis" />
        <rect
          v-for="(count, index) in bins"
          :key="index"
          :x="index * 24 + 2"
          :y="85 - (count / maxBin) * 70"
          width="20"
          :height="(count / maxBin) * 70"
          class="null-bar"
        />
        <line :x1="observed * 240" y1="5" :x2="observed * 240" y2="85" class="observed-line" />
        <text x="0" y="103">0</text>
        <text x="185" y="103">Balanced accuracy 1</text>
      </svg>
      <p class="key">
        <span class="null-key"></span> Shuffled-label searches
        <span class="observed-key"></span> Observed-label search
      </p>
      <p>
        This tests association against exchangeable random labels in the calibration cohort. It does
        not establish independent external validity or application-domain fitness.
      </p>
      <p v-if="blockColumn">Labels were shuffled within the recorded {{ blockColumn }} blocks.</p>
      <p>CV-ANOVA: unavailable for this PLS-DA response design.</p>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { scientificNumber } from "@/utils/scientificEncoding";

const props = defineProps<{ record?: Record<string, unknown> | null }>();
const isDigest = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const isInteger = (value: unknown) => typeof value === "number" && Number.isInteger(value);
const isPermutation = computed(
  () => props.record?.schema_version === "spectrasherpa-plsda-response-permutation/1",
);
const scores = computed(() => {
  const rows = props.record?.null;
  if (!Array.isArray(rows)) return [];
  if (
    !rows.every(
      (row) =>
        row &&
        typeof row === "object" &&
        isInteger(row.selected_components) &&
        row.selected_components >= 1 &&
        row.selected_components <= Number(props.record?.component_search_maximum) &&
        isDigest(row.split_digest),
    )
  )
    return [];
  const values = rows.map((row) => row?.balanced_accuracy);
  return values.every(
    (value) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1,
  )
    ? (values as number[])
    : [];
});
const observed = computed(() => Number(props.record?.observed));
const exceedances = computed(() => Number(props.record?.exceedances));
const probability = computed(() => Number(props.record?.p_value));
const selectedLv = computed(() => Number(props.record?.observed_reselected_components));
const savedLv = computed(() => Number(props.record?.saved_model_components));
const maximumLv = computed(() => Number(props.record?.component_search_maximum));
const folds = computed(() => Number(props.record?.folds));
const seed = computed(() => Number(props.record?.seed));
const calibrationRows = computed(() => Number(props.record?.n_calibration));
const classCountValid = computed(() => {
  const counts = props.record?.class_counts;
  if (!counts || typeof counts !== "object" || Array.isArray(counts)) return false;
  const values = Object.values(counts);
  return (
    isInteger(props.record?.n_classes) &&
    values.length === props.record?.n_classes &&
    values.every((value) => isInteger(value) && value >= 1) &&
    values.reduce<number>((sum, value) => sum + Number(value), 0) === calibrationRows.value
  );
});
const blockColumn = computed(() =>
  typeof props.record?.exchangeability_block_column === "string"
    ? props.record.exchangeability_block_column
    : null,
);
const valid = computed(() => {
  const total = props.record?.permutations_successful;
  return (
    props.record?.status === "complete" &&
    props.record.scope === "calibration_development_only_no_independent_test" &&
    props.record.metric === "balanced_accuracy" &&
    isDigest(props.record.model_state_sha256) &&
    isInteger(total) &&
    props.record.permutations_requested === total &&
    total === scores.value.length &&
    scores.value.length >= 19 &&
    scores.value.length <= 199 &&
    typeof props.record.observed === "number" &&
    Number.isFinite(observed.value) &&
    observed.value >= 0 &&
    observed.value <= 1 &&
    typeof props.record.exceedances === "number" &&
    Number.isInteger(exceedances.value) &&
    exceedances.value >= 0 &&
    exceedances.value <= scores.value.length &&
    exceedances.value === scores.value.filter((score) => score >= observed.value).length &&
    typeof props.record.p_value === "number" &&
    Math.abs(probability.value - (1 + exceedances.value) / (1 + scores.value.length)) < 1e-12 &&
    isInteger(props.record.observed_reselected_components) &&
    selectedLv.value >= 1 &&
    isInteger(props.record.saved_model_components) &&
    savedLv.value >= 1 &&
    isInteger(props.record.component_search_maximum) &&
    maximumLv.value >= Math.max(selectedLv.value, savedLv.value) &&
    isInteger(props.record.folds) &&
    folds.value >= 2 &&
    folds.value <= 5 &&
    isInteger(props.record.seed) &&
    seed.value >= 0 &&
    seed.value < 2 ** 32 &&
    isInteger(props.record.n_calibration) &&
    calibrationRows.value >= 12 &&
    calibrationRows.value <= 500 &&
    isInteger(props.record.n_units) &&
    Number(props.record.n_units) >= 6 &&
    classCountValid.value
  );
});
const bins = computed(() =>
  Array.from(
    { length: 10 },
    (_, index) =>
      scores.value.filter((score) => Math.min(9, Math.floor(score * 10)) === index).length,
  ),
);
const maxBin = computed(() => Math.max(1, ...bins.value));
const plotDescription = computed(
  () =>
    `Distribution of ${scores.value.length} shuffled-label balanced accuracy scores; observed score ${format(observed.value)} marked by a line.`,
);
const format = (value: number) => scientificNumber(value, { decimalPlaces: 4 });
</script>

<style scoped>
.permutation-summary {
  margin: 0.75rem 0;
  padding: 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 0.5rem;
}
.permutation-summary p {
  margin: 0.5rem 0;
}
.null-histogram {
  display: block;
  width: 100%;
  max-width: 440px;
  height: auto;
}
.axis {
  stroke: currentColor;
  stroke-width: 1;
}
.null-bar {
  fill: var(--ss-text-muted);
}
.observed-line {
  stroke: var(--ss-danger);
  stroke-width: 2;
}
.null-histogram text {
  fill: currentColor;
  font-size: 8px;
}
.key {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.85rem;
}
.null-key,
.observed-key {
  width: 0.7rem;
  height: 0.7rem;
  display: inline-block;
}
.null-key {
  background: var(--ss-border-strong);
}
.observed-key {
  background: var(--ss-danger);
}
</style>
