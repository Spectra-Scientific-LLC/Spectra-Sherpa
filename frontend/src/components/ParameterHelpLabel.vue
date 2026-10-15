<template>
  <div
    class="parameter-label"
    @keydown.esc.stop="dismiss"
  >
    <label :for="inputId"><slot /></label>
    <button
      v-if="description"
      type="button"
      class="parameter-help"
      :aria-label="`Help for ${label}`"
      :aria-expanded="visible"
      :aria-controls="helpId"
      :aria-describedby="visible ? helpId : undefined"
      @blur="dismiss"
      @click.stop="visible = !visible"
    >
      ?
    </button>
    <div v-if="description && visible" :id="helpId" role="tooltip" class="parameter-tooltip">
      {{ description }}
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, useId } from "vue";
defineProps<{ inputId: string; label: string; description?: string }>();
const helpId = useId();
const visible = ref(false);
function dismiss() {
  visible.value = false;
}
</script>
<style scoped>
.parameter-label {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.parameter-label label {
  color: #94a3b8;
  font-size: 0.8rem;
  font-weight: 500;
  margin: 0;
}
.parameter-help {
  flex: 0 0 auto;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 1px solid #64748b;
  border-radius: 50%;
  background: transparent;
  color: #cbd5e1;
  cursor: pointer;
  font-size: 12px;
}
.parameter-help:hover,
.parameter-help:focus-visible {
  border-color: #a5b4fc;
  outline: 2px solid #818cf8;
}
.parameter-tooltip {
  position: absolute;
  right: 0;
  top: 100%;
  width: min(260px, 100%);
  box-sizing: border-box;
  z-index: 100;
  padding: 10px;
  border: 1px solid #64748b;
  border-radius: 6px;
  background: #0f172a;
  color: #f1f5f9;
  font-size: 0.8125rem;
  font-weight: 400;
  line-height: 1.45;
  box-shadow: 0 4px 12px #0006;
}
</style>
