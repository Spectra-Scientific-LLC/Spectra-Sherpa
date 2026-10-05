import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";

import { useWorkflowStore } from "@/stores/workflow";
import type { TemplateStatus, WorkflowTemplate } from "@/stores/workflow-types";
import TemplateGallery from "@/views/workflow-builder/TemplateGallery.vue";

const template = (
  id: number,
  name: string,
  status: TemplateStatus,
  statusDetail: string | null,
): WorkflowTemplate => ({
  id,
  slug: name.toLowerCase().replace(/ /g, "-"),
  name,
  description: `${name} description`,
  category: "exploratory",
  status,
  status_detail: statusDetail,
  data_modalities: ["spectra"],
  template_data: {
    nodes: [],
    edges: [],
    status,
    ...(statusDetail === null ? {} : { status_detail: statusDetail }),
  },
  is_active: true,
  created_at: "2026-08-26T00:00:00Z",
  updated_at: "2026-08-26T00:00:00Z",
});

describe("TemplateGallery explicit qualification states", () => {
  it("shows the exact pending authority and disables only non-ready starters", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useWorkflowStore(pinia);
    store.templates = [
      template(1, "Qualified PCA", "ready", null),
      template(
        2,
        "Pending Calibration",
        "pending_qualification",
        "Representative end-to-end execution evidence is pending.",
      ),
    ];
    vi.spyOn(store, "fetchTemplates").mockResolvedValue(store.templates);

    const wrapper = mount(TemplateGallery, {
      global: {
        plugins: [pinia],
        stubs: {
          Button: {
            props: ["label", "disabled"],
            template: '<button :disabled="disabled">{{ label }}</button>',
          },
          Message: true,
          ProgressSpinner: true,
        },
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("ready");
    expect(wrapper.text()).toContain("pending qualification");
    expect(wrapper.text()).toContain("Representative end-to-end execution evidence is pending.");
    const cards = wrapper.findAll(".template-card");
    expect(cards[0].text()).toContain("Pending Calibration");
    expect(cards[0].get("button").attributes("disabled")).toBeDefined();
    expect(cards[1].text()).toContain("Qualified PCA");
    expect(cards[1].get("button").attributes("disabled")).toBeUndefined();
  });

  it("partitions every template for a selected dataset and names missing inputs", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useWorkflowStore(pinia);
    const pca = template(1, "PCA", "ready", null);
    const pls = template(2, "PLS Regression", "ready", null);
    const pending = template(
      3,
      "Pending SIMCA",
      "pending_qualification",
      "Scientific qualification is pending.",
    );
    store.templates = [pca, pls, pending];
    store.compatibilityMatrix = {
      schema_version: "spectra-sherpa-reference-template-matrix/1",
      dataset_count: 1,
      template_count: 3,
      pair_count: 3,
      datasets: [],
      matrix: [
        {
          dataset_id: "registered:target-free",
          template_slug: pca.slug,
          schema_version: "spectra-sherpa-dataset-template-compatibility/1",
          status: "compatible",
          display_group: "compatible",
          scope: "structural",
          compatible: true,
          can_use_as_primary: true,
          reason_codes: [],
          reasons: [],
          technique_recommended: true,
          advisory_codes: [],
          advisories: [],
        },
        {
          dataset_id: "registered:target-free",
          template_slug: pls.slug,
          schema_version: "spectra-sherpa-dataset-template-compatibility/1",
          status: "needs_input",
          display_group: "needs_target",
          scope: "structural",
          compatible: false,
          can_use_as_primary: true,
          reason_codes: ["continuous_target_missing"],
          reasons: [
            {
              code: "continuous_target_missing",
              message: "Requires a numeric target; this dataset has no target.",
              role: "Y_reference",
            },
          ],
          technique_recommended: true,
          advisory_codes: [],
          advisories: [],
        },
        {
          dataset_id: "registered:target-free",
          template_slug: pending.slug,
          schema_version: "spectra-sherpa-dataset-template-compatibility/1",
          status: "pending",
          display_group: "pending",
          scope: "structural",
          compatible: false,
          can_use_as_primary: true,
          reason_codes: ["template_pending_qualification"],
          reasons: [
            {
              code: "template_pending_qualification",
              message: "This analysis template is pending scientific qualification.",
              role: null,
            },
          ],
          technique_recommended: true,
          advisory_codes: [],
          advisories: [],
        },
      ],
    };
    vi.spyOn(store, "fetchTemplates").mockResolvedValue(store.templates);
    vi.spyOn(store, "fetchCompatibilityMatrix").mockResolvedValue(store.compatibilityMatrix);

    const wrapper = mount(TemplateGallery, {
      props: { selectedDatasetId: "registered:target-free" },
      global: {
        plugins: [pinia],
        stubs: {
          Button: {
            props: ["label", "disabled"],
            template: '<button :disabled="disabled">{{ label }}</button>',
          },
          Message: true,
          ProgressSpinner: true,
        },
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Available");
    expect(wrapper.text()).toContain("Needs target or class labels");
    expect(wrapper.text()).toContain("Scientific sufficiency is checked when the workflow runs.");
    expect(wrapper.text()).toContain("Pending qualification");
    expect(wrapper.text()).toContain("Requires a numeric target; this dataset has no target.");
    const cards = wrapper.findAll(".template-card");
    expect(
      cards
        .find((card) => card.text().includes("PCA"))!
        .get("button")
        .attributes("disabled"),
    ).toBeUndefined();
    expect(
      cards
        .find((card) => card.text().includes("PLS Regression"))!
        .get("button")
        .attributes("disabled"),
    ).toBeDefined();
    expect(
      cards
        .find((card) => card.text().includes("Pending SIMCA"))!
        .get("button")
        .attributes("disabled"),
    ).toBeDefined();
  });
});
