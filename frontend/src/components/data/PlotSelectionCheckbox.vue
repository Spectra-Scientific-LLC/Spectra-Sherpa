<template>
  <label
    class="plot-selection-checkbox"
    :class="{ partial, disabled }"
    :title="title || label"
    @click.stop
  >
    <input
      type="checkbox"
      :checked="checked"
      :indeterminate="partial"
      :disabled="disabled"
      :aria-label="label"
      :aria-checked="partial ? 'mixed' : checked"
      @change="onChange"
    />
    <span aria-hidden="true">
      <i v-if="partial" class="pi pi-minus" />
      <i v-else-if="checked" class="pi pi-check" />
    </span>
  </label>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    checked: boolean;
    partial?: boolean;
    disabled?: boolean;
    label: string;
    title?: string;
  }>(),
  {
    partial: false,
    disabled: false,
    title: "",
  },
);

const emit = defineEmits<{ toggle: [checked: boolean] }>();

function onChange(event: Event): void {
  emit("toggle", (event.target as HTMLInputElement).checked);
}
</script>

<style scoped>
.plot-selection-checkbox {
  align-items: center;
  cursor: pointer;
  display: inline-flex;
  height: 1.25rem;
  justify-content: center;
  position: relative;
  width: 1.25rem;
}

.plot-selection-checkbox input {
  height: 100%;
  inset: 0;
  margin: 0;
  opacity: 0;
  position: absolute;
  width: 100%;
}

.plot-selection-checkbox span {
  align-items: center;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 4px;
  color: white;
  display: flex;
  height: 1.1rem;
  justify-content: center;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
  width: 1.1rem;
}

.plot-selection-checkbox:has(input:focus-visible) span {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color) 25%, transparent);
}

.plot-selection-checkbox:has(input:checked) span,
.plot-selection-checkbox.partial span {
  background: var(--primary-color);
  border-color: var(--primary-color);
}

.plot-selection-checkbox i {
  font-size: 0.68rem;
  font-weight: 700;
}

.plot-selection-checkbox.disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
</style>
