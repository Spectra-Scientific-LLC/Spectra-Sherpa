<template>
  <div class="conc-curve-editor">
    <div v-if="!hideToolbar" class="conc-curve-editor__toolbar">
      <label class="conc-curve-editor__points">
        Points
        <InputNumber
          :modelValue="pointCount"
          :min="MIN_POINTS"
          :max="MAX_POINTS"
          :useGrouping="false"
          showButtons
          buttonLayout="horizontal"
          incrementButtonIcon="pi pi-plus"
          decrementButtonIcon="pi pi-minus"
          @update:model-value="onPointCount"
        />
      </label>
      <slot name="actions" />
    </div>
    <svg
      ref="svgRef"
      class="conc-curve-editor__canvas"
      :viewBox="`${-PAD_L} ${-PAD_T} ${100 + PAD_L + PAD_R} ${100 + PAD_T + PAD_B}`"
      role="img"
      :aria-label="`Concentration shape for ${title}`"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointerleave="onPointerUp"
    >
      <!-- plot frame -->
      <rect x="0" y="0" width="100" height="100" class="conc-curve-editor__frame" />
      <!-- grid + ticks -->
      <g class="conc-curve-editor__grid">
        <template v-for="gx in X_TICKS" :key="`gx-${gx}`">
          <line :x1="gx" y1="0" :x2="gx" y2="100" />
          <text :x="gx" y="111" text-anchor="middle">{{ gx }}</text>
        </template>
        <template v-for="gy in Y_TICKS" :key="`gy-${gy}`">
          <line x1="0" :y1="toSvgY(gy)" x2="100" :y2="toSvgY(gy)" />
          <text x="-4" :y="toSvgY(gy) + 3" text-anchor="end">{{ gy.toFixed(1) }}</text>
        </template>
      </g>
      <text class="conc-curve-editor__axis" x="50" y="123" text-anchor="middle">Sample index</text>
      <text
        class="conc-curve-editor__axis"
        :x="-PAD_L + 6"
        y="50"
        text-anchor="middle"
        :transform="`rotate(-90 ${-PAD_L + 6} 50)`"
      >
        Relative Concentration
      </text>
      <!-- spline + control polyline -->
      <polyline :points="controlPolyline" class="conc-curve-editor__polyline" />
      <path :d="curvePath" class="conc-curve-editor__line" :style="{ stroke: color }" />
      <circle
        v-for="(point, idx) in points"
        :key="idx"
        :cx="point.x"
        :cy="toSvgY(point.y)"
        r="2.6"
        class="conc-curve-editor__handle"
        :style="{ fill: color, stroke: color }"
        :tabindex="0"
        @pointerdown.stop="onPointerDown(idx, $event)"
        @keydown="onHandleKey(idx, $event)"
      />
    </svg>
    <div v-if="!hideHint" class="conc-curve-editor__hint">
      Drag handles vertically to shape the trace. Shape is 0–1; the per-species ppm
      multiplier sets the magnitude, so species at very different concentrations stay
      comparable here.
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import InputNumber from "primevue/inputnumber";
import type { CurvePoint } from "@/types";
import {
  buildSegments,
  resampleConcentrationShape,
  sampleSegments,
  seedConcentrationShape,
} from "@/utils/curve";

const MIN_POINTS = 4;
const MAX_POINTS = 60;
// Asymmetric padding inside the viewBox so axis ticks/labels have room
// without distorting the 0..100 x 0..100 plot area.
const PAD_L = 24;
const PAD_R = 4;
const PAD_T = 6;
const PAD_B = 26;
const X_TICKS = [0, 20, 40, 60, 80, 100];
const Y_TICKS = [0, 0.25, 0.5, 0.75, 1];

const props = withDefaults(
  defineProps<{
    points: CurvePoint[];
    color?: string;
    title?: string;
    hideToolbar?: boolean;
    hideHint?: boolean;
  }>(),
  { color: "#2563eb", title: "component", hideToolbar: false, hideHint: false },
);

const emit = defineEmits<{
  (event: "update:points", points: CurvePoint[]): void;
}>();

const svgRef = ref<SVGSVGElement | null>(null);
const activeIndex = ref<number | null>(null);

const pointCount = computed(() => props.points.length);

const toSvgY = (value: number) => 100 - value * 100;
const toValueY = (svgY: number) => 1 - svgY / 100;

