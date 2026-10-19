<template>
  <section class="validation-ledger" aria-label="Validation ledger">
    <header class="validation-ledger__header">
      <div>
        <h3>Sample predictions</h3>
        <small>{{ roleSummary }}</small>
      </div>
      <Button label="Download CSV" icon="pi pi-download" class="p-button-sm p-button-text" @click="download" />
    </header>
    <p v-if="calibrationOnly" class="validation-ledger__note validation-ledger__note--caution" role="note">
      Calibration fitted values.
    </p>
    <div class="validation-ledger__table-wrap">
      <table>
        <thead>
          <tr>
            <th>Sample</th><th v-if="hasTarget">Target</th><th class="num">Reference</th><th class="num">Predicted</th>
            <th v-if="hasResidual" class="num">Residual</th><th v-if="hasCorrect">Correct</th><th v-if="hasRole">Set</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in visibleRows" :key="row.sample + '-' + (row.target || '')">
            <td>{{ row.sample }}</td><td v-if="hasTarget">{{ row.target }}</td>
            <td class="num" :title="fullPrecisionTitle(row.reference)">{{ cell(row, row.reference) }}</td>
            <td class="num" :title="fullPrecisionTitle(row.predicted)">{{ cell(row, row.predicted) }}</td>
            <td v-if="hasResidual" class="num" :title="fullPrecisionTitle(row.residual)">{{ cell(row, row.residual) }}</td>
            <td v-if="hasCorrect">{{ row.correct == null ? "Not evaluated" : row.correct ? "Yes" : "No" }}</td>
            <td v-if="hasRole" :title="row.role">{{ row.role ? evaluationRoleLabel(row.role) : "" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <small v-if="rows.length > visibleRows.length" class="validation-ledger__note">
      Showing the first {{ visibleRows.length }} rows. Download the CSV for the complete ledger at full precision.
    </small>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import Button from "primevue/button";
import { downloadText } from "@/utils/download";
import { validationLedgerCsv, type ValidationLedgerRow } from "@/utils/validationLedger";
import { columnDecimals, evaluationRoleLabel, formatMeasurement, fullPrecisionTitle } from "@/utils/scientificDisplay";

const props = defineProps<{ rows: ValidationLedgerRow[]; title?: string }>();
const visibleRows = computed(() => props.rows.slice(0, 200));
const hasTarget = computed(() => props.rows.some((row) => row.target != null));
const hasResidual = computed(() => props.rows.some((row) => row.residual != null));
const hasCorrect = computed(() => props.rows.some((row) => row.correct != null));
const hasRole = computed(() => props.rows.some((row) => row.role != null));
const calibrationOnly = computed(() => props.rows.length > 0 && props.rows.every((row) => row.role === "calibration"));

// One precision per target: reference, prediction and residual share the
// response's scale, so they read in the same units and decimals.
const decimalsByTarget = computed(() => {
  const groups = new Map<string, unknown[]>();
  for (const row of props.rows) {
    const key = row.target ?? "";
    groups.set(key, [...(groups.get(key) ?? []), row.reference, row.predicted]);
  }
  return new Map([...groups].map(([key, values]) => [key, columnDecimals(values)]));
});
const cell = (row: ValidationLedgerRow, value: unknown): string =>
  formatMeasurement(value, decimalsByTarget.value.get(row.target ?? "") ?? 0);

const roleSummary = computed(() => {
  const counts = new Map<string, number>();
  for (const row of props.rows) {
    const label = row.role ? evaluationRoleLabel(row.role) : "Unlabelled";
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  const total = `${props.rows.length} sample-level prediction${props.rows.length === 1 ? "" : "s"}`;
  return counts.size && hasRole.value
    ? `${total} · ${[...counts].map(([label, count]) => `${count} ${label.toLowerCase()}`).join(", ")}`
    : total;
});

function download(): void {
  downloadText(validationLedgerCsv(props.rows), `${props.title ?? "validation-ledger"}.csv`, "text/csv;charset=utf-8");
}
</script>

<style scoped>
.validation-ledger { margin: 1rem 0; border: 1px solid var(--surface-border); border-radius: 8px; padding: 0.75rem; }
.validation-ledger__header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.validation-ledger h3 { margin: 0; }
.validation-ledger__table-wrap { max-height: 22rem; overflow: auto; margin-top: 0.5rem; }
.validation-ledger table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.validation-ledger th, .validation-ledger td { padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--surface-border); text-align: left; white-space: nowrap; }
.validation-ledger .num { text-align: right; font-variant-numeric: tabular-nums; }
.validation-ledger__note { display: block; margin-top: 0.5rem; color: var(--text-color-secondary); }
.validation-ledger__note--caution { margin: 0.5rem 0 0; padding: 0.5rem 0.75rem; border-left: 3px solid var(--orange-400); background: var(--surface-ground); color: var(--text-color); font-size: 0.85rem; }
</style>
