<template>
  <div v-if="colorOptions.length" class="control-group">
    <label>Color by metadata</label>
    <Dropdown
      :model-value="colorValue"
      :options="colorOptions"
      optionLabel="label"
      optionValue="value"
      @update:model-value="$emit('update:colorValue', $event)"
    />
  </div>
  <div v-if="styleOptions.length" class="control-group">
    <label>{{ styleLabel }} by metadata</label>
    <Dropdown
      :model-value="styleValue"
      :options="styleOptions"
      optionLabel="label"
      optionValue="value"
      @update:model-value="$emit('update:styleValue', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import Dropdown from "primevue/dropdown";

type Option = { label: string; value: string };

withDefaults(
  defineProps<{
    colorValue: string;
    styleValue: string;
    colorOptions: Option[];
    styleOptions: Option[];
    styleLabel?: string;
  }>(),
  {
    styleLabel: "Symbol",
  },
);

defineEmits<{
  (event: "update:colorValue", value: string): void;
  (event: "update:styleValue", value: string): void;
}>();
</script>
