<template>
  <div class="plotly-chart">
    <div v-if="loading" class="plotly-overlay">Rendering chart...</div>
    <div v-if="!loading && isEmpty" class="plotly-empty">
      {{ emptyMessage }}
    </div>
    <div ref="chartEl" class="plotly-canvas"></div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

type PlotlyData = Record<string, unknown>;
type PlotlyLayout = Record<string, unknown>;
type PlotlyConfig = Record<string, unknown>;

interface PlotlyClickEvent {
  points: Array<{
    x: number;
    y: number;
    z?: number;
    pointIndex: number;
    curveNumber: number;
    data: PlotlyData;
  }>;
}

interface PlotlyHoverEvent {
  points: Array<{
    x: number;
    y: number;
    z?: number;
    pointIndex: number;
    curveNumber: number;
    data: PlotlyData;
  }>;
}

const props = defineProps<{
  data: PlotlyData[];
  layout?: PlotlyLayout;
  config?: PlotlyConfig;
  loading?: boolean;
  emptyMessage?: string;
}>();

const emit = defineEmits<{
  click: [event: PlotlyClickEvent];
  hover: [event: PlotlyHoverEvent];
}>();

const chartEl = ref<HTMLDivElement | null>(null);
const emptyMessage = computed(() => props.emptyMessage || "No data yet.");
const isEmpty = computed(() => !props.data || props.data.length === 0);

type PlotlyClient = {
  react: (
    element: HTMLDivElement,
    data: PlotlyData[],
    layout: PlotlyLayout,
    config: PlotlyConfig
  ) => unknown | Promise<unknown>;
  relayout: (
    element: HTMLDivElement,
    update: PlotlyLayout
  ) => unknown | Promise<unknown>;
  purge: (element: HTMLDivElement) => void;
  Plots: {
    resize: (element: HTMLDivElement) => void;
  };
};

type PlotlyElement = HTMLDivElement & {
  on: (eventName: string, handler: (data: unknown) => void) => void;
};

let plotlyClientPromise: Promise<PlotlyClient> | null = null;
let listenersBound = false;
let resizeObserver: ResizeObserver | null = null;
let resizeFrame: number | null = null;

const cloneForPlotly = <T>(value: T): T => {
  if (value == null) {
    return value;
  }
  if (typeof structuredClone === "function") {
    try {
      return structuredClone(value);
    } catch {
      // Vue proxies and some DOM-backed values can fail structuredClone.
    }
  }
  return JSON.parse(JSON.stringify(value)) as T;
};

const getPlotlyClient = async (): Promise<PlotlyClient> => {
  if (!plotlyClientPromise) {
    plotlyClientPromise = import("plotly.js-cartesian-dist-min").then(
      (mod) =>
        (mod as unknown as { default?: PlotlyClient }).default ??
        (mod as unknown as PlotlyClient)
    );
  }
  return plotlyClientPromise;
};

const setupEventListeners = () => {
  if (!chartEl.value || listenersBound) return;

  const plotlyElement = chartEl.value as PlotlyElement;
  if (typeof plotlyElement.on !== "function") return;

  plotlyElement.on("plotly_click", (data) => {
    emit("click", data as PlotlyClickEvent);
  });

  plotlyElement.on("plotly_hover", (data) => {
    emit("hover", data as PlotlyHoverEvent);
  });

  listenersBound = true;
};

const scheduleResize = () => {
  if (resizeFrame !== null) {
    cancelAnimationFrame(resizeFrame);
  }
  resizeFrame = requestAnimationFrame(async () => {
    resizeFrame = null;
    if (!chartEl.value) return;
    const Plotly = await getPlotlyClient();
    if (chartEl.value) {
      Plotly.Plots.resize(chartEl.value);
    }
  });
};

const render = async () => {
  if (!chartEl.value) {
    return;
  }
  const Plotly = await getPlotlyClient();
  const data = cloneForPlotly(props.data || []);
  const layout = cloneForPlotly(props.layout || {});
  const config = { responsive: true, displaylogo: false, ...cloneForPlotly(props.config || {}) };
  await Plotly.react(chartEl.value, data, layout, config);
  setupEventListeners();
};

onMounted(() => {
  void render();
  // Plotly computes width at render time; container may not be laid out yet.
  // Resize after the browser paints so the chart fills the full width.
  void nextTick(() => {
    scheduleResize();
    if (typeof ResizeObserver !== "undefined" && chartEl.value) {
      resizeObserver = new ResizeObserver(scheduleResize);
      resizeObserver.observe(chartEl.value);
    }
  });
});

// Full re-render when data or config change
watch(
  () => [props.data, props.config],
  () => {
    void render();
  },
  { deep: true }
);

// Layout-only update (axis labels, titles) — use relayout to avoid re-rendering traces
watch(
  () => props.layout,
  async (newLayout) => {
    if (!chartEl.value || !newLayout) return;
    const Plotly = await getPlotlyClient();
    // Flatten layout for relayout: e.g. { xaxis: { title: "X" } } → { "xaxis.title": "X" }
    const flat: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(newLayout)) {
      if (val && typeof val === "object" && !Array.isArray(val)) {
        for (const [subKey, subVal] of Object.entries(val as Record<string, unknown>)) {
          flat[`${key}.${subKey}`] = subVal;
        }
      } else {
        flat[key] = val;
      }
    }
    Plotly.relayout(chartEl.value, flat);
  },
  { deep: true }
);

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
  if (resizeFrame !== null) {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = null;
  }
  if (chartEl.value && plotlyClientPromise) {
    const element = chartEl.value;
    void plotlyClientPromise.then((Plotly) => {
      Plotly.purge(element);
    });
  }
  listenersBound = false;
});
</script>

<style scoped>
.plotly-chart {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 320px;
}

.plotly-canvas {
  width: 100%;
  height: 100%;
}

.plotly-overlay,
.plotly-empty {
  position: absolute;
  top: 12px;
  left: 12px;
  right: 12px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.08);
  color: #0f172a;
  font-size: 0.9rem;
  z-index: 2;
}
</style>
