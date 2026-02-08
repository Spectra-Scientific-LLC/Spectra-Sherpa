<template>
  <div class="curve-editor">
    <svg
      ref="svgRef"
      class="curve-editor__canvas"
      viewBox="0 0 100 100"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointerleave="onPointerUp"
    >
      <path :d="curvePath" class="curve-editor__line" />
      <polyline :points="controlPolyline" class="curve-editor__polyline" />
      <circle
        v-for="(point, idx) in points"
        :key="idx"
        :cx="point.x"
        :cy="toSvgY(point.y)"
        r="2.8"
        class="curve-editor__point"
        @pointerdown.stop="onPointerDown(idx, $event)"
      />
    </svg>
    <div class="curve-editor__hint">Drag points to shape the concentration curve.</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import type { CurvePoint } from "@/types";
import { buildSegments, sampleSegments } from "@/utils/curve";

const props = defineProps<{
  points: CurvePoint[];
  samplesPerSegment?: number;
}>();

const emit = defineEmits<{
  (event: "update:points", points: CurvePoint[]): void;
}>();

const svgRef = ref<SVGSVGElement | null>(null);
const activeIndex = ref<number | null>(null);

const toSvgY = (value: number) => 100 - value * 100;
const toValueY = (svgY: number) => 1 - svgY / 100;

const controlPolyline = computed(() => {
  return props.points
    .map((point) => `${point.x},${toSvgY(point.y)}`)
    .join(" ");
});

const curvePath = computed(() => {
  const segments = buildSegments(props.points);
  const samples = sampleSegments(segments, props.samplesPerSegment || 30);
  if (samples.length === 0) {
    return "";
  }
  const [start, ...rest] = samples;
  const commands = [`M ${start.x} ${toSvgY(start.y)}`];
  rest.forEach((point) => {
    commands.push(`L ${point.x} ${toSvgY(point.y)}`);
  });
  return commands.join(" ");
});

const onPointerDown = (index: number, event: PointerEvent) => {
  activeIndex.value = index;
  (event.target as SVGCircleElement).setPointerCapture(event.pointerId);
};

const onPointerMove = (event: PointerEvent) => {
  if (activeIndex.value === null || !svgRef.value) {
    return;
  }
  const rect = svgRef.value.getBoundingClientRect();
  const rawX = ((event.clientX - rect.left) / rect.width) * 100;
  const rawY = ((event.clientY - rect.top) / rect.height) * 100;

  const clampedIndex = activeIndex.value;
  const prev = props.points[clampedIndex - 1];
  const next = props.points[clampedIndex + 1];
  const minX = prev ? prev.x + 1 : 0;
  const maxX = next ? next.x - 1 : 100;

  const nextPoints = props.points.map((point, idx) => {
    if (idx !== clampedIndex) {
      return point;
    }
    const x = Math.min(Math.max(rawX, minX), maxX);
    const y = Math.min(Math.max(toValueY(rawY), 0), 1);
    return { ...point, x, y };
  });

  emit("update:points", nextPoints);
};

const onPointerUp = () => {
  activeIndex.value = null;
};
</script>

<style scoped>
.curve-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.curve-editor__canvas {
  width: 100%;
  height: 200px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}

.curve-editor__line {
  fill: none;
  stroke: #2563eb;
  stroke-width: 1.5;
}

.curve-editor__polyline {
  fill: none;
  stroke: #94a3b8;
  stroke-width: 0.8;
  stroke-dasharray: 4 4;
}

.curve-editor__point {
  fill: #f97316;
  stroke: #c2410c;
  stroke-width: 0.6;
  cursor: grab;
}

.curve-editor__hint {
  font-size: 0.85rem;
  color: #64748b;
}
</style>
