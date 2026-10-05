<template>
  <div class="plotly-chart" tabindex="0" @pointerdown="notePlotFocus" @focusin="notePlotFocus">
    <div v-if="loading" class="plotly-overlay">Rendering chart...</div>
    <div v-if="!loading && isEmpty" class="plotly-empty" role="status">
      {{ emptyMessage }}
    </div>
    <div v-show="!isEmpty" ref="chartEl" class="plotly-canvas"></div>
  </div>
</template>

<script setup lang="ts">
import { focusPlot, releasePlot, nextPlotAttentionId } from "@/lib/sherpaAttention";
import { scientificPlotRefusal } from "@/utils/scientificPlotState";
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
  attentionNodeId?: string;
  attentionPlotKey?: string;
}>();

const emit = defineEmits<{
  click: [event: PlotlyClickEvent];
  hover: [event: PlotlyHoverEvent];
}>();

const attentionId = nextPlotAttentionId();
const notePlotFocus = () => focusPlot(attentionId, props.attentionNodeId, props.attentionPlotKey);
onBeforeUnmount(() => releasePlot(attentionId));
const chartEl = ref<HTMLDivElement | null>(null);
const refusal = computed(() => scientificPlotRefusal(props.layout));
const emptyMessage = computed(
  () => refusal.value || props.emptyMessage || "No renderable plot data available.",
);
const isEmpty = computed(() => !!refusal.value || !props.data || props.data.length === 0);

type PlotlyClient = {
  downloadImage: (element: HTMLDivElement, options: Record<string, unknown>) => Promise<unknown>;
  react: (
    element: HTMLDivElement,
    data: PlotlyData[],
    layout: PlotlyLayout,
    config: PlotlyConfig,
  ) => unknown | Promise<unknown>;
  relayout: (element: HTMLDivElement, update: PlotlyLayout) => unknown | Promise<unknown>;
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
let disposed = false;
let renderRevision = 0;
let chartWork: Promise<unknown> = Promise.resolve();
let needsFullRender = true;

const cloneForPlotly = <T,>(value: T): T => {
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
        (mod as unknown as { default?: PlotlyClient }).default ?? (mod as unknown as PlotlyClient),
    );
  }
  return plotlyClientPromise;
};

const setupEventListeners = (element: HTMLDivElement) => {
  if (disposed || chartEl.value !== element || listenersBound) return;

  const plotlyElement = element as PlotlyElement;
  if (typeof plotlyElement.on !== "function") return;

  plotlyElement.on("plotly_click", (data) => {
    emit("click", data as PlotlyClickEvent);
  });

  plotlyElement.on("plotly_hover", (data) => {
    emit("hover", data as PlotlyHoverEvent);
  });

  listenersBound = true;
};

const isDisplayed = (element: HTMLDivElement): boolean =>
  element.isConnected !== false && element.getClientRects().length > 0;

const scheduleResize = () => {
  if (resizeFrame !== null) {
    cancelAnimationFrame(resizeFrame);
  }
  resizeFrame = requestAnimationFrame(async () => {
    resizeFrame = null;
    const element = chartEl.value;
    if (disposed || !element) return;
    const Plotly = await getPlotlyClient();
    // Plotly.Plots.resize throws when v-show has left the chart in a hidden
    // tab or collapsed panel. ResizeObserver will schedule this again once
    // the element receives a visible client rect.
    if (!disposed && chartEl.value === element && isDisplayed(element)) {
      Plotly.Plots.resize(element);
    }
  });
};

const render = (layoutOnly = false): Promise<boolean> => {
  const revision = ++renderRevision;
  if (!layoutOnly) needsFullRender = true;
  const task = chartWork
    .catch(() => undefined)
    .then(async () => {
      const element = chartEl.value;
      if (disposed || !element || revision !== renderRevision) return false;
      const Plotly = await getPlotlyClient();
      if (disposed || chartEl.value !== element || revision !== renderRevision) return false;
      if (isEmpty.value) {
        Plotly.purge(element);
        listenersBound = false;
        needsFullRender = true;
        return false;
      }
      if (layoutOnly && !needsFullRender) {
        const flat: Record<string, unknown> = {};
        for (const [key, val] of Object.entries(cloneForPlotly(props.layout || {}))) {
          if (val && typeof val === "object" && !Array.isArray(val)) {
            for (const [subKey, subVal] of Object.entries(val as Record<string, unknown>))
              flat[`${key}.${subKey}`] = subVal;
          } else flat[key] = val;
        }
        await Plotly.relayout(element, flat);
      } else {
        await Plotly.react(
          element,
          cloneForPlotly(props.data || []),
          cloneForPlotly(props.layout || {}),
          { responsive: true, displaylogo: false, ...cloneForPlotly(props.config || {}) },
        );
      }
      if (disposed || chartEl.value !== element) {
        Plotly.purge(element);
        return false;
      }
      // Stale work must never purge a newer rendering. All chart writes are serialized.
      if (revision !== renderRevision) return false;
      needsFullRender = false;
      setupEventListeners(element);
      return true;
    });
  chartWork = task;
  return task;
};

async function downloadImage(options: Record<string, unknown>) {
  await nextTick();
  const element = chartEl.value;
  if (disposed || !element || isEmpty.value)
    throw new Error(refusal.value || "No rendered plot is available for download.");
  const rendered = await render();
  const revision = renderRevision;
  if (!rendered) throw new Error("The plot changed before download. Try again.");
  const task = chartWork.then(async () => {
    const Plotly = await getPlotlyClient();
    if (disposed || chartEl.value !== element || revision !== renderRevision)
      throw new Error("The plot changed before download. Try again.");
    await Plotly.downloadImage(element, options);
  });
  chartWork = task;
  await task;
}
defineExpose({ downloadImage });

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
  { deep: true },
);

// Layout and data updates share the same chart work queue as image export.
watch(
  () => props.layout,
  () => {
    void render(true);
  },
  { deep: true },
);

onBeforeUnmount(() => {
  disposed = true;
  renderRevision += 1;
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
