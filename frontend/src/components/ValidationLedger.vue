<template>
  <section class="validation-ledger" aria-label="Validation ledger">
    <header class="validation-ledger__header">
      <div>
        <h3>Validation ledger</h3>
        <small>{{ rows.length }} sample-level prediction{{ rows.length === 1 ? "" : "s" }}</small>
      </div>
      <Button label="Download CSV" icon="pi pi-download" class="p-button-sm p-button-text" @click="download" />
    </header>
    <div class="validation-ledger__table-wrap">
      <table>
        <thead>
          <tr>
            <th>Sample</th><th v-if="hasTarget">Target</th><th>True / reference</th><th>Predicted</th>
            <th v-if="hasResidual">Residual</th><th v-if="hasCorrect">Correct</th><th v-if="hasRole">Role</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in visibleRows" :key="row.sample + '-' + (row.target || '')">
            <td>{{ row.sample }}</td><td v-if="hasTarget">{{ row.target }}</td>
            <td>{{ row.reference }}</td><td>{{ row.predicted }}</td><td v-if="hasResidual">{{ row.residual }}</td>
            <td v-if="hasCorrect">{{ row.correct == null ? "Not evaluated" : row.correct ? "Yes" : "No" }}</td><td v-if="hasRole">{{ row.role }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <small v-if="rows.length > visibleRows.length" class="validation-ledger__note">
      Showing the first {{ visibleRows.length }} rows. Download the CSV for the complete ledger.
    </small>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import Button from "primevue/button";
import { downloadText } from "@/utils/download";
import { validationLedgerCsv, type ValidationLedgerRow } from "@/utils/validationLedger";

const props = defineProps<{ rows: ValidationLedgerRow[]; title?: string }>();
const visibleRows = computed(() => props.rows.slice(0, 200));
const hasTarget = computed(() => props.rows.some((row) => row.target != null));
const hasResidual = computed(() => props.rows.some((row) => row.residual != null));
const hasCorrect = computed(() => props.rows.some((row) => row.correct != null));
const hasRole = computed(() => props.rows.some((row) => row.role != null));
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
.validation-ledger__note { display: block; margin-top: 0.5rem; color: var(--text-color-secondary); }
</style>
