<template>
  <section v-if="protocol" class="bosch-context" aria-label="BOSCH experiment context">
    <h5>BOSCH experiment</h5>
    <dl v-if="protocol.selected_lot" class="lot-facts">
      <dt>Production lot</dt>
      <dd>{{ protocol.selected_lot.lot_number }} · {{ protocol.selected_lot.experiment_date }}</dd>
      <dt>Wafer</dt>
      <dd>{{ protocol.selected_lot.wafer_number }}</dd>
      <dt>Conditioning surface</dt>
      <dd>{{ protocol.selected_lot.conditioning_surface }}</dd>
      <dt>Conditioning repetitions</dt>
      <dd>{{ protocol.selected_lot.conditioning_repetitions }}</dd>
      <dt>Recorded wafers</dt>
      <dd>
        {{ protocol.selected_lot.recorded_wafer_count }} of
        {{ protocol.production_lot.planned_wafer_count }} planned
      </dd>
    </dl>
    <p v-else>
      Reference protocol. This source has not been matched to a published production lot.
    </p>
    <div class="protocol-sections">
      <section>
        <h6>Initial chamber preparation</h6>
        <ol>
          <li v-for="(step, index) in protocol.initial_chamber_preparation" :key="index">
            {{ step.label
            }}<template v-if="step.duration_seconds != null"
              >: {{ duration(step.duration_seconds) }}</template
            ><template v-else> · variable duration</template>
          </li>
        </ol>
      </section>
      <section>
        <h6>Conditioning experiment</h6>
        <p>Studied surfaces: {{ protocol.conditioning_experiment.surface_options.join("; ") }}.</p>
        <p>Repeat {{ protocol.conditioning_experiment.repetition_options.join(", ") }} times.</p>
        <ol>
          <li v-for="(step, index) in protocol.conditioning_experiment.sequence" :key="index">
            {{ step.label }}: {{ duration(step.duration_seconds) }}
          </li>
        </ol>
        <p>
          Break between repetitions:
          {{ duration(protocol.conditioning_experiment.break_between_repetitions_seconds) }}.
        </p>
      </section>
      <section>
        <h6>Production lot</h6>
        <p>
          {{ protocol.production_lot.planned_wafer_count }} planned production wafers,
          {{ protocol.production_lot.bosch_cycles_per_wafer }} BOSCH cycles per wafer.
        </p>
        <p>
          Break between wafers:
          {{ duration(protocol.production_lot.break_between_wafers_seconds) }}.
        </p>
        <p>Between production wafers:</p>
        <ol>
          <li v-for="(step, index) in protocol.production_lot.inter_wafer_sequence" :key="index">
            {{ step.label
            }}<template v-if="step.duration_seconds != null"
              >: {{ duration(step.duration_seconds) }}</template
            ><template v-else> · variable duration</template>
          </li>
        </ol>
        <p>EPD clean after the last wafer: {{ protocol.production_lot.post_lot_clean_status }}.</p>
        <details>
          <summary>Recipe and recorded signals</summary>
          <p>{{ protocol.production_lot.epd_sequence_basis }}</p>
          <p>{{ protocol.production_lot.source_discrepancy }}</p>
          <p>{{ protocol.production_lot.observed_post_etch_plasma }}</p>
        </details>
      </section>
    </div>
    <small
      >Protocol: Readme.pdf, §1 and Figure 1. Lot conditions: Lot_status.xlsx.
      <a href="https://zenodo.org/records/17122442" target="_blank" rel="noopener noreferrer"
        >Source dataset</a
      ></small
    >
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";

type Step = { label: string; duration_seconds: number | null };
type Protocol = {
  schema_version: "spectrasherpa.bosch-experiment-context/1";
  initial_chamber_preparation: Step[];
  conditioning_experiment: {
    surface_options: string[];
    repetition_options: number[];
    sequence: Step[];
    break_between_repetitions_seconds: number;
  };
  production_lot: {
    planned_wafer_count: number;
    bosch_cycles_per_wafer: number;
    break_between_wafers_seconds: number;
    inter_wafer_sequence: Step[];
    post_lot_clean_status: string;
    epd_sequence_basis: string;
    source_discrepancy: string;
    observed_post_etch_plasma: string;
  };
  selected_lot: {
    lot_number: number;
    experiment_date: string;
    wafer_number: number;
    conditioning_surface: string;
    conditioning_repetitions: number;
    recorded_wafer_count: number;
  } | null;
};
const props = defineProps<{ context: unknown }>();
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function steps(value: unknown): value is Step[] {
  return (
    Array.isArray(value) &&
    value.every(
      (step) =>
        record(step) &&
        typeof step.label === "string" &&
        (step.duration_seconds === null || typeof step.duration_seconds === "number"),
    )
  );
}
const protocol = computed<Protocol | null>(() => {
  const value = props.context;
  if (
    !record(value) ||
    value.schema_version !== "spectrasherpa.bosch-experiment-context/1" ||
    !steps(value.initial_chamber_preparation)
  )
    return null;
  const conditioning = value.conditioning_experiment,
    production = value.production_lot;
  if (
    !record(conditioning) ||
    !steps(conditioning.sequence) ||
    !Array.isArray(conditioning.surface_options) ||
    !conditioning.surface_options.every((v) => typeof v === "string") ||
    !Array.isArray(conditioning.repetition_options) ||
    !conditioning.repetition_options.every((v) => typeof v === "number") ||
    typeof conditioning.break_between_repetitions_seconds !== "number"
  )
    return null;
  if (
    !record(production) ||
    !steps(production.inter_wafer_sequence) ||
    !["planned_wafer_count", "bosch_cycles_per_wafer", "break_between_wafers_seconds"].every(
      (key) => typeof production[key] === "number",
    )
  )
    return null;
  if (value.selected_lot !== null) {
    const lot = value.selected_lot;
    if (
      !record(lot) ||
      typeof lot.experiment_date !== "string" ||
      typeof lot.conditioning_surface !== "string" ||
      !["lot_number", "wafer_number", "conditioning_repetitions", "recorded_wafer_count"].every(
        (key) => typeof lot[key] === "number",
      )
    )
      return null;
  }
  return value as unknown as Protocol;
});
function duration(seconds: number | null): string {
  if (seconds === null) return "variable duration";
  return seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`;
}
</script>

<style scoped>
.bosch-context {
  margin-top: 1rem;
}
.bosch-context h5 {
  margin: 0 0 0.75rem;
}
.protocol-sections {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1.5rem;
}
.protocol-sections h6 {
  font-size: inherit;
  margin: 0.75rem 0;
}
.protocol-sections ol {
  padding-left: 1.25rem;
  line-height: 1.7;
}
.protocol-sections p {
  line-height: 1.5;
}
.lot-facts {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 0.4rem 1rem;
}
.lot-facts dt {
  font-weight: 600;
}
.lot-facts dd {
  margin: 0;
}
</style>
