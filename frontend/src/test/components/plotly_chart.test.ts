import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const onMock = vi.fn();
const reactMock = vi.fn(async (element: HTMLDivElement) => {
  (element as HTMLDivElement & { on?: typeof onMock }).on = onMock;
});
const downloadMock = vi.fn().mockResolvedValue("synthetic.png");
const relayoutMock = vi.fn();
const purgeMock = vi.fn();
const resizeMock = vi.fn();
const observeMock = vi.fn();
const disconnectMock = vi.fn();
let resizeObserverCallback: ResizeObserverCallback | null = null;

vi.mock("plotly.js-cartesian-dist-min", () => ({
  default: {
    downloadImage: downloadMock,
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
  it("F2 preserves refusal over generic messages, hides stale data and blocks export", async () => {
    const wrapper = mount(PlotlyChart, {
      props: { data: [{ x: [1], y: [2] }], emptyMessage: "No data yet." },
    });
    await settle();
    await wrapper.setProps({
      layout: { meta: { refusal_reason: "All retained observations are excluded." } },
    });
    await settle();
    expect(wrapper.text()).toContain("All retained observations are excluded.");
    expect(wrapper.text()).not.toContain("No data yet.");
    expect((wrapper.find(".plotly-canvas").element as HTMLElement).style.display).toBe("none");
    expect(purgeMock).toHaveBeenCalled();
    await expect(wrapper.vm.downloadImage({ format: "png" })).rejects.toThrow("excluded");
    await wrapper.setProps({ layout: {}, data: [{ x: [1], y: [3] }] });
    await settle();
    expect((wrapper.find(".plotly-canvas").element as HTMLElement).style.display).not.toBe("none");
    expect(wrapper.text()).not.toContain("excluded");
    await wrapper.vm.downloadImage({ format: "png" });
    wrapper.unmount();
  });
  it("F2 does not describe an empty finished result as pending", async () => {
    const wrapper = mount(PlotlyChart, { props: { data: [] } });
    await settle();
    expect(wrapper.text()).toContain("No renderable plot data available.");
    expect(wrapper.text()).not.toContain("yet");
    wrapper.unmount();
  });
  it("GSC-09 downloads the current rendered chart through its owned module without a global", async () => {
    const wrapper = mount(PlotlyChart, {
      props: { data: [{ type: "scatter", x: [1, 2], y: [3, 4] }] },
    });
    await settle();
    expect((window as unknown as { Plotly?: unknown }).Plotly).toBeUndefined();
    await wrapper.vm.downloadImage({ format: "png", filename: "evidence" });
    expect(downloadMock).toHaveBeenCalledWith(wrapper.find(".plotly-canvas").element, {
      format: "png",
      filename: "evidence",
    });
    expect(reactMock.mock.invocationCallOrder.at(-1)).toBeLessThan(
      downloadMock.mock.invocationCallOrder.at(-1)!,
    );
    wrapper.unmount();
  });
  it("GSC-09 propagates export failures for the owning view to disclose", async () => {
    const wrapper = mount(PlotlyChart, { props: { data: [{ type: "scatter", x: [1], y: [3] }] } });
    await settle();
    downloadMock.mockRejectedValueOnce(new Error("Export unavailable"));
    await expect(wrapper.vm.downloadImage({ format: "png" })).rejects.toThrow("Export unavailable");
    wrapper.unmount();
  });
  it.each(["data", "layout"])(
    "GSC-09 refuses a %s change during render without purging the newer chart",
    async (kind) => {
      const wrapper = mount(PlotlyChart, {
        props: { data: [{ x: [1], y: [2] }], layout: { title: "A" } },
      });
      await settle();
      let release!: () => void;
      reactMock.mockImplementationOnce(
        async () =>
          new Promise<void>((resolve) => {
            release = resolve;
          }),
      );
      const outcome = wrapper.vm.downloadImage({ format: "png" }).catch((error) => error);
      await settle();
      await wrapper.setProps(
        kind === "data" ? { data: [{ x: [3], y: [4] }] } : { layout: { title: "B" } },
      );
      release();
      await settle();
      expect(await outcome).toBeInstanceOf(Error);
      expect(downloadMock).not.toHaveBeenCalled();
      expect(purgeMock).not.toHaveBeenCalled();
      await wrapper.vm.downloadImage({ format: "png" });
      expect(downloadMock).toHaveBeenCalledTimes(1);
      const args = reactMock.mock.calls.at(-1)!;
      expect(kind === "data" ? args[1] : args[2]).toEqual(
        kind === "data" ? [{ x: [3], y: [4] }] : { title: "B" },
      );
      wrapper.unmount();
    },
  );
  it("GSC-09 serializes concurrent download requests and rejects superseded work", async () => {
    const wrapper = mount(PlotlyChart, { props: { data: [{ x: [1], y: [2] }] } });
    await settle();
    const results = await Promise.allSettled([
      wrapper.vm.downloadImage({ format: "png", filename: "first" }),
      wrapper.vm.downloadImage({ format: "png", filename: "second" }),
    ]);
    expect(results.map((r) => r.status)).toEqual(["rejected", "fulfilled"]);
    expect(downloadMock).toHaveBeenCalledTimes(1);
    expect(downloadMock.mock.calls[0][1]).toEqual({ format: "png", filename: "second" });
    expect(purgeMock).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  beforeEach(() => {
    downloadMock.mockReset().mockResolvedValue("synthetic.png");
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
    const element = wrapper.find(".plotly-canvas").element;
    Object.defineProperty(element, "isConnected", { value: true, configurable: true });
    vi.spyOn(element, "getClientRects").mockReturnValue([{} as DOMRect]);
    expect(observeMock).toHaveBeenCalled();

    resizeMock.mockClear();
    resizeObserverCallback?.([], {} as ResizeObserver);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    await settle();

    expect(resizeMock).toHaveBeenCalled();
    wrapper.unmount();
    expect(disconnectMock).toHaveBeenCalled();
  });

  it("does not ask Plotly to resize a hidden chart", async () => {
    const wrapper = mount(PlotlyChart, {
      props: {
        data: [{ x: [1], y: [2], type: "scatter" }],
      },
    });
    const element = wrapper.find(".plotly-canvas").element;
    Object.defineProperty(element, "isConnected", { value: true, configurable: true });
    vi.spyOn(element, "getClientRects").mockReturnValue([]);
    await settle();
    resizeMock.mockClear();
    resizeObserverCallback?.([], {} as ResizeObserver);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    await settle();
    expect(resizeMock).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("keeps populated results renderable through repeated hide and reopen cycles", async () => {
    const data = [{ x: [1, 2, 3], y: [4, 5, 6], type: "scatter", mode: "lines" }];
    const wrapper = mount(PlotlyChart, {
      props: {
        data,
        layout: { title: "Retained scores" },
      },
    });
    const element = wrapper.find(".plotly-canvas").element;
    let visible = true;
    Object.defineProperty(element, "isConnected", { value: true, configurable: true });
    vi.spyOn(element, "getClientRects").mockImplementation(
      () => (visible ? ([{} as DOMRect] as DOMRectList) : ([] as unknown as DOMRectList)),
    );
    await settle();

    expect(reactMock).toHaveBeenCalled();
    expect(reactMock.mock.calls.at(-1)?.[1]).toEqual(data);
    expect(wrapper.text()).not.toContain("No renderable plot data available.");

    for (let cycle = 0; cycle < 2; cycle += 1) {
      visible = false;
      resizeMock.mockClear();
      resizeObserverCallback?.([], {} as ResizeObserver);
      await new Promise((resolve) => requestAnimationFrame(resolve));
      await settle();
      expect(resizeMock).not.toHaveBeenCalled();

      visible = true;
      resizeObserverCallback?.([], {} as ResizeObserver);
      await new Promise((resolve) => requestAnimationFrame(resolve));
      await settle();
      expect(resizeMock).toHaveBeenCalledTimes(1);
      expect((element as HTMLElement).style.display).not.toBe("none");
      expect(wrapper.text()).not.toContain("No renderable plot data available.");
    }

    wrapper.unmount();
    resizeMock.mockClear();
    resizeObserverCallback?.([], {} as ResizeObserver);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(resizeMock).not.toHaveBeenCalled();
  });

  it("does not render into a detached element when unmounted during lazy loading", async () => {
    const wrapper = mount(PlotlyChart, {
      props: {
        data: [{ x: [1], y: [2], type: "scatter" }],
      },
    });

    wrapper.unmount();
    await settle();

    expect(reactMock).not.toHaveBeenCalled();
  });
});
