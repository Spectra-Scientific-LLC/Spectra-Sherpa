<template>
  <div class="resizable-inspector">
    <div
      class="inspector-resize-handle"
      role="separator"
      aria-label="Resize Inspector"
      aria-orientation="vertical"
      :aria-valuenow="Math.round(modelValue * 100)"
      :aria-valuetext="`${Math.round(modelValue * 100)}% of default width`"
      :aria-valuemin="100"
      :aria-valuemax="200"
      tabindex="0"
      @pointerdown="startResize"
      @pointermove="resize"
      @pointerup="stopResize"
      @pointercancel="stopResize"
      @lostpointercapture="drag = null"
      @keydown="resizeWithKeyboard"
      @dblclick="emit('update:modelValue', 1)"
    ></div>
    <slot />
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{ modelValue: number }>();
const emit = defineEmits<{ "update:modelValue": [value: number] }>();
let drag: { pointerId: number; x: number; width: number; minimum: number } | null = null;
const clamp = (value: number) => Math.max(1, Math.min(2, value));
function startResize(event: PointerEvent) {
  if (event.button !== 0) return;
  const handle = event.currentTarget as HTMLElement;
  const panel = handle.parentElement!;
  const minimum = parseFloat(getComputedStyle(panel).getPropertyValue("--inspector-min")) || 320;
  drag = {
    pointerId: event.pointerId,
    x: event.clientX,
    width: panel.getBoundingClientRect().width,
    minimum,
  };
  handle.setPointerCapture(event.pointerId);
  event.preventDefault();
}
function resize(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return;
  emit("update:modelValue", clamp((drag.width + drag.x - event.clientX) / drag.minimum));
}
function stopResize(event: PointerEvent) {
  drag = null;
  const handle = event.currentTarget as HTMLElement;
  if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
}
function resizeWithKeyboard(event: KeyboardEvent) {
  const values: Record<string, number> = {
    ArrowLeft: props.modelValue + 0.05,
    ArrowRight: props.modelValue - 0.05,
    Home: 1,
    End: 2,
  };
  if (!(event.key in values)) return;
  event.preventDefault();
  emit("update:modelValue", clamp(values[event.key]));
}
</script>

<style scoped>
.resizable-inspector {
  position: relative;
  min-width: 0;
  min-height: 0;
  display: flex;
}
.resizable-inspector :deep(.workflow-inspector) {
  flex: 1;
  min-width: 0;
}
.inspector-resize-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  left: -9px;
  width: 12px;
  z-index: 10;
  cursor: col-resize;
  touch-action: none;
}
.inspector-resize-handle:hover,
.inspector-resize-handle:focus-visible {
  background: rgba(99, 102, 241, 0.3);
  border-radius: 4px;
  outline: 2px solid #818cf8;
}
</style>
