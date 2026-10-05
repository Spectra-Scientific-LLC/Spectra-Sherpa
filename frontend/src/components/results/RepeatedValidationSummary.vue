<template>
  <section v-if="record?.schema_version === 'spectrasherpa.repeated-nested-validation/1'">
    <h4>Repeated validation: partition sensitivity</h4>
    <p>{{ record.n_repeats }} repeats · {{ record.n_rows }} original rows
      <span v-if="record.n_groups != null"> · {{ record.n_groups }} groups</span></p>
    <p>{{ record.interpretation }}</p>
    <table>
      <thead><tr><th>Metric</th><th>Mean</th><th>SD across repeats</th><th>Range</th><th>Each repeat</th></tr></thead>
      <tbody><tr v-for="(value, key) in record.distributions" :key="key">
        <th>{{ key }}</th><td>{{ number(value.mean) }}</td><td>{{ number(value.std_across_repeats) }}</td>
        <td>{{ number(value.minimum) }} – {{ number(value.maximum) }}</td>
        <td>{{ value.per_repeat.map(number).join(', ') }}</td>
      </tr></tbody>
    </table>
    <p>Root seed: {{ record.root_seed }}. Exact repeat seeds and folds are retained in Separate Repeat Evidence.</p>
  </section>
</template>
<script setup lang="ts">
import { scientificNumber } from "@/utils/scientificEncoding";
defineProps<{ record?: Record<string, any> | null }>();
const number = (value: number) => scientificNumber(value, { decimalPlaces: 4 });
</script>
<style scoped>
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.4rem; border-bottom: 1px solid var(--surface-border); }
</style>
