<template>
  <p v-for="note in metricNotes" :key="note" role="note">{{ note }}</p>
  <p v-if="scientific && hasMetrics" role="note">{{ scientificProtocolLabel(displayContext) }}</p>
  <div v-if="tableRows.length" class="saved-table">
    <table>
      <thead><tr><th v-for="column in tableColumns" :key="column">{{ columnLabel(column) }}</th></tr></thead>
      <tbody><tr v-for="(row, index) in tableRows.slice(0, displayPreferences.maxRows)" :key="index">
        <td v-for="column in tableColumns" :key="column" :class="{ num: scientific && typeof row[column] === 'number' }">
          <details v-if="row[column] !== null && typeof row[column] === 'object'"><summary>Details</summary><pre>{{ JSON.stringify(row[column], null, 2) }}</pre></details>
          <span v-else :title="scientific ? fullPrecisionTitle(row[column]) : undefined">{{ tableValue(column, row[column], row, index) }}</span>
        </td>
      </tr></tbody>
    </table>
    <p v-if="tableRows.length > displayPreferences.maxRows">Showing {{ displayPreferences.maxRows }} of {{ tableRows.length }} retained rows.</p>
  </div>
  <dl v-if="scientificEntries.length" class="saved-value">
    <template v-for="[key, item] in scientificEntries" :key="key">
      <dt :title="scientific ? key : undefined">{{ entryLabel(key) }}</dt>
      <dd>
        <details v-if="item !== null && typeof item === 'object'" @toggle="expanded[key] = ($event.target as HTMLDetailsElement).open">
          <summary>{{ Array.isArray(item) ? `${item.length} items` : 'Details' }}</summary>
          <div v-if="scientific && expanded[key] && /_per_(target|response)$/.test(key) && Array.isArray(item)">
            <p v-for="(number, index) in item" :key="index">{{ scientificErrorMetricLabel(key, scientificTargetMetricContext(displayContext, index), `${scientificFieldLabel(scientificMetricKey(key))} [${index + 1}]`) }}: {{ scientificScalar(number) }}</p>
          </div>
          <SavedValue v-else-if="scientific && expanded[key] && metricContainers.includes(key)" :value="item" scientific :metric-context="displayContext" />
          <pre v-else-if="expanded[key]">{{ JSON.stringify(item, null, 2) }}</pre>
        </details>
        <span v-else :title="scientific ? fullPrecisionTitle(item) : undefined">{{ displayValue(item) }}</span>
      </dd>
    </template>
  </dl>
  <p v-else-if="!tableRows.length && !auditEntries.length">{{ value == null ? 'Not recorded' : typeof value === 'object' ? 'No fields recorded.' : String(value) }}</p>
  <details v-if="auditEntries.length" class="saved-audit">
    <summary>Audit details ({{ auditEntries.length }})</summary>
    <dl class="saved-value">
      <template v-for="[key, item] in auditEntries" :key="key">
        <dt>{{ key.replace(/_/g, ' ') }}</dt>
        <dd>
          <pre v-if="item !== null && typeof item === 'object'">{{ JSON.stringify(item, null, 2) }}</pre>
          <span v-else>{{ item == null ? 'Not recorded' : String(item) }}</span>
        </dd>
      </template>
    </dl>
  </details>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { displayNumber, useDisplayPreferences } from '@/composables/useDisplayPreferences';
import { columnDecimals, formatMeasurement, fullPrecisionTitle, isAuditField, scientificFieldLabel, scientificScalar, scientificMetricNotes, scientificErrorMetricLabel, scientificProtocolLabel, scientificMetricContext, scientificTargetMetricContext, scientificMetricKey } from '@/utils/scientificDisplay';

// `scientific` renders saved results for reading: field names become
// chemometric labels, numbers are rounded for display (full precision in the
// tooltip) and provenance bookkeeping folds into "Audit details". Without it,
// values are shown exactly as recorded (authored parameters, environment).
const props = defineProps<{ value: unknown; scientific?: boolean; metricContext?: unknown }>();
const displayPreferences = useDisplayPreferences();
const displayContext = computed(() => scientificMetricContext(props.value, props.metricContext));
const metricContainers = ['metrics', 'quality_summary', 'diagnostics', 'metadata', 'splits', 'per_target', 'per_response', 'statistics', 'targets'];
const metricNotes = computed(() => props.scientific ? scientificMetricNotes(props.value) : []);
const expanded = ref<Record<string, boolean>>({});
const tableRows = computed<Record<string, unknown>[]>(() => {
  const value = props.value as { data?: unknown } | null;
  const rows = Array.isArray(value) ? value : value?.data;
  return Array.isArray(rows) && rows.length && rows.every(row => row !== null && typeof row === 'object' && !Array.isArray(row)) ? rows : [];
});
const tableColumns = computed(() => [...new Set(tableRows.value.flatMap(row => Object.keys(row)))]);
const tableDecimals = computed(() => new Map(tableColumns.value.map(column => [
  column, columnDecimals(tableRows.value.map(row => row[column]), 5),
])));
const columnLabel = (column: string) => props.scientific ? scientificFieldLabel(column) : column.replace(/_/g, ' ');
const tableValue = (column: string, value: unknown, row: Record<string, unknown>, index: number) => {
  if (value == null) return 'Not recorded';
  const text = props.scientific && typeof value === 'number'
    ? displayPreferences.precision === 'full'
      ? formatMeasurement(value, Number.isInteger(value) ? 0 : tableDecimals.value.get(column) ?? 0)
      : displayNumber(value)
    : String(value);
  const context = scientificMetricContext(row, scientificTargetMetricContext(displayContext.value, index, row.target ?? row.target_name));
  const units = props.scientific ? scientificErrorMetricLabel(column, context, '') : '';
  return units ? `${text}${units} · ${scientificProtocolLabel(context)}` : text;
};
const displayValue = (value: unknown) => props.scientific ? scientificScalar(value) : value == null ? 'Not recorded' : String(value);
const entryLabel = (key: string) => props.scientific ? scientificErrorMetricLabel(key, displayContext.value) : key.replace(/_/g, ' ');
const hasMetrics = computed(() => [...entries.value.map(([key]) => key), ...tableColumns.value]
  .some(key => /^(rmse.*|mae|bias|sep|r2.*|q2|accuracy.*|balanced_accuracy|f1.*)$/.test(key)));
const entries = computed(() => props.value !== null && typeof props.value === 'object'
  ? Object.entries(props.value).filter(([key]) => !tableRows.value.length || (!Array.isArray(props.value) && key !== 'data')) : []);
const scientificEntries = computed(() => props.scientific && !Array.isArray(props.value)
  ? entries.value.filter(([key]) => !isAuditField(key)) : entries.value);
const auditEntries = computed(() => props.scientific && !Array.isArray(props.value)
  ? entries.value.filter(([key]) => isAuditField(key)) : []);
watch(() => props.value, () => { expanded.value = {}; });
</script>

<style scoped>
.saved-table { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: .5rem; text-align: left; border-bottom: 1px solid var(--surface-border); white-space: nowrap; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.saved-value { display: grid; grid-template-columns: minmax(8rem, 1fr) minmax(0, 2fr); gap: .65rem; }
dt, dd { margin: 0; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 24rem; overflow: auto; }
.saved-audit { margin-top: 1rem; border-top: 1px solid var(--surface-border); padding-top: .5rem; color: var(--text-color-secondary); font-size: .85rem; }
.saved-audit summary { cursor: pointer; }
.saved-audit .saved-value { margin-top: .5rem; }
</style>
