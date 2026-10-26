<template>
  <div aria-label="Processing step selection">
    <p v-if="!hideInstructions" class="footnote">
      Select wafer numbers by day and step. Hover or focus for acquisition times and ranges. Breaks
      are excluded.
    </p>
    <div class="matrix" @scroll="hover?.hide()">
      <table>
        <thead>
          <tr>
            <th>Day</th>
            <th>Preparation</th>
            <th>Conditioning</th>
            <th v-for="column in columns" :key="column.id">{{ column.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in entries" :key="entry.file.id">
            <th>
              {{ entry.catalog.date }}<small>{{ entry.file.file_path.split("/").pop() }}</small>
            </th>
            <td v-for="stage in ['Preparation', 'Conditioning']" :key="stage">
              <span
                class="unavailable"
                :title="`${stage}: no identified source interval in these wafer recordings`"
                >No identified interval</span
              >
            </td>
            <td v-for="column in columns" :key="column.id">
              <section
                v-if="available(entry, column).length"
                class="step-box"
                :class="[
                  column.id === 'production' ? 'bosch' : 'clean',
                  {
                    selected: available(entry, column).some((w) => isChosen(entry, w, column)),
                  },
                ]"
              >
                <strong>{{ column.recipe }}</strong
                ><small>{{ column.note }}</small>
                <div class="wafers">
                  <button
                    v-for="wafer in available(entry, column)"
                    :key="wafer.asset_id"
                    :aria-label="`${entry.catalog.date}, ${column.label}, ${wafer.asset_id}`"
                    :aria-pressed="isChosen(entry, wafer, column)"
                    :class="{ picked: isChosen(entry, wafer, column) }"
                    :style="isChosen(entry, wafer, column) ? { backgroundColor: groupColors?.[stepSelectionKey({experiment_id: entry.experimentId, file_id: entry.file.id, asset_id: wafer.asset_id, step_id: column.id as StepSelection['step_id']})] } : undefined"
                    @click="toggle(entry, wafer, column)"
                    @mouseenter="show(entry, wafer, column, $event)"
                    @mousemove="show(entry, wafer, column, $event, true)"
                    @mouseleave="hover?.hidePointer()"
                    @focus="show(entry, wafer, column, $event)"
                    @blur="hover?.hide()"
                  >
                    {{ wafer.asset_id.replace("Wafer_", "") }}
                  </button>
                </div>
              </section>
              <span v-else>Not recorded</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <PlateWellHoverCard ref="hover" />
  </div>
</template>
<script setup lang="ts">
import { ref } from "vue";
import PlateWellHoverCard from "@/components/PlateWellHoverCard.vue";
import { stepSelectionKey } from "./composables/useProcessingStepSelection";
import type { StepEntry, StepSelection } from "./composables/useProcessingStepSelection";
type Entry = StepEntry;
type Wafer = Entry["catalog"]["wafers"][number];
const props = defineProps<{ entries: Entry[]; modelValue: StepSelection[]; groupColors?: Record<string, string>; hideInstructions?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: StepSelection[]] }>();
const hover = ref<InstanceType<typeof PlateWellHoverCard> | null>(null);
const columns = [
  {
    id: "mixed",
    label: "Mixed-gas plasma",
    recipe: "Mixed flow",
    note: "Brief interval · unassigned protocol step",
    phases: ["mixed_plasma"],
  },
  {
    id: "production",
    label: "Production etch",
    recipe: "BOSCH",
    note: "SF₆ ⇄ C₄F₈ · repeated phases",
    phases: ["etch", "passivation"],
  },
  {
    id: "gas1",
    label: "Post-production plasma",
    recipe: "Gas1 only",
    note: "O₂ tentative · EPD not established",
    phases: ["gas1_plasma"],
  },
];
type Column = (typeof columns)[number];

const steps = (wafer: Wafer, column: Column) =>
  wafer.steps.filter((s) => column.phases.includes(s.step_id));
const available = (entry: Entry, column: Column) =>
  entry.catalog.wafers.filter((w) => !w.refusal && steps(w, column).length);
const isChosen = (entry: Entry, wafer: Wafer, column: Column) =>
  props.modelValue.some(
    (s) =>
      s.experiment_id === entry.experimentId &&
      s.file_id === entry.file.id &&
      s.asset_id === wafer.asset_id &&
      s.step_id === column.id,
  );
