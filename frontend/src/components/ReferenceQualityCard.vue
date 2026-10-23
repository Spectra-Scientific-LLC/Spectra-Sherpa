<script setup lang="ts">
import { computed } from "vue";
import MethodHelp from "@/components/MethodHelp.vue";
import type { ReferenceValueEvidence } from "@/types";

const props = defineProps<{
  evidence: ReferenceValueEvidence | null;
  calibrationRows?: number | null;
  unavailableReason?: string | null;
  title?: string;
}>();

const precision = computed(() => {
  const value = props.evidence?.method?.precision;
  if (!value || !Array.isArray(value.sd) || value.sd.length !== 1) return null;
  const sd = value.sd[0];
  const specimens = value.specimens;
  const replicates = value.replicates_per_specimen;
  const degrees = value.degrees_of_freedom;
  if (typeof sd !== "number" || !Number.isFinite(sd) || sd < 0 ||
    typeof specimens !== "number" || !Number.isSafeInteger(specimens) || specimens < 1 ||
    typeof replicates !== "number" || !Number.isSafeInteger(replicates) || replicates < 2 ||
    typeof degrees !== "number" || !Number.isSafeInteger(degrees) || degrees < 1) return null;
  return { sd, specimens, replicates, degrees };
});
</script>

<template>
  <section class="reference-quality" :aria-label="title || 'Reference-value quality'">
    <h4>{{ title || "Reference-value quality" }} <MethodHelp topic="referenceValues" label="Reference quality" context="Model residuals do not establish laboratory precision. Prediction intervals require separate calibration and coverage evidence." /></h4>
    <p v-if="unavailableReason" role="note">{{ unavailableReason }}</p>
    <p v-else-if="!evidence" role="note">
      Laboratory reference declaration not recorded.
    </p>
    <template v-else>
      <dl>
        <div><dt>Response</dt><dd>{{ evidence.target_name }} ({{ evidence.units || (evidence.target_type === "categorical" ? "class labels" : "units not recorded") }})</dd></div>
        <div><dt>Laboratory method</dt><dd>{{ evidence.method ? `${evidence.method.method_id} v${evidence.method.version}` : "Not recorded" }}</dd></div>
        <div><dt>Value basis</dt><dd>{{ evidence.method?.measurement_basis === "replicate_mean" ? `Mean of ${evidence.method.measurements_per_label} measurements; mapping unverified` : evidence.method ? "Single measurement" : "Not recorded" }}</dd></div>
        <div><dt>Source included rows</dt><dd>{{ evidence.source_included_count }} before calibration/test split</dd></div>
        <div><dt>Calibration rows</dt><dd>{{ calibrationRows ?? "Not retained" }}</dd></div>
        <div><dt>Missing targets</dt><dd>{{ evidence.missing_included_count }} included; {{ evidence.missing_excluded_count }} excluded</dd></div>
        <div><dt>Reported precision</dt><dd>{{ precision ? `${precision.sd} ${evidence.units || 'response units not recorded'} pooled within-specimen SD (unverified)` : "Not recorded" }}</dd></div>
        <div v-if="precision"><dt>Precision study</dt><dd>{{ precision.specimens }} specimens × {{ precision.replicates }} replicates; {{ precision.degrees }} degrees of freedom. {{ evidence.precision_study_provenance || "Provenance not recorded" }}</dd></div>
        <div v-if="evidence.provenance"><dt>Method provenance</dt><dd>{{ evidence.provenance }}</dd></div>
      </dl>
      <details><summary>Unrecorded supporting evidence</summary>
        <p v-if="!evidence.provenance">Method provenance: not recorded.</p>
        <p>Instrument repeatability: not recorded separately.</p>
      </details>
      <p v-if="evidence.qualification_gaps.length" role="status">
        Qualification gaps: {{ evidence.qualification_gaps.join("; ") }}.
      </p>

    </template>
  </section>
</template>

<style scoped>
.reference-quality { border: 1px solid var(--surface-border); border-radius: 8px; padding: 1rem; margin-block: 1rem; }
.reference-quality h4 { margin: 0 0 .75rem; }
.reference-quality dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: .75rem 1rem; margin: 0; }
.reference-quality dt { font-size: .8rem; opacity: .75; }
.reference-quality dd { margin: .15rem 0 0; overflow-wrap: anywhere; }
.reference-quality p { margin: .75rem 0 0; }
</style>
