<template>
  <div class="matrix-wrap">
    <div class="matrix-meta">
      <span
        >{{ displayedRows.length.toLocaleString() }} x
        {{ matrix.cols_shown.toLocaleString() }} shown</span
      >
      <span v-if="matrix.truncated || displayedRows.length < matrix.matrix.length">
        of {{ matrix.total_rows.toLocaleString() }} x {{ matrix.total_cols.toLocaleString() }}
      </span>
      <DisplaySubsetIndicator v-if="hasSubset" />
      <MethodHelp
        v-if="displayedRows.length < matrix.matrix.length"
        topic="displayExports"
        label="Table display limits"
        context="Display Settings limit the rows shown. Dataset values and exports are unchanged."
      />
    </div>
    <div ref="scrollEl" class="matrix-scroll" @scroll="onScroll">
      <table class="matrix-table">
        <thead>
          <tr>
            <th v-if="selectionRows" class="selection-head">Include</th>
            <th class="row-head">{{ matrix.y_title || "Sample" }}</th>
            <th v-for="label in matrix.col_labels" :key="label" :title="xTitle">
              {{ label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="topSpacerHeight > 0" aria-hidden="true">
            <td v-if="selectionRows" :style="{ height: `${topSpacerHeight}px` }"></td>
            <td :style="{ height: `${topSpacerHeight}px` }"></td>
            <td :colspan="matrix.col_labels.length"></td>
          </tr>
          <tr v-for="row in visibleRows" :key="row.index">
            <td v-if="selectionRows" class="selection-cell">
              <input
                v-if="selectionRows[row.index]"
                type="checkbox"
                :aria-label="`Include sample ${selectionRows[row.index]!.sampleId}`"
                :checked="selectionRows[row.index]!.checked"
                :disabled="selectionDisabled || !selectionRows[row.index]!.sourceIncluded"
                @change="emit('toggle-sample', selectionRows[row.index]!.sampleId)"
              />
            </td>
            <th class="row-head" :title="row.label">{{ row.label }}</th>
            <td v-for="(value, colIndex) in row.values" :key="colIndex">
              {{ formatValue(value) }}
            </td>
          </tr>
          <tr v-if="bottomSpacerHeight > 0" aria-hidden="true">
            <td v-if="selectionRows" :style="{ height: `${bottomSpacerHeight}px` }"></td>
            <td :style="{ height: `${bottomSpacerHeight}px` }"></td>
            <td :colspan="matrix.col_labels.length"></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import MethodHelp from "@/components/MethodHelp.vue";
import DisplaySubsetIndicator from "@/components/DisplaySubsetIndicator.vue";
import { computed, ref, watch } from "vue";
import { displayNumber, useDisplayPreferences } from "@/composables/useDisplayPreferences";
import type { DataMatrixResponse } from "@/stores/data";

interface MatrixSelectionRow {
  sampleId: string;
  checked: boolean;
  sourceIncluded: boolean;
}

const props = defineProps<{
  matrix: DataMatrixResponse;
  selectionRows?: Array<MatrixSelectionRow | null>;
  selectionDisabled?: boolean;
}>();
const displayPreferences = useDisplayPreferences();
const displayedRows = computed(() => props.matrix.matrix.slice(0, displayPreferences.maxRows));
const hasSubset = computed(() => props.matrix.truncated || displayedRows.value.length < props.matrix.total_rows ||
  props.matrix.cols_shown < props.matrix.total_cols);
const emit = defineEmits<{ "toggle-sample": [sampleId: string] }>();

const rowHeight = 18;
const viewportRows = 120;
const scrollTop = ref(0);
const scrollEl = ref<HTMLElement | null>(null);
watch(
  () => props.matrix.row_start,
  () => {
    scrollTop.value = 0;
    if (scrollEl.value) scrollEl.value.scrollTop = 0;
  },
);
watch(() => displayPreferences.maxRows, () => {
  scrollTop.value = 0;
  if (scrollEl.value) scrollEl.value.scrollTop = 0;
});

const startRow = computed(() => Math.max(0, Math.floor(scrollTop.value / rowHeight) - 4));
const endRow = computed(() => Math.min(displayedRows.value.length, startRow.value + viewportRows));
const visibleRows = computed(() =>
  displayedRows.value.slice(startRow.value, endRow.value).map((values, offset) => {
    const index = startRow.value + offset;
    return {
      index,
      label: props.matrix.row_labels[index] ?? String(index + 1),
      values,
    };
  }),
);
const topSpacerHeight = computed(() => startRow.value * rowHeight);
const bottomSpacerHeight = computed(
  () => Math.max(0, displayedRows.value.length - endRow.value) * rowHeight,
);
const xTitle = computed(() => {
  if (props.matrix.x_title && props.matrix.x_units)
    return `${props.matrix.x_title} (${props.matrix.x_units})`;
  return props.matrix.x_title || "";
});

function onScroll() {
  scrollTop.value = scrollEl.value?.scrollTop ?? 0;
}

function formatValue(value: number | string | null): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return Number.isFinite(value) ? displayNumber(value, 5) : "";
  return value;
}
</script>

<style scoped>
.matrix-wrap {
  min-height: 0;
}

.matrix-meta {
  display: flex;
  gap: 0.4rem;
  color: var(--text-color-secondary);
  font-size: 0.8rem;
  margin-bottom: 0.5rem;
}

.matrix-scroll {
  max-height: 460px;
  overflow: auto;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
}

.matrix-table {
  border-collapse: separate;
  border-spacing: 0;
  min-width: 100%;
  font-size: 0.7rem;
}

th,
td {
  border-right: 1px solid var(--surface-border);
  border-bottom: 1px solid var(--surface-border);
  padding: 0.08rem 0.32rem;
  height: 18px;
  line-height: 1.05;
  white-space: nowrap;
  text-align: right;
  background: var(--surface-card);
}

thead th {
  position: sticky;
  top: 0;
  z-index: 3;
  background: var(--surface-ground);
  font-weight: 600;
}

.row-head {
  position: sticky;
  left: 0;
  z-index: 2;
  text-align: left;
  max-width: 210px;
  min-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  background: var(--surface-ground);
}

.selection-head,
.selection-cell {
  position: sticky;
  left: 0;
  z-index: 3;
  min-width: 2.4rem;
  width: 2.4rem;
  text-align: center;
  background: var(--surface-ground);
}

.selection-head {
  z-index: 5;
}
.selection-cell input {
  margin: 0;
}

.selection-head + .row-head,
.selection-cell + .row-head {
  left: 2.4rem;
}

thead .row-head {
  z-index: 4;
}
</style>
