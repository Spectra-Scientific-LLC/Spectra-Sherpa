<template>
  <fieldset class="qualification-policy-form">
    <legend>Prepare a validation policy</legend>
    <p>Enter your laboratory's acceptance criteria before inspecting validation results. Sherpa supplies no universal pass limits. This form prepares the policy; it does not execute, accept or certify a model.</p>
    <label>Policy name<input v-model="policyName" data-field="policy-name" maxlength="200" /></label>
    <label>Policy version<input v-model="policyVersion" data-field="policy-version" maxlength="100" /></label>
    <label>Intended use<textarea v-model="intendedUse" data-field="intended-use" maxlength="2000" /></label>
    <label>Intended population<textarea v-model="population" data-field="population" maxlength="2000" /></label>
    <label>Specimen register / namespace<input v-model="namespace" data-field="namespace" maxlength="200" /></label>
    <label>Sampling design<textarea v-model="samplingDesign" data-field="sampling-design" maxlength="2000" /></label>
    <label>Reference laboratory method<input v-model="method" data-field="method" maxlength="200" /></label>
    <label>Method version<input v-model="methodVersion" data-field="method-version" maxlength="100" /></label>
    <label>Reference measurement basis<select v-model="measurementBasis" data-field="measurement-basis"><option value="">Choose measurement basis</option><option value="single_measurement">One measurement per label</option><option value="replicate_mean">Mean of replicate measurements</option></select></label>
    <label v-if="measurementBasis === 'replicate_mean'">Measurements per reference label<input v-model.number="measurementsPerLabel" data-field="measurements-per-label" type="number" min="2" max="10000" step="1" /></label>
    <label>Instrument (optional)<input v-model="instrument" maxlength="200" /></label>
    <label>Minimum independent specimens<input v-model.number="minimumSpecimens" data-field="minimum-specimens" type="number" min="2" step="1" /></label>
    <label>Minimum specimens per fitted component<input v-model.number="perComponent" data-field="per-component" type="number" min="0" step="any" /></label>
    <label>Minimum fraction with available applicability screening (0–1)<input v-model.number="screeningFraction" data-field="screening" type="number" min="0" max="1" step="any" /></label>
    <p>RMSEP and bias limits use each response's stated units. The intended range describes the population to validate.</p>
    <fieldset v-for="(response, index) in responses" :key="index">
      <legend>Response {{ index + 1 }}</legend>
      <template v-if="responseIdentity"><p>{{ response.name || 'Unnamed response' }} · {{ response.unit || 'units not recorded' }} (saved model authority)</p></template>
      <template v-else>
        <label>Response name<input v-model="response.name" :data-field="`name-${index}`" /></label>
        <label>Response units<input v-model="response.unit" :data-field="`unit-${index}`" /></label>
      </template>
      <label>Maximum RMSEP<input v-model.number="response.rmsep" :data-field="`rmsep-${index}`" type="number" min="0" step="any" /></label>
      <label>Maximum absolute bias<input v-model.number="response.bias" :data-field="`bias-${index}`" type="number" min="0" step="any" /></label>
      <label>Intended minimum<input v-model.number="response.minimum" :data-field="`minimum-${index}`" type="number" step="any" /></label>
      <label>Intended maximum<input v-model.number="response.maximum" :data-field="`maximum-${index}`" type="number" step="any" /></label>
      <button v-if="!responseIdentity && responses.length > 1" type="button" @click="responses.splice(index, 1)">Remove response</button>
    </fieldset>
    <button v-if="!responseIdentity" type="button" :disabled="responses.length >= 256" @click="responses.push(emptyResponse())">Add response</button>
    <p v-if="!responseIdentity">Enter the frozen application's exact response names and units. The server checks them against the fitted model before assessment.</p>
    <fieldset><legend>Chronology and independence declarations</legend>
      <p>Leave a statement unchecked unless you can support it. Missing declarations remain visible and may prevent qualification; checking them does not prove independence.</p>
      <label><input v-model="policyFrozen" type="checkbox" /> The policy was frozen before examining validation results.</label>
      <label><input v-model="modelFrozen" type="checkbox" /> The model was frozen before validation.</label>
      <label><input v-model="unusedSpecimens" type="checkbox" /> These specimens were not used for fitting, selection or interval calibration.</label>
      <label><input v-model="independentSampling" type="checkbox" /> Independent specimen sampling is supported by the declared sampling design.</label>
    </fieldset>
    <p>Initial calculation settings: 95% bias confidence, 200 bootstrap resamples, seed 0. Reference precision and intervals remain unassessed. Use Advanced for another measurement basis or additional criteria.</p>
    <button type="button" :disabled="!complete" @click="prepare">Use this policy and context</button>
    <p v-if="prepared" role="status">Policy and context prepared below. Review them, then explicitly execute the assessment.</p>
  </fieldset>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
