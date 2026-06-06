<template>
  <div class="stats-wrap">
    <div class="stats-summary">
      <span>{{ matrix.stats.summary.n_samples.toLocaleString() }} samples</span>
      <span>{{ matrix.stats.summary.n_features.toLocaleString() }} features</span>
      <span>{{ matrix.stats.summary.total_missing_pct.toFixed(2) }}% missing</span>
      <span v-if="matrix.target">
        {{ matrix.target.target_name || "Target" }}:
        {{ targetDescriptor }}
      </span>
    </div>
    <DataTable
      v-if="matrix.target?.classes?.length"
      :value="matrix.target.classes"
      size="small"
      stripedRows
      class="target-table"
    >
      <Column field="value" header="Label" />
      <Column field="label" header="Class" />
      <Column field="count" header="Count" />
      <Column header="%">
        <template #body="{ data }">{{ Number(data.pct).toFixed(1) }}%</template>
      </Column>
    </DataTable>
    <DataTable
      :value="matrix.stats.per_column"
      size="small"
      scrollable
      scrollHeight="420px"
      stripedRows
      class="stats-table"
    >
      <Column field="label" header="Feature" />
      <Column field="count" header="Count" />
      <Column header="Missing">
        <template #body="{ data }">
          {{ data.missing }} ({{ Number(data.missing_pct).toFixed(1) }}%)
        </template>
      </Column>
      <Column header="Min">
        <template #body="{ data }">{{ formatStat(data.min) }}</template>
      </Column>
      <Column header="Max">
        <template #body="{ data }">{{ formatStat(data.max) }}</template>
      </Column>
      <Column header="Mean">
        <template #body="{ data }">{{ formatStat(data.mean) }}</template>
      </Column>
      <Column header="Std">
        <template #body="{ data }">{{ formatStat(data.std) }}</template>
      </Column>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import type { DataMatrixResponse } from "@/stores/data";

const props = defineProps<{ matrix: DataMatrixResponse }>();

const targetDescriptor = computed(() => {
  const target = props.matrix.target;
  if (!target) return "";
  if (target.n_classes) {
    return `${target.n_classes} classes, ${target.count.toLocaleString()} labeled samples`;
  }
  if (typeof target.mean === "number") {
    return `mean ${formatStat(target.mean)}, ${target.count.toLocaleString()} values`;
  }
  return `${target.count.toLocaleString()} values`;
});

function formatStat(value: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toPrecision(5) : "";
}
</script>

<style scoped>
.stats-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
  margin-bottom: 0.65rem;
}

.target-table {
  margin-bottom: 0.85rem;
}

.stats-table :deep(.p-datatable-thead > tr > th),
.stats-table :deep(.p-datatable-tbody > tr > td),
.target-table :deep(.p-datatable-thead > tr > th),
.target-table :deep(.p-datatable-tbody > tr > td) {
  white-space: nowrap;
}
</style>
