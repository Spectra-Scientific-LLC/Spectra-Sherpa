import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const onMock = vi.fn();
const reactMock = vi.fn(async (element: HTMLDivElement) => {
  (element as HTMLDivElement & { on?: typeof onMock }).on = onMock;
});
const relayoutMock = vi.fn();
const purgeMock = vi.fn();
const resizeMock = vi.fn();
const observeMock = vi.fn();
const disconnectMock = vi.fn();
let resizeObserverCallback: ResizeObserverCallback | null = null;

vi.mock("plotly.js-cartesian-dist-min", () => ({
  default: {
    react: reactMock,
    relayout: relayoutMock,
    purge: purgeMock,
    Plots: {
      resize: resizeMock,
    },
  },
}));

import PlotlyChart from "@/components/PlotlyChart.vue";

async function settle(): Promise<void> {
  await flushPromises();
  await nextTick();
}

describe("PlotlyChart", () => {
  beforeEach(() => {
    onMock.mockReset();
    reactMock.mockClear();
    relayoutMock.mockClear();
    purgeMock.mockClear();
    resizeMock.mockClear();
    observeMock.mockClear();
    disconnectMock.mockClear();
    resizeObserverCallback = null;
    class MockResizeObserver {
      observe = observeMock;
      disconnect = disconnectMock;
      unobserve = vi.fn();

      constructor(callback: ResizeObserverCallback) {
        resizeObserverCallback = callback;
      }
    }
    vi.stubGlobal("ResizeObserver", MockResizeObserver);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("clones data/layout before handing them to Plotly and binds listeners once", async () => {
    const data = [{ x: [1, 2], y: [3, 4], type: "scatter", mode: "markers" }];
    const layout = { title: "Confusion Matrix", xaxis: { title: "Predicted Class" } };

    const wrapper = mount(PlotlyChart, {
      props: {
        data,
        layout,
      },
    });

    await settle();

    expect(reactMock).toHaveBeenCalled();
    const [, plotlyData, plotlyLayout] = reactMock.mock.calls[0];

    expect(plotlyData).not.toBe(data);
    expect(plotlyData[0]).not.toBe(data[0]);
    expect(plotlyLayout).not.toBe(layout);

    plotlyData[0].marker = { color: "red" };
    plotlyLayout.xaxis.extra = "mutated";

    expect((data[0] as Record<string, unknown>).marker).toBeUndefined();
    expect((layout.xaxis as Record<string, unknown>).extra).toBeUndefined();

    expect(onMock).toHaveBeenCalledTimes(2);

    await wrapper.setProps({
      layout: { ...layout, title: "Updated" },
    });
    await settle();

    expect(relayoutMock).toHaveBeenCalled();
    expect(onMock).toHaveBeenCalledTimes(2);
  });

  it("resizes when its container changes size", async () => {
    const wrapper = mount(PlotlyChart, {
      props: {
        data: [{ x: [1], y: [2], type: "scatter" }],
        layout: { title: "Autosize" },
      },
    });

    await settle();
    expect(observeMock).toHaveBeenCalled();

    resizeMock.mockClear();
    resizeObserverCallback?.([], {} as ResizeObserver);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    await settle();

    expect(resizeMock).toHaveBeenCalled();
    wrapper.unmount();
    expect(disconnectMock).toHaveBeenCalled();
  });
});
