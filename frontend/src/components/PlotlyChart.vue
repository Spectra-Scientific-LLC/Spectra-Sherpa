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
  purge: (element: HTMLDivElement) => void;
  Plots: {
    resize: (element: HTMLDivElement) => void;
  };
};

let plotlyClientPromise: Promise<PlotlyClient> | null = null;

const getPlotlyClient = async (): Promise<PlotlyClient> => {
  if (!plotlyClientPromise) {
    plotlyClientPromise = import("plotly.js-dist-min").then(
      (mod) =>
        (mod as unknown as { default?: PlotlyClient }).default ??
        (mod as unknown as PlotlyClient)
    );
  }
  return plotlyClientPromise;
};

const setupEventListeners = () => {
  if (!chartEl.value) return;

  (chartEl.value as any).on("plotly_click", (data: PlotlyClickEvent) => {
    emit("click", data);
  });

  (chartEl.value as any).on("plotly_hover", (data: PlotlyHoverEvent) => {
    emit("hover", data);
  });
};

const render = async () => {
  if (!chartEl.value) {
    return;
  }
  const Plotly = await getPlotlyClient();
  const layout = props.layout || {};
  const config = { responsive: true, displaylogo: false, ...props.config };
  Plotly.react(chartEl.value, props.data, layout, config);
  setupEventListeners();
};

onMounted(() => {
  void render();
  // Plotly computes width at render time; container may not be laid out yet.
  // Resize after the browser paints so the chart fills the full width.
  void nextTick(async () => {
    const Plotly = await getPlotlyClient();
    requestAnimationFrame(() => {
      if (chartEl.value) {
        Plotly.Plots.resize(chartEl.value);
      }
    });
  });
});

watch(
  () => [props.data, props.layout, props.config],
  () => {
    void render();
  },
  { deep: true }
);

onBeforeUnmount(() => {
  if (chartEl.value && plotlyClientPromise) {
    const element = chartEl.value;
    void plotlyClientPromise.then((Plotly) => {
      Plotly.purge(element);
    });
  }
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
