<template>
  <details v-if="selection" @toggle="open = ($event.target as HTMLDetailsElement).open">
    <summary>Sample map · {{ selection.retainedRows }} retained · {{ selection.inputRows - selection.retainedRows }} excluded</summary>
    <DataTable v-if="open" :value="rows" scrollable scrollHeight="360px" size="small"
      :paginator="limit > 0 && selection.inputRows > limit" :rows="limit || selection.inputRows">
      <Column field="inputRow" header="Input row" />
      <Column field="sample" header="Sample" />
      <Column field="status" header="Status" />
      <Column field="resultRow" header="Result row" />
    </DataTable>
  </details>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import { sampleSelectionMap } from "@/utils/sampleSelectionMap";

const props = defineProps<{ value: unknown; count: number; limit: number }>();
const open = ref(false);
const selection = computed(() => sampleSelectionMap(props.value, props.count));
const rows = computed(() => {
  if (!open.value || !selection.value) return [];
  const payload = props.value as { sample_axis?: { labels?: unknown }; y_axis?: { labels?: unknown } };
  const labels = payload.sample_axis?.labels ?? payload.y_axis?.labels;
  const aligned = Array.isArray(labels) && labels.length === props.count;
  // Only the retained result can name its rows. A current connection—even an
  // equal-sized one—does not establish the input to an earlier execution.
  return Array.from({ length: selection.value.inputRows }, (_, index) => {
    const resultRow = selection.value!.resultRows.get(index);
    return {
      inputRow: index + 1,
      sample: aligned && resultRow != null ? String(labels[resultRow - 1] ?? "") : "—",
      status: resultRow != null ? "Retained" : "Excluded",
      resultRow: resultRow ?? "—",
    };
  });
});
</script>
