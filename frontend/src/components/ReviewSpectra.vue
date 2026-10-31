<template>
  <section :aria-label="title || 'Linked source spectra'">
    <p>
      {{ title || "Source spectra" }}: showing {{ visibleRows.length }} of
      {{ rows.length }} observations (maximum 32 curves). Selected curves have priority;
      {{ hiddenSelected }} selected observations are outside this view.
      {{ spectra.display_count }} of {{ spectra.variable_count }}
      variables displayed.
      <span v-if="spectra.display_count < spectra.variable_count"
        >Display is sampled; narrow features between displayed variables are not selectable here.
        Model fitting uses every model-input variable.</span
      >
    </p>
    <p v-if="spectra.missing_ids?.length">
      {{ spectra.missing_ids.length }} observations have no retained curves in this space; use the
      table to inspect them.
    </p>
    <label
      >First curve
      <input v-model.number="offset" type="number" min="0" :max="Math.max(0, rows.length - 1)"
    /></label>
    <p>
      Lasso displayed spectral points to select their whole observations. Use the table for samples
      outside this view.
    </p>
    <PlotlyChart
      :data="traces"
      :layout="layout"
      :config="config"
      :selected-point-ids="selected"
      link-line-selection
      @selected="emit('selected', $event)"
      @deselect="emit('deselect')"
    />
  </section>
</template>
<script setup lang="ts">
import { reviewRowLabel } from "@/utils/sampleReview";
import { escapeScientificText } from "@/utils/validationReportPlots";
import { computed, ref } from "vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import type { ReviewRow, SpectralDisplay } from "@/utils/sampleReview";
const props = defineProps<{
  spectra: SpectralDisplay;
  rows: ReviewRow[];
  selected: string[];
  marked: string[];
  masked: string[];
  colors: Map<string, string>;
  title?: string;
}>();
const emit = defineEmits<{ selected: [event: unknown]; deselect: [] }>();
const config = { responsive: true, displaylogo: false };
const offset = ref(0);
const selectedSet = computed(() => new Set(props.selected));
const visibleRows = computed<ReviewRow[]>((previous) => {
  const ordered = [
    ...props.rows.filter((r) => selectedSet.value.has(r.id) && r.id in props.spectra.rows),
    ...props.rows.slice(Math.max(0, offset.value || 0)).filter((r) => r.id in props.spectra.rows),
  ];
  const next = [...new Map(ordered.map((r) => [r.id, r])).values()].slice(0, 32);
  // Keep trace order and identity stable when only the selection changes.
  if (previous && previous.length === next.length && previous.every((row) => next.includes(row)))
    return previous;
  return next;
});
const hiddenSelected = computed(
  () => props.selected.length - visibleRows.value.filter((r) => selectedSet.value.has(r.id)).length,
);
const traces = computed(() =>
  visibleRows.value.map((row) => ({
    type: "scatter",
    mode: "lines+markers",
    name: escapeScientificText(reviewRowLabel(row)),
    showlegend: false,
    x: props.spectra.x,
    y: props.spectra.rows[row.id],
    customdata: props.spectra.x.map(() => row.id),
    text: props.spectra.x.map(() => escapeScientificText(reviewRowLabel(row))),
    hovertemplate: "%{text}<br>%{x}: %{y:.5g}<extra></extra>",
    line: {
      color: props.colors.get(row.group),
      width: 1,
      dash: row.role === "excluded_projected" || props.masked.includes(row.id) ? "dot" : "solid",
    },
    opacity: 1,
    marker: {
      size: 3,
      color: props.colors.get(row.group),
      symbol: props.marked.includes(row.id) ? "diamond-open" : "circle",
    },
    selected: { marker: { size: 5, opacity: 1 } },
    unselected: { marker: { opacity: 0.2 } },
  })),
);
const layout = computed(() => ({
  height: 350,
  dragmode: "lasso",
  title: props.title || "Linked source spectra",
  xaxis: { title: props.spectra.units || "Original variable" },
  yaxis: { title: props.spectra.signal_units || "Signal intensity" },
  uirevision: props.title || "review-spectra",
  margin: { t: 40, l: 60, r: 20, b: 55 },
}));
</script>
