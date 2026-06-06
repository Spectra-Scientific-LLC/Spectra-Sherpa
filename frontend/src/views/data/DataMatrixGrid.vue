<template>
  <div class="matrix-wrap">
    <div class="matrix-meta">
      <span>{{ matrix.rows_shown.toLocaleString() }} x {{ matrix.cols_shown.toLocaleString() }} shown</span>
      <span v-if="matrix.truncated">
        of {{ matrix.total_rows.toLocaleString() }} x {{ matrix.total_cols.toLocaleString() }}
      </span>
    </div>
    <div ref="scrollEl" class="matrix-scroll" @scroll="onScroll">
      <table class="matrix-table">
        <thead>
          <tr>
            <th class="row-head">{{ matrix.y_title || "Sample" }}</th>
            <th v-for="label in matrix.col_labels" :key="label" :title="xTitle">
              {{ label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="topSpacerHeight > 0" aria-hidden="true">
            <td :style="{ height: `${topSpacerHeight}px` }"></td>
            <td :colspan="matrix.col_labels.length"></td>
          </tr>
          <tr v-for="row in visibleRows" :key="row.index">
            <th class="row-head" :title="row.label">{{ row.label }}</th>
            <td v-for="(value, colIndex) in row.values" :key="colIndex">
              {{ formatValue(value) }}
            </td>
          </tr>
          <tr v-if="bottomSpacerHeight > 0" aria-hidden="true">
            <td :style="{ height: `${bottomSpacerHeight}px` }"></td>
            <td :colspan="matrix.col_labels.length"></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import type { DataMatrixResponse } from "@/stores/data";

const props = defineProps<{ matrix: DataMatrixResponse }>();

const rowHeight = 18;
const viewportRows = 120;
const scrollTop = ref(0);
const scrollEl = ref<HTMLElement | null>(null);

const startRow = computed(() => Math.max(0, Math.floor(scrollTop.value / rowHeight) - 4));
const endRow = computed(() => Math.min(props.matrix.matrix.length, startRow.value + viewportRows));
const visibleRows = computed(() =>
  props.matrix.matrix.slice(startRow.value, endRow.value).map((values, offset) => {
    const index = startRow.value + offset;
    return {
      index,
      label: props.matrix.row_labels[index] ?? String(index + 1),
      values,
    };
  })
);
const topSpacerHeight = computed(() => startRow.value * rowHeight);
const bottomSpacerHeight = computed(() => Math.max(0, props.matrix.matrix.length - endRow.value) * rowHeight);
const xTitle = computed(() => {
  if (props.matrix.x_title && props.matrix.x_units) return `${props.matrix.x_title} (${props.matrix.x_units})`;
  return props.matrix.x_title || "Feature";
});

function onScroll() {
  scrollTop.value = scrollEl.value?.scrollTop ?? 0;
}

function formatValue(value: number | string | null): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return Number.isFinite(value) ? value.toPrecision(5) : "";
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

thead .row-head {
  z-index: 4;
}
</style>
