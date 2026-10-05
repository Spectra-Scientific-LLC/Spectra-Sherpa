<template>
  <section class="peak-execution-details" aria-label="Executed peak-finding inputs">
    <h4>Executed peak-finding inputs</h4>
    <template v-if="call">
      <p>From this result's execution. Editing settings does not change this execution record.</p>
      <p>SciPy version: {{ record.scipy_version ?? "not retained" }}</p>
      <pre>{{ call }}</pre>
      <p v-if="typeof record.scipy_find_peaks_call_count === 'number'">
        Peak detection calls: {{ record.scipy_find_peaks_call_count }} (one per input spectrum).
      </p>
      <p v-if="typeof record.scipy_peak_widths_call_count === 'number'">
        Width measurement calls: {{ record.scipy_peak_widths_call_count }} (only spectra with
        detected peaks).
      </p>
      <pre v-if="typeof record.scipy_peak_widths_call === 'string'">{{
        record.scipy_peak_widths_call
      }}</pre>
      <p v-if="typeof record.consensus_binning === 'string'">{{ record.consensus_binning }}</p>
      <p v-if="typeof record.parameter_interpretation === 'string'">
        {{ record.parameter_interpretation }}
      </p>
    </template>
    <p v-else>
      Exact SciPy arguments were not retained with this result. Run the updated node to capture
      them; current settings cannot establish historical inputs.
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ diagnostics?: unknown }>();
const record = computed<Record<string, unknown>>(() =>
  props.diagnostics && typeof props.diagnostics === "object" && !Array.isArray(props.diagnostics)
    ? (props.diagnostics as Record<string, unknown>)
    : {},
);
const call = computed(() =>
  typeof record.value.scipy_find_peaks_call === "string"
    ? record.value.scipy_find_peaks_call
    : null,
);
</script>

<style scoped>
.peak-execution-details {
  padding: 0.75rem;
  border: 1px solid var(--surface-border, #475569);
  border-radius: 6px;
  margin: 0.75rem 0;
}
h4 {
  margin: 0 0 0.5rem;
}
p {
  font-size: 0.8rem;
  margin: 0.5rem 0;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 0.8rem;
  user-select: text;
}
</style>
