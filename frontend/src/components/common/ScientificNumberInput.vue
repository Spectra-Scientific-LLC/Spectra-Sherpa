<template>
  <span class="scientific-number-input">
    <input
      v-bind="$attrs"
      :id="id"
      type="text"
      inputmode="decimal"
      class="p-inputtext p-component"
      :class="{ 'p-invalid': error }"
      :value="draft"
      :aria-invalid="error ? 'true' : undefined"
      :required="required"
      :aria-describedby="id && (error || rangeHint) ? `${id}-numeric-help` : undefined"
      @input="onInput"
    />
    <small
      v-if="error || rangeHint"
      :id="id ? `${id}-numeric-help` : undefined"
      :class="{ 'numeric-error': error }"
      aria-live="polite"
    >
      {{ error || rangeHint }}
    </small>
  </span>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  numericRangeError,
  parseScientificNumber,
  type ScientificNumberValue,
} from "@/utils/scientificNumberInput";

defineOptions({ inheritAttrs: false });
const props = defineProps<{
  modelValue?: ScientificNumberValue;
  id?: string;
  min?: number | null;
  max?: number | null;
  // A step is not a precision declaration. Retained for callers using node metadata.
  step?: number | null;
  required?: boolean;
  integer?: boolean;
}>();
const emit = defineEmits<{
  (e: "update:modelValue", value: ScientificNumberValue): void;
}>();
const draft = ref(String(props.modelValue ?? ""));
const parsed = computed(() => parseScientificNumber(draft.value));
const error = computed(
  () =>
    parsed.value.error ||
    (props.integer &&
    typeof parsed.value.value === "number" &&
    !Number.isInteger(parsed.value.value)
      ? "Enter a whole number. The entered value has not been changed."
      : null) ||
    (props.required && parsed.value.value === null ? "A value is required." : null) ||
    numericRangeError(parsed.value.value, props.min, props.max),
);
const rangeHint = computed(() => {
  if (props.min != null && props.max != null) return `Allowed range: ${props.min} to ${props.max}.`;
  if (props.min != null) return `Minimum: ${props.min}.`;
  if (props.max != null) return `Maximum: ${props.max}.`;
  return "";
});
watch(
  () => props.modelValue,
  (value) => {
    // A parent echo must not erase a decimal point, trailing zero, or exponent.
    if (!Object.is(value ?? null, parsed.value.value)) draft.value = String(value ?? "");
  },
);
function onInput(event: Event) {
  draft.value = (event.target as HTMLInputElement).value;
  // Invalid drafts remain invalid strings in the graph. Existing node validation
  // refuses execution; retaining the previous numeric value would run stale input.
  emit("update:modelValue", parsed.value.value);
}
</script>

<style scoped>
.scientific-number-input {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  width: 100%;
}
input {
  width: 100%;
  min-width: 0;
}
small {
  color: var(--text-color-secondary);
}
.numeric-error {
  color: var(--red-400, #f87171);
}
</style>