function toggle(entry: Entry, wafer: Wafer, column: Column) {
  const selection: StepSelection = {
    experiment_id: entry.experimentId,
    file_id: entry.file.id,
    process_file_id: entry.catalog.process_file_id!,
    asset_id: wafer.asset_id,
    step_id: column.id as StepSelection["step_id"],
  };
  emit(
    "update:modelValue",
    isChosen(entry, wafer, column)
      ? props.modelValue.filter(
          (s) =>
            !(
              s.experiment_id === selection.experiment_id &&
              s.file_id === selection.file_id &&
              s.asset_id === selection.asset_id &&
              s.step_id === selection.step_id
            ),
        )
      : [...props.modelValue, selection],
  );
}
function show(
  entry: Entry,
  wafer: Wafer,
  column: Column,
  event: MouseEvent | FocusEvent,
  moved = false,
) {
  const intervals = steps(wafer, column)
    .flatMap((s) => s.intervals)
    .sort((a, b) => a.first_acquisition - b.first_acquisition);
  hover.value?.show(
    {
      well_position: entry.catalog.date,
      label: `${wafer.asset_id} · ${column.label}`,
      details: [
        { label: "Recipe / assignment", value: column.note },
        {
          label: "UTC start / end",
          value: `${new Date(intervals[0].start_time * 1000).toISOString()} / ${new Date(intervals[intervals.length - 1].end_time * 1000).toISOString()}`,
        },
        {
          label: "Acquisitions",
          value:
            intervals
              .slice(0, 8)
              .map((i) => `${i.first_acquisition}–${i.last_acquisition}`)
              .join(", ") +
            (intervals.length > 8 ? ` … (${intervals.length} separate intervals)` : ""),
        },
        {
          label: "Observation count",
          value: String(steps(wafer, column).reduce((n, s) => n + s.acquisition_count, 0)),
        },
        {
          label: "Cycle identity",
          value: "Not retained in this alignment version; interval count is not a cycle count",
        },
        {
          label: "Clock fit / boundary uncertainty",
          value: `${Number(wafer.alignment?.correlation).toFixed(3)} / ±${Number(wafer.alignment?.boundary_uncertainty_s).toFixed(2)} s`,
        },
        { label: "Source", value: entry.file.file_path },
        { label: "Source SHA-256", value: entry.catalog.source_sha256 },
      ],
    },
    event,
    moved,
  );
}
</script>
<style scoped>
.footnote,
.unavailable {
  color: var(--ss-text-muted);
}
small {
  display: block;
  font-weight: normal;
  margin-top: 0.4rem;
}
.matrix {
  max-height: 32rem;
  overflow: auto;
  padding: 0.5rem;
  border: 1px solid var(--ss-border-strong);
  border-radius: 8px;
  background: var(--ss-surface);
}
table {
  border-spacing: 12px;
  width: 100%;
}
th {
  text-align: left;
  background: var(--ss-surface);
}
thead th {
  position: sticky;
  top: 0;
  z-index: 2;
}
tbody th {
  position: sticky;
  left: 0;
  z-index: 1;
  min-width: 9rem;
}
td {
  text-align: center;
}
.step-box {
  border: 2px solid var(--ss-border-strong);
  border-radius: 8px;
  padding: 0.75rem;
  min-width: 200px;
  transition: transform 0.15s;
}
.step-box.selected {
  transform: scale(1.025);

}
.bosch {
  border-color: var(--ss-info-strong);
  --recipe-color: var(--ss-info-strong);
  background: var(--ss-info-surface);
  color: var(--ss-info-strong);
}
.clean {
  border-color: var(--ss-success-strong);
  --recipe-color: var(--ss-success-strong);
  background: var(--ss-success-surface);
  color: var(--ss-success-strong);
}
.wafers {
  display: grid;
  grid-template-columns: repeat(5, 2rem);
  gap: 6px;
  margin: 0.8rem 0;
}
button {
  height: 2rem;
  border: 2px solid var(--recipe-color);
  border-radius: 6px;
  background: var(--ss-surface);
  color: var(--ss-text);
  cursor: pointer;
}
button.picked {
  transform: scale(1.08);
  background: var(--ss-action);
  color: var(--ss-surface);
}
button:focus-visible {
  outline: 2px solid var(--ss-action);
  outline-offset: 2px;
}
</style>