type Identity = { names: string[] | null; units: (string | null)[] };
type NumberInput = number | '';
type ResponseDraft = { name: string; unit: string; rmsep: NumberInput; bias: NumberInput; minimum: NumberInput; maximum: NumberInput };
const props = defineProps<{ responseIdentity?: Identity }>();
const emit = defineEmits<{ prepared: [value: { policy: string; context: string }]; changed: [] }>();
const emptyResponse = (): ResponseDraft => ({ name: '', unit: '', rmsep: '', bias: '', minimum: '', maximum: '' });
const responses = ref<ResponseDraft[]>([emptyResponse()]);
const policyName = ref(''), policyVersion = ref('1'), intendedUse = ref(''), population = ref(''), namespace = ref(''), samplingDesign = ref(''), method = ref(''), methodVersion = ref(''), instrument = ref('');
const measurementBasis = ref(''), measurementsPerLabel = ref<NumberInput>('');
const minimumSpecimens = ref<NumberInput>(''), perComponent = ref<NumberInput>(''), screeningFraction = ref<NumberInput>('');
const policyFrozen = ref(false), modelFrozen = ref(false), unusedSpecimens = ref(false), independentSampling = ref(false), prepared = ref(false);
const finite = (value: NumberInput): value is number => typeof value === 'number' && Number.isFinite(value);
const complete = computed(() => [policyName, policyVersion, intendedUse, population, namespace, samplingDesign, method, methodVersion].every(value => value.value.trim()) &&
  (measurementBasis.value === 'single_measurement' || (measurementBasis.value === 'replicate_mean' && finite(measurementsPerLabel.value) && Number.isInteger(measurementsPerLabel.value) && measurementsPerLabel.value >= 2 && measurementsPerLabel.value <= 10000)) &&
  finite(minimumSpecimens.value) && Number.isInteger(minimumSpecimens.value) && minimumSpecimens.value >= 2 && finite(perComponent.value) && perComponent.value > 0 &&
  finite(screeningFraction.value) && screeningFraction.value >= 0 && screeningFraction.value <= 1 && responses.value.length > 0 &&
  responses.value.every(r => (props.responseIdentity || (r.name.trim() && r.unit.trim())) && finite(r.rmsep) && r.rmsep > 0 && finite(r.bias) && r.bias > 0 && finite(r.minimum) && finite(r.maximum) && r.minimum < r.maximum));
watch(() => props.responseIdentity, identity => {
  responses.value = identity ? identity.units.map((unit, i) => ({ ...emptyResponse(), name: identity.names?.[i] || '', unit: unit || '' })) : [emptyResponse()];
  prepared.value = false;
}, { immediate: true, deep: true });
watch([policyName, policyVersion, intendedUse, population, namespace, samplingDesign, method, methodVersion,
  instrument, measurementBasis, measurementsPerLabel, minimumSpecimens, perComponent, screeningFraction, responses, policyFrozen, modelFrozen, unusedSpecimens, independentSampling],
  () => { prepared.value = false; emit('changed'); }, { deep: true });
function prepare() {
  if (!complete.value) return;
  const identity = props.responseIdentity || { names: responses.value.map(r => r.name.trim()), units: responses.value.map(r => r.unit.trim()) };
  const policy = { schema_version: 'spectrasherpa.declared-qualification-policy/1', policy_name: policyName.value.trim(), policy_version: policyVersion.value.trim(),
    minimum_independent_specimens: minimumSpecimens.value, minimum_specimens_per_component: perComponent.value, response_identity: identity,
    responses: responses.value.map(r => ({ max_rmsep: r.rmsep, max_absolute_bias: r.bias, intended_minimum: r.minimum, intended_maximum: r.maximum })),
    require_reference_precision: false, minimum_screening_available_fraction: screeningFraction.value,
    minimum_interval_available_fraction: null, minimum_observed_interval_coverage: null, bias_confidence_level: 0.95, bootstrap_resamples: 200, random_seed: 0 };
  const context = { intended_use: intendedUse.value.trim(), intended_population: population.value.trim(), specimen_namespace: namespace.value.trim(),
    reference_method: { method_id: method.value.trim(), version: methodVersion.value.trim(), response_identity: identity, measurement_basis: measurementBasis.value, measurements_per_label: measurementBasis.value === 'single_measurement' ? 1 : measurementsPerLabel.value, precision: null },
    instrument_id: instrument.value.trim() || null, acquisition_configuration_digest: null, domain_coverage_evidence_digest: null,
    policy_frozen_before_validation: policyFrozen.value, model_frozen_before_validation: modelFrozen.value,
    specimens_not_used_for_fit_selection_or_interval_calibration: unusedSpecimens.value, independent_specimen_sampling_declared: independentSampling.value,
    sampling_design: samplingDesign.value.trim(), evaluation_role: 'external_validation' };
  emit('prepared', { policy: JSON.stringify(policy, null, 2), context: JSON.stringify(context, null, 2) }); prepared.value = true;
}
</script>
<style scoped>
.qualification-policy-form { display: grid; gap: .6rem; margin: .8rem 0; }
label { display: grid; gap: .25rem; margin: .5rem 0; }
input:not([type=checkbox]), textarea { width: 100%; }
fieldset { min-width: 0; }
</style>
