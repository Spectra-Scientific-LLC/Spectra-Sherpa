<template>
  <div v-if="visible" class="axis-set-controls" aria-label="Dataset axis display controls">
    <div v-if="scaleOptions.length > 1" class="axis-set-control">
      <label>Coordinate scale</label>
      <Dropdown
        :model-value="scaleValue"
        :options="scaleOptions"
        optionLabel="label"
        optionValue="value"
        @update:model-value="$emit('update:scaleValue', $event)"
      />
    </div>
    <div v-if="labelOptions.length > 1" class="axis-set-control">
      <label>Axis labels</label>
      <Dropdown
        :model-value="labelValue"
        :options="labelOptions"
        optionLabel="label"
        optionValue="value"
        @update:model-value="$emit('update:labelValue', $event)"
      />
    </div>
    <div v-if="titleOptions.length > 1" class="axis-set-control">
      <label>Axis title</label>
      <Dropdown
        :model-value="titleValue"
        :options="titleOptions"
        optionLabel="label"
        optionValue="value"
        @update:model-value="$emit('update:titleValue', $event)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import Dropdown from "primevue/dropdown";

import type { AxisSetOption } from "@/utils/datasetAxisSets";

const props = defineProps<{
  scaleValue: string;
  labelValue: string;
  titleValue: string;
  scaleOptions: AxisSetOption[];
  labelOptions: AxisSetOption[];
  titleOptions: AxisSetOption[];
}>();

const visible = computed(
  () =>
    props.scaleOptions.length > 1 || props.labelOptions.length > 1 || props.titleOptions.length > 1,
);

defineEmits<{
  (event: "update:scaleValue", value: string): void;
  (event: "update:labelValue", value: string): void;
  (event: "update:titleValue", value: string): void;
}>();
</script>

<style scoped>
.axis-set-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: end;
}

.axis-set-control {
  display: flex;
  min-width: 12rem;
  flex-direction: column;
  gap: 0.3rem;
}

.axis-set-control label {
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  font-weight: 600;
}
</style>