const controlPolyline = computed(() =>
  props.points.map((point) => `${point.x},${toSvgY(point.y)}`).join(" "),
);

const curvePath = computed(() => {
  const samples = sampleSegments(buildSegments(props.points), 30);
  if (samples.length === 0) return "";
  const [start, ...rest] = samples;
  return [
    `M ${start.x} ${toSvgY(clamp01(start.y))}`,
    ...rest.map((p) => `L ${p.x} ${toSvgY(clamp01(p.y))}`),
  ].join(" ");
});

const clamp01 = (v: number) => Math.min(Math.max(v, 0), 1);

const seedShape = (count: number): CurvePoint[] =>
  seedConcentrationShape(count, MIN_POINTS, MAX_POINTS);

const onPointCount = (next: number | null) => {
  const count = Math.min(Math.max(Math.round(Number(next) || MIN_POINTS), MIN_POINTS), MAX_POINTS);
  emit("update:points", resampleConcentrationShape(props.points, count, MIN_POINTS, MAX_POINTS));
};

const onPointerDown = (index: number, event: PointerEvent) => {
  activeIndex.value = index;
  (event.target as SVGCircleElement).setPointerCapture(event.pointerId);
};

const onPointerMove = (event: PointerEvent) => {
  if (activeIndex.value === null || !svgRef.value) return;
  // Use the SVG CTM rather than getBoundingClientRect: the viewBox is padded
  // and preserveAspectRatio letterboxes, so a naive rect ratio drifts from
  // the cursor. matrixTransform(inverse(CTM)) gives exact plot-space coords.
  const ctm = svgRef.value.getScreenCTM();
  if (!ctm) return;
  const pt = svgRef.value.createSVGPoint();
  pt.x = event.clientX;
  pt.y = event.clientY;
  const svgY = pt.matrixTransform(ctm.inverse()).y;
  // Vertical drag only — x stays fixed (handle-tuned, like the Project0 designer).
  const next = props.points.map((point, idx) =>
    idx === activeIndex.value ? { ...point, y: clamp01(toValueY(svgY)) } : point,
  );
  emit("update:points", next);
};

const onPointerUp = () => {
  activeIndex.value = null;
};

const onHandleKey = (index: number, event: KeyboardEvent) => {
  const step = event.shiftKey ? 0.1 : 0.02;
  let delta = 0;
  if (event.key === "ArrowUp") delta = step;
  else if (event.key === "ArrowDown") delta = -step;
  else return;
  event.preventDefault();
  const next = props.points.map((point, idx) =>
    idx === index ? { ...point, y: clamp01(point.y + delta) } : point,
  );
  emit("update:points", next);
};

defineExpose({ seedShape });
</script>

<style scoped>
.conc-curve-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.conc-curve-editor__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.conc-curve-editor__points {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-color-secondary);
  text-transform: uppercase;
}

.conc-curve-editor__points :deep(.p-inputnumber-input) {
  width: 4rem;
  text-align: center;
}

.conc-curve-editor__canvas {
  width: 100%;
  aspect-ratio: 1 / 1;
  height: auto;
  min-height: 220px;
  background: var(--surface-50, #f8fafc);
  border: 1px solid var(--surface-200, #e2e8f0);
  border-radius: 10px;
}

.conc-curve-editor__frame {
  fill: #fff;
  stroke: #cbd5e1;
  stroke-width: 0.5;
}

.conc-curve-editor__grid line {
  stroke: #e2e8f0;
  stroke-width: 0.4;
}

.conc-curve-editor__grid text {
  fill: #64748b;
  font-size: 5px;
}

.conc-curve-editor__axis {
  fill: #475569;
  font-size: 5.5px;
  font-weight: 600;
}

.conc-curve-editor__line {
  fill: none;
  stroke-width: 1.6;
}

.conc-curve-editor__polyline {
  fill: none;
  stroke: #94a3b8;
  stroke-width: 0.6;
  stroke-dasharray: 3 3;
}

.conc-curve-editor__handle {
  stroke-width: 0.6;
  cursor: ns-resize;
}

.conc-curve-editor__handle:focus {
  outline: none;
  stroke-width: 1.6;
}

.conc-curve-editor__hint {
  font-size: 0.8rem;
  color: var(--text-color-secondary, #64748b);
}
</style>
