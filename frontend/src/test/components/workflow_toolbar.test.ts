/**
 * Regression coverage for the redesigned "Add Nodes" toolbar.
 *
 * These tests guard the UX contracts the panel is supposed to honor:
 *   1. Categories expand on CLICK only (no hover-to-expand),
 *   2. Multiple categories can be open at the same time,
 *   3. A search box at the top filters nodes live and remains the first element,
 *   4. Hovering a node shows a FLOATING tooltip with the FULL description,
 *      positioned to the right of the button via position: fixed so it can
 *      overlay the main workflow canvas,
 *   5. A header chevron collapses/expands the whole toolbar and flips direction.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import WorkflowToolbar from "@/views/workflow-builder/WorkflowToolbar.vue";
import { useWorkflowStore } from "@/stores/workflow";
import type { NodeTypeMetadata } from "@/types";

// Block any accidental network calls; the tests pre-populate the store directly.
vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { nodes: [], total: 0 } }),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const makeNode = (overrides: Partial<NodeTypeMetadata> & Pick<NodeTypeMetadata, "node_type" | "category" | "label">): NodeTypeMetadata => ({
  description: "",
  parameters: [],
  input_types: [],
  output_type: "",
  ...overrides,
});

const seedLibrary: NodeTypeMetadata[] = [
  makeNode({
    node_type: "data.my_dataset",
    category: "data",
    label: "My Dataset",
    description: "Load the selected My Dataset into the workflow.",
  }),
  makeNode({
    node_type: "data.source",
    category: "data",
    label: "Data Source",
    description: "Legacy source node kept for saved workflows.",
  }),
  makeNode({
    node_type: "data.file_load",
    category: "data",
    label: "File Load",
    description: "Read CSV",
  }),
  makeNode({
    node_type: "data.load_group",
    category: "data",
    label: "Load Group",
    description: "Legacy group file loader.",
  }),
  makeNode({
    node_type: "data.nist_library",
    category: "data",
    label: "NIST Library",
    description: "Legacy NIST library loader.",
  }),
  makeNode({
    node_type: "data.synthetic_curve",
    category: "synthesis",
    label: "Synthetic Curve",
    description: "Generate synthetic concentration curves.",
  }),
  makeNode({
    node_type: "preprocess.smooth",
    category: "preprocessing",
    label: "Smooth",
    description: "Apply Savitzky-Golay smoothing to reduce high-frequency noise in spectra.",
  }),
  makeNode({
    node_type: "preprocess.normalize",
    category: "preprocessing",
    label: "Normalize",
    description: "Normalize spectra to unit area or vector length.",
  }),
  makeNode({
    node_type: "model.pls",
    category: "regression",
    label: "PLS Regression",
    description: "Partial Least Squares regression for quantitative prediction tasks.",
  }),
  makeNode({
    node_type: "output.plot",
    category: "output",
    label: "Plot",
    description: "Render a line plot.",
  }),
];

const seedStore = () => {
  const store = useWorkflowStore();
  const library = new Map<string, NodeTypeMetadata>();
  for (const node of seedLibrary) {
    library.set(node.node_type, node);
  }
  store.nodeLibrary = library;
};

const mountToolbar = async () => {
  const wrapper = mount(WorkflowToolbar);
  // Let onMounted + nextTick (search auto-focus path) settle.
  await flushPromises();
  return wrapper;
};

describe("WorkflowToolbar", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    seedStore();
  });

  describe("click-to-expand behavior", () => {
    it("starts with all categories collapsed (no auto-expand)", async () => {
      const wrapper = await mountToolbar();

      const dataNodes = wrapper.get('[data-testid="section-nodes-data"]');
      const preprocNodes = wrapper.get('[data-testid="section-nodes-preprocessing"]');
      expect(dataNodes.classes()).not.toContain("expanded");
      expect(preprocNodes.classes()).not.toContain("expanded");
    });

    it("expands a category on click and collapses on a second click", async () => {
      const wrapper = await mountToolbar();
      const header = wrapper.get('[data-testid="section-header-data"]');
      const nodes = wrapper.get('[data-testid="section-nodes-data"]');

      await header.trigger("click");
      expect(nodes.classes()).toContain("expanded");

      await header.trigger("click");
      expect(nodes.classes()).not.toContain("expanded");
    });

    it("does NOT expand a category on hover (mouseenter is a no-op)", async () => {
      const wrapper = await mountToolbar();
      const section = wrapper.get('[data-testid="section-data"]');
      const nodes = wrapper.get('[data-testid="section-nodes-data"]');

      await section.trigger("mouseenter");
      expect(nodes.classes()).not.toContain("expanded");
    });

    it("allows multiple categories to be open at the same time", async () => {
      const wrapper = await mountToolbar();

      await wrapper.get('[data-testid="section-header-data"]').trigger("click");
      await wrapper.get('[data-testid="section-header-preprocessing"]').trigger("click");
      await wrapper.get('[data-testid="section-header-regression"]').trigger("click");

      expect(wrapper.get('[data-testid="section-nodes-data"]').classes()).toContain("expanded");
      expect(wrapper.get('[data-testid="section-nodes-preprocessing"]').classes()).toContain("expanded");
      expect(wrapper.get('[data-testid="section-nodes-regression"]').classes()).toContain("expanded");
    });

    it("shows only My Dataset in Data while keeping Synthetic Curve under Synthesis", async () => {
      const wrapper = await mountToolbar();

      await wrapper.get('[data-testid="section-header-data"]').trigger("click");
      const dataSection = wrapper.get('[data-testid="section-nodes-data"]');
      expect(dataSection.html()).toContain("My Dataset");
      expect(dataSection.find('[data-testid="node-button-data.source"]').exists()).toBe(false);
      expect(dataSection.find('[data-testid="node-button-data.file_load"]').exists()).toBe(false);
      expect(dataSection.find('[data-testid="node-button-data.load_group"]').exists()).toBe(false);
      expect(dataSection.find('[data-testid="node-button-data.nist_library"]').exists()).toBe(false);

      await wrapper.get('[data-testid="section-header-synthesis"]').trigger("click");
      const synthesisSection = wrapper.get('[data-testid="section-nodes-synthesis"]');
      expect(synthesisSection.find('[data-testid="node-button-data.synthetic_curve"]').exists()).toBe(true);
    });
  });

  describe("search", () => {
    it("renders the Search section as the first category in the toolbar", async () => {
      const wrapper = await mountToolbar();
      const firstSection = wrapper.find(".toolbar-content > .section");
      expect(firstSection.attributes("data-testid")).toBe("section-search");
    });

    it("filters nodes by substring match on label", async () => {
      const wrapper = await mountToolbar();
      const input = wrapper.get('[data-testid="toolbar-search-input"]');

      await input.setValue("smo");
      const results = wrapper.get('[data-testid="toolbar-search-results"]');
      expect(results.html()).toContain("Smooth");
      // Should NOT contain unrelated labels.
      expect(results.html()).not.toContain("PLS Regression");
      expect(results.html()).not.toContain("Data Source");
    });

    it("hides legacy ingestion nodes from palette search", async () => {
      const wrapper = await mountToolbar();
      const input = wrapper.get('[data-testid="toolbar-search-input"]');

      await input.setValue("data.source");
      expect(wrapper.get('[data-testid="toolbar-search-empty"]').text()).toContain("data.source");

      await input.setValue("NIST");
      expect(wrapper.get('[data-testid="toolbar-search-empty"]').text()).toContain("NIST");
    });

    it("is case-insensitive and also matches node_type identifiers", async () => {
      const wrapper = await mountToolbar();
      const input = wrapper.get('[data-testid="toolbar-search-input"]');

      await input.setValue("PLS");
      expect(wrapper.get('[data-testid="toolbar-search-results"]').html()).toContain("PLS Regression");

      await input.setValue("output.plot");
      expect(wrapper.get('[data-testid="toolbar-search-results"]').html()).toContain("Plot");
    });

    it("shows an empty-state message when no nodes match", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="toolbar-search-input"]').setValue("xyzzy_no_such_node");

      const empty = wrapper.find('[data-testid="toolbar-search-empty"]');
      expect(empty.exists()).toBe(true);
      expect(empty.text()).toContain("xyzzy_no_such_node");
    });

    it("emits add-node and clears the search box when a search result is clicked", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="toolbar-search-input"]').setValue("smooth");

      const hit = wrapper.get('[data-testid="toolbar-search-results"] [data-testid="node-button-preprocess.smooth"]');
      await hit.trigger("click");

      const emitted = wrapper.emitted("add-node");
      expect(emitted).toBeTruthy();
      expect(emitted?.[0]).toEqual(["preprocess.smooth"]);

      const input = wrapper.get('[data-testid="toolbar-search-input"]').element as HTMLInputElement;
      expect(input.value).toBe("");
    });

    it("does not render search-results container when query is empty", async () => {
      const wrapper = await mountToolbar();
      expect(wrapper.find('[data-testid="toolbar-search-results"]').exists()).toBe(false);
    });
  });

  describe("floating hover tooltip", () => {
    const stubRect = (el: HTMLElement, rect: Partial<DOMRect>) => {
      const full: DOMRect = {
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        width: 0,
        height: 0,
        x: 0,
        y: 0,
        toJSON: () => ({}),
        ...rect,
      } as DOMRect;
      el.getBoundingClientRect = () => full;
    };

    it("is not rendered until the user hovers a node", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="section-header-data"]').trigger("click");
      expect(wrapper.find('[data-testid="node-hover-tooltip"]').exists()).toBe(false);
    });

    it("shows the FULL description (not truncated) on mouseenter", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="section-header-data"]').trigger("click");

      const button = wrapper.get('[data-testid="node-button-data.my_dataset"]');
      await button.trigger("mouseenter");

      const tooltip = wrapper.get('[data-testid="node-hover-tooltip"]');
      // Full description (from seedLibrary), no 7-word ellipsis.
      expect(tooltip.text()).toContain(
        "Load the selected My Dataset into the workflow."
      );
      // Label rendered as tooltip title.
      expect(tooltip.get(".node-tooltip-title").text()).toBe("My Dataset");
      // > 9 words proves the 7-word cap is gone.
      const words = tooltip.get(".node-tooltip-body").text().split(/\s+/).filter(Boolean);
      expect(words.length).toBeGreaterThan(6);
    });

    it("hides the tooltip on mouseleave", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="section-header-data"]').trigger("click");
      const button = wrapper.get('[data-testid="node-button-data.my_dataset"]');

      await button.trigger("mouseenter");
      expect(wrapper.find('[data-testid="node-hover-tooltip"]').exists()).toBe(true);

      await button.trigger("mouseleave");
      expect(wrapper.find('[data-testid="node-hover-tooltip"]').exists()).toBe(false);
    });

    it("positions the tooltip to the right of the hovered button via fixed coords", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="section-header-data"]').trigger("click");

      const button = wrapper.get('[data-testid="node-button-data.my_dataset"]');
      stubRect(button.element as HTMLElement, { top: 150, left: 20, right: 200, bottom: 180, width: 180, height: 30 });

      await button.trigger("mouseenter");

      const tooltip = wrapper.get('[data-testid="node-hover-tooltip"]');
      const styleAttr = tooltip.attributes("style") || "";
      // The gap is 12px; right=200 → left should land at 212px.
      expect(styleAttr).toContain("left: 212px");
      expect(styleAttr).toContain("top: 150px");
    });

    it("flips to the left when the tooltip would overflow the viewport on the right", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="section-header-data"]').trigger("click");

      const button = wrapper.get('[data-testid="node-button-data.my_dataset"]');
      // Force the button to sit near the right edge of a narrow viewport.
      Object.defineProperty(window, "innerWidth", { value: 400, configurable: true });
      stubRect(button.element as HTMLElement, { top: 100, left: 180, right: 380, bottom: 130, width: 200, height: 30 });

      await button.trigger("mouseenter");

      const tooltip = wrapper.get('[data-testid="node-hover-tooltip"]');
      const styleAttr = tooltip.attributes("style") || "";
      // Tooltip should land to the LEFT of the button (left < button.left).
      const leftMatch = styleAttr.match(/left:\s*(-?\d+(?:\.\d+)?)px/);
      expect(leftMatch).not.toBeNull();
      expect(parseFloat(leftMatch![1])).toBeLessThan(180);
    });

    it("does not render the inline .node-desc anymore (description lives in the floating tooltip)", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="section-header-data"]').trigger("click");
      expect(wrapper.find(".node-desc").exists()).toBe(false);
      expect(wrapper.find(".node-desc-body").exists()).toBe(false);
    });

    it("dismisses the tooltip when a node button is clicked (add-node)", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="section-header-data"]').trigger("click");

      const button = wrapper.get('[data-testid="node-button-data.my_dataset"]');
      await button.trigger("mouseenter");
      expect(wrapper.find('[data-testid="node-hover-tooltip"]').exists()).toBe(true);

      await button.trigger("click");
      expect(wrapper.find('[data-testid="node-hover-tooltip"]').exists()).toBe(false);
    });
  });

  describe("toolbar collapse chevron", () => {
    it("renders the chevron pointing LEFT when expanded", async () => {
      const wrapper = await mountToolbar();
      const toggle = wrapper.get('[data-testid="toolbar-collapse-toggle"]');
      expect(toggle.find("i").classes()).toContain("pi-chevron-left");
    });

    it("collapses the toolbar on click and flips the chevron to point RIGHT", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="toolbar-collapse-toggle"]').trigger("click");
      await flushPromises();

      // The header/help/content are all hidden when collapsed.
      expect(wrapper.find(".toolbar-content").exists()).toBe(false);
      expect(wrapper.find(".toolbar-help").exists()).toBe(false);
      expect(wrapper.find("h3").exists()).toBe(false);

      // The chevron flips direction to hint "click to expand".
      const toggle = wrapper.get('[data-testid="toolbar-collapse-toggle"]');
      expect(toggle.find("i").classes()).toContain("pi-chevron-right");

      // Root carries the collapsed class for the parent grid to react to.
      expect(wrapper.classes()).toContain("collapsed");
    });

    it("emits toggle-collapsed events with the new state", async () => {
      const wrapper = await mountToolbar();
      // Initial emission on mount reports the starting (expanded) state.
      const initial = wrapper.emitted("toggle-collapsed");
      expect(initial).toBeTruthy();
      expect(initial?.[0]).toEqual([false]);

      await wrapper.get('[data-testid="toolbar-collapse-toggle"]').trigger("click");
      const events = wrapper.emitted("toggle-collapsed")!;
      expect(events.at(-1)).toEqual([true]);

      await wrapper.get('[data-testid="toolbar-collapse-toggle"]').trigger("click");
      expect(wrapper.emitted("toggle-collapsed")!.at(-1)).toEqual([false]);
    });

    it("persists the collapsed state across remounts via localStorage", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="toolbar-collapse-toggle"]').trigger("click");
      expect(localStorage.getItem("workflow-toolbar-collapsed")).toBe("1");
      wrapper.unmount();

      // Re-seed store for the fresh Pinia root and mount again.
      setActivePinia(createPinia());
      seedStore();
      const second = await mountToolbar();
      expect(second.classes()).toContain("collapsed");
      expect(second.find(".toolbar-content").exists()).toBe(false);
    });
  });

  describe("add-node wiring", () => {
    it("emits add-node with the correct node_type when a category button is clicked", async () => {
      const wrapper = await mountToolbar();
      await wrapper.get('[data-testid="section-header-preprocessing"]').trigger("click");
      await wrapper.get('[data-testid="node-button-preprocess.normalize"]').trigger("click");

      const events = wrapper.emitted("add-node");
      expect(events).toBeTruthy();
      expect(events?.[0]).toEqual(["preprocess.normalize"]);
    });
  });
});
