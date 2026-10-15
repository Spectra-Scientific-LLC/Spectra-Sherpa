import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TemplatePickerDialog from "@/components/TemplatePickerDialog.vue";
import type { DataSelectionReceipt } from "@/utils/workflowDataSelection";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  openTemplateAsSheet: vi.fn(),
  toastAdd: vi.fn(),
  workflowNodes: [] as Array<Record<string, unknown>>,
  routerPush: vi.fn(),
  optimization: false,
}));

vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({
  appConfig: { value: { features: { managedCampaigns: mocks.optimization } } },
}) }));
vi.mock("@/composables/usePrimaryNavigation", () => ({ usePrimaryNavigation: () => ({
  items: { value: mocks.optimization ? [{ label: "Optimize", to: "/contributed-destination" }] : [] },
}) }));

vi.mock("@/api", () => ({ api: { get: mocks.apiGet, post: mocks.apiPost } }));
vi.mock("@/stores/workbook", () => ({
  useWorkbookStore: () => ({ projectId: 7, openTemplateAsSheet: mocks.openTemplateAsSheet }),
}));
vi.mock("@/stores/workflow", () => ({
  useWorkflowStore: () => ({ nodes: mocks.workflowNodes }),
}));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: mocks.toastAdd }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.routerPush }) }));
vi.mock("primevue/dialog", () => ({
  default: defineComponent({
    name: "DialogStub",
    props: { visible: Boolean },
    template: "<section v-if='visible'><slot /><slot name='footer' /></section>",
  }),
}));
vi.mock("primevue/button", () => ({
  default: defineComponent({
    name: "PrimeButton",
    props: { label: String, disabled: Boolean, title: String },
    emits: ["click"],
    template:
      "<button :disabled='disabled' :title='title' @click='$emit(`click`)'>{{ label }}</button>",
  }),
}));

const role = (targetType: "continuous" | "categorical") => ({
  nodes: [{ node_id: "data_1", node_type: "data.collection_load", parameters: {} }],
  data_roles: {
    X_spectra: {
      role_type: "X_spectra",
      node_binding: "data_1",
      required: true,
      binding_mode: "embedded",
    },
    target: {
      role_type: targetType === "categorical" ? "class_labels" : "Y_reference",
      node_binding: "data_1",
      required: true,
      binding_mode: "embedded",
      target_type: targetType,
    },
  },
});

describe("TemplatePickerDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.optimization = false;
    mocks.workflowNodes = [];
    mocks.apiPost.mockResolvedValue({ data: null });
  });

  it("discloses unavailable provider examples and never launches one", async () => {
    mocks.apiGet.mockResolvedValue({ data: { total: 1, templates: [{
      id: 22, slug: "pls_calibration", name: "PLS Calibration", description: "Held-out calibration",
      category: "calibration", status: "ready", status_detail: null, is_active: true,
      example_unavailable_reason: "Provider example import is unavailable. Select an uploaded My Dataset instead.",
      template_data: { nodes: [{ node_id: "data_1", node_type: "data.file_load", parameters: {},
        example_binding: { source: "eigenvector", dataset_name: "corn_m5" } }] },
    }] } });
    const wrapper = mount(TemplatePickerDialog, { props: { visible: false } });
    await wrapper.setProps({ visible: true });
    await flushPromises();
    expect(wrapper.text()).toContain("Select an uploaded My Dataset instead");
    expect(wrapper.text()).not.toContain("Use Bundled Example");
    const launch = wrapper.findAll("button").find((button) => button.text() === "Needs data");
    expect(launch?.attributes("disabled")).toBeDefined();
    expect(mocks.openTemplateAsSheet).not.toHaveBeenCalled();
  });

  it("auto-starts the Dashboard-selected compatible starter with current data", async () => {
    mocks.openTemplateAsSheet.mockResolvedValue({ name: "PCA" });
    mocks.apiGet.mockResolvedValue({
      data: {
        templates: [
          {
            id: 1,
            slug: "pca",
            name: "PCA",
            description: "Principal component analysis",
            category: "exploratory",
            status: "ready",
            status_detail: null,
            is_active: true,
            template_data: {
              nodes: [{ node_id: "data_1", node_type: "data.collection_load", parameters: {} }],
              data_roles: {
                X_spectra: {
                  role_type: "X_spectra",
                  node_binding: "data_1",
                  required: true,
                  binding_mode: "embedded",
                },
              },
            },
          },
        ],
        total: 1,
      },
    });
    const receipt: DataSelectionReceipt = {
      schema_version: "spectra-my-dataset-workflow-selection/3",
      receipt_id: "selection-test-1",
      project_id: 7,
      datasets: [
        {
          experiment_id: 12,
          dataset_name: "Lavender",
          selection: "subset",
          selected_file_count: 3,
          file_ids: [1, 2, 3],
          stage: "raw",
        },
      ],
      target_authority: null,
      group: null,
      analysis_readiness_experiment_id: 12,
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "FTIR",
          target_type: null,
          target_fields: [],
          identity_fields: [],
          group_fields: [],
          ordered_samples: false,
        },
        template_count: 1,
        counts: {
          compatible: 1,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [
          {
            template_slug: "pca",
            template_name: "PCA",
            category: "exploratory",
            display_status: "compatible",
            status: "compatible",
            reason_codes: [],
            reasons: [],
          },
        ],
        diagnostics: [],
      },
    };

    const wrapper = mount(TemplatePickerDialog, {
      props: { visible: false, dataSelection: receipt, preferredTemplateSlug: "pca" },
    });
    await wrapper.setProps({ visible: true });
    await flushPromises();

    expect(mocks.openTemplateAsSheet).toHaveBeenCalledWith(1, "PCA", {
      launchMode: "user",
      dataBindings: {
        data_1: expect.objectContaining({
          experimentId: 12,
          fileIds: [1, 2, 3],
          allFiles: false,
        }),
      },
    });
    expect(wrapper.emitted("sheet-opened")).toHaveLength(1);
  });

  it.each([false, true])("discloses two-view follow-up with optimization capability %s", async (optimization) => {
    mocks.optimization = optimization;
    mocks.openTemplateAsSheet.mockResolvedValue({ name: "PLS Regression Calibration" });
    mocks.apiGet.mockResolvedValue({
      data: {
        templates: [
          {
            id: 11,
            slug: "pls_calibration",
            name: "PLS Regression Calibration",
            description: "Corn calibration",
            category: "calibration",
            status: "ready",
            status_detail: null,
            is_active: true,
            template_data: { ...role("continuous"), canonical_project: { schema_version: "test" } },
          },
        ],
        total: 1,
      },
    });
    const receipt: DataSelectionReceipt = {
      schema_version: "spectra-my-dataset-workflow-selection/3",
      receipt_id: "selection-test-2",
      project_id: 7,
      datasets: [
        {
          experiment_id: 12,
          dataset_name: "Corn",
          selection: "subset",
          selected_file_count: 2,
          file_ids: [51, 52],
          stage: "raw",
        },
      ],
      target_authority: null,
      group: null,
      analysis_readiness_experiment_id: 12,
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "NIR",
          target_type: "continuous",
          target_fields: ["Moisture"],
          identity_fields: ["sample_id"],
          group_fields: ["instrument"],
          ordered_samples: false,
        },
        template_count: 1,
        counts: {
          compatible: 1,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [
          {
            template_slug: "pls_calibration",
            template_name: "PLS Regression Calibration",
            category: "calibration",
            display_status: "compatible",
            status: "compatible",
            reason_codes: [],
            reasons: [],
          },
        ],
        diagnostics: [],
      },
    };

    const wrapper = mount(TemplatePickerDialog, {
      props: { visible: false, dataSelection: receipt },
    });
    await wrapper.setProps({ visible: true });
    await flushPromises();
    expect(wrapper.text()).toContain(
      "No companion workflow is required.",
    );
    expect(wrapper.text().includes("choose Optimize")).toBe(optimization);
    if (!optimization) expect(wrapper.text()).toContain("compare them manually in Runs");

    await wrapper.get(".tp-row button").trigger("click");
    await flushPromises();
    expect(mocks.openTemplateAsSheet).toHaveBeenCalled();
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "info",
        summary: "Analysis started",
        detail: expect.stringContaining(optimization ? "After a successful run, choose Optimize" : "compare them manually in Runs"),
      }),
    );
  });

  it("offers current data only to starters approved by the server preview", async () => {
    mocks.apiGet.mockResolvedValue({
      data: {
        templates: [
          {
            id: 1,
            slug: "classification-plsda",
            name: "Classification (PLS-DA)",
            description: "Categorical analysis",
            category: "classification",
            status: "ready",
            status_detail: null,
            is_active: true,
            template_data: {
              ...role("categorical"),
              nodes: [
                {
                  node_id: "data_1",
                  node_type: "data.file_load",
                  parameters: {},
                  example_binding: { source: "sklearn", dataset_name: "wine" },
                },
              ],
            },
          },
          {
            id: 2,
            slug: "pls-regression",
            name: "PLS Regression",
            description: "Quantitative analysis",
            category: "calibration",
            status: "ready",
            status_detail: null,
            is_active: true,
            template_data: role("continuous"),
          },
        ],
        total: 2,
      },
    });
    const receipt: DataSelectionReceipt = {
      schema_version: "spectra-my-dataset-workflow-selection/3",
      receipt_id: "selection-test-3",
      project_id: 7,
      datasets: [
        {
          experiment_id: 12,
          dataset_name: "Lavender",
          selection: "subset",
          selected_file_count: 3,
          file_ids: [1, 2, 3],
          stage: "raw",
        },
      ],
      target_authority: {
        schema_version: "spectrasherpa-target-authority/1",
        column: "species",
        target_type: "categorical",
        units: null,
        source_digest: "a".repeat(64),
      },
      group: "block",
      analysis_readiness_experiment_id: 12,
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "IR",
          target_type: "categorical",
          target_fields: ["species"],
          identity_fields: ["sample_id"],
          group_fields: ["block"],
          ordered_samples: false,
        },
        template_count: 2,
        counts: {
          compatible: 1,
          needs_target: 1,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [
          {
            template_slug: "classification-plsda",
            template_name: "Classification (PLS-DA)",
            category: "classification",
            display_status: "compatible",
            status: "compatible",
            reason_codes: [],
            reasons: [],
          },
          {
            template_slug: "pls-regression",
            template_name: "PLS Regression",
            category: "calibration",
            display_status: "needs_target",
            status: "needs_input",
            reason_codes: ["continuous_target_missing"],
            reasons: [
              {
                code: "continuous_target_missing",
                message: "Requires a numeric target; the selected target is categorical.",
                role: "target",
              },
            ],
          },
        ],
        diagnostics: [],
      },
    };

    const wrapper = mount(TemplatePickerDialog, {
      props: { visible: false, dataSelection: receipt },
    });
    await wrapper.setProps({ visible: true });
    await flushPromises();

    const rows = wrapper.findAll(".tp-row");
    const classification = rows.find((row) => row.text().includes("Classification (PLS-DA)"));
    const regression = rows.find((row) => row.text().includes("PLS Regression"));
    expect(classification?.text()).toContain("Use Current Data");
    expect(rows[0].text()).toContain("Classification (PLS-DA)");
    expect(rows[rows.length - 1].text()).toContain("PLS Regression");
    expect(wrapper.findAll(".tp-group-title").map((heading) => heading.text())).toEqual([
      "Classification (1)", "Not Available for Current Dataset (1)",
    ]);
    expect(classification?.text()).not.toContain("Use Bundled Example");
    expect(classification?.text()).not.toContain("Example source: wine (sklearn)");
    expect(regression?.find(".tp-row-description").exists()).toBe(false);
    expect(regression?.find("[role=tooltip]").text()).toContain("Requires a numeric target");
    expect(regression?.text()).toContain("Requires a numeric target");
    expect(regression?.text()).not.toContain("Use Current Data");
  });

  it("preflights an active sheet source before offering Use Current Data", async () => {
    mocks.workflowNodes = [
      {
        id: "data_1",
        type: "data.file_load",
        params: { experiment_id: 8, file_id: 9, stage: "raw" },
      },
    ];
    mocks.apiGet.mockResolvedValue({
      data: {
        templates: [
          {
            id: 2,
            slug: "pls-regression",
            name: "PLS Regression",
            description: "Quantitative analysis",
            category: "calibration",
            status: "ready",
            status_detail: null,
            is_active: true,
            template_data: role("continuous"),
          },
        ],
        total: 1,
      },
    });
    mocks.apiPost.mockResolvedValueOnce({
      data: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "needs_input",
        profile: {
          primary_role: "X_features",
          modality: "features",
          technique: "ML/Statistics",
          target_type: null,
          target_fields: [],
          identity_fields: [],
          group_fields: [],
          ordered_samples: false,
        },
        template_count: 1,
        counts: {
          compatible: 0,
          needs_target: 1,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [
          {
            template_slug: "pls-regression",
            template_name: "PLS Regression",
            category: "calibration",
            display_status: "needs_target",
            status: "needs_input",
            reason_codes: ["continuous_target_missing"],
            reasons: [
              {
                code: "continuous_target_missing",
                message: "Requires a numeric target.",
                role: "target",
              },
            ],
          },
        ],
        diagnostics: [],
      },
    });

    const wrapper = mount(TemplatePickerDialog, { props: { visible: false } });
    await wrapper.setProps({ visible: true });
    await flushPromises();

    expect(mocks.apiPost).toHaveBeenCalledWith(
      "/workflow-templates/binding-compatibility-preview",
      expect.objectContaining({
        project_id: 7,
        binding: expect.objectContaining({ experiment_id: 8, file_id: 9 }),
      }),
    );
    expect(wrapper.text()).toContain("Requires a numeric target");
    expect(wrapper.findAll(".tp-row button")).toHaveLength(0);
    expect(wrapper.get(".tp-unavailable-status").text()).toBe("Not Available for Current Dataset");
    expect(mocks.routerPush).not.toHaveBeenCalled();
  });

  it("uses the verified project dataset instead of a stale active sheet source", async () => {
    mocks.workflowNodes = [{
      id: "data_1",
      type: "data.file_load",
      params: { experiment_id: 8, file_id: 10, stage: "raw" }, // MP5 on the old sheet
    }];
    const projectDataset = {
      id: 42,
      name: "Corn MP6 · Moisture",
      digest: "a".repeat(64),
      definition: {
        experiment_id: 8,
        stage: "raw",
        selected_file_ids: [11], // MP6 selected in My Dataset
        asset_id: null,
        target_authority: {
          schema_version: "spectrasherpa-target-authority/1",
          column: "Moisture",
          target_type: "continuous",
          units: null,
          source_digest: "b".repeat(64),
        },
        group_column: null,
      },
    };
    mocks.apiGet.mockImplementation(async (url: string) => url.includes("current-dataset")
      ? { data: { dataset: projectDataset } }
      : { data: { templates: [{
          id: 2, slug: "pls-regression", name: "PLS Regression", description: "Quantitative analysis",
          category: "calibration", status: "ready", status_detail: null, is_active: true,
          template_data: role("continuous"),
        }], total: 1 } });
    const savedAuthority = { ...projectDataset.definition.target_authority, column: "Protein", units: "%" };
    mocks.apiPost.mockResolvedValue({ data: { binding: {
      target_authority: savedAuthority, group_column: "specimen_id",
    }, decisions: [{
      template_slug: "pls-regression", status: "compatible", reason_codes: [], reasons: [],
    }] } });
    mocks.openTemplateAsSheet.mockResolvedValue({ name: "PLS Regression" });

    const wrapper = mount(TemplatePickerDialog, { props: { visible: false } });
    await wrapper.setProps({ visible: true });
    await flushPromises();

    expect(wrapper.text()).toContain("Project dataset: Corn MP6 · Moisture");
    expect(mocks.apiPost).toHaveBeenCalledWith(
      "/workflow-templates/binding-compatibility-preview",
      expect.objectContaining({ use_saved_analysis_selection: true, binding: expect.objectContaining({ file_ids: [11] }) }),
    );
    const button = wrapper.findAll("button").find((candidate) => candidate.text() === "Use Project Dataset");
    expect(button).toBeDefined();
    await button!.trigger("click");
    await flushPromises();
    expect(mocks.openTemplateAsSheet).toHaveBeenCalledWith(2, "PLS Regression", {
      launchMode: "user",
      dataBindings: { data_1: expect.objectContaining({
        experimentId: 8, fileIds: [11], allFiles: false,
        targetAuthority: savedAuthority, groupColumn: "specimen_id",
      }) },
    });
  });

  it("previews and launches the exact selected asset from a generic multi-asset import", async () => {
    const assetId = "scientific-asset-2";
    mocks.apiGet.mockImplementation(async (url: string) => url.includes("current-dataset")
      ? { data: { dataset: {
          id: 43, name: "Selected imported asset", digest: "a".repeat(64),
          definition: {
            experiment_id: 8, stage: "raw", selected_file_ids: [12], asset_id: assetId,
            target_authority: null, group_column: null,
          },
        } } }
      : { data: { templates: [{
          id: 2, slug: "pls-regression", name: "PLS Regression", description: "Quantitative analysis",
          category: "calibration", status: "ready", status_detail: null, is_active: true,
          template_data: role("continuous"),
        }], total: 1 } });
    mocks.apiPost.mockImplementation(async (_url: string, payload: { binding: { asset_id: string | null } }) => ({
      data: { binding: { target_authority: null, group_column: null }, decisions: [{
        template_slug: "pls-regression",
        status: payload.binding.asset_id === assetId ? "compatible" : "needs_input",
        reason_codes: [], reasons: [],
      }] },
    }));
    mocks.openTemplateAsSheet.mockResolvedValue({ name: "PLS Regression" });

    const wrapper = mount(TemplatePickerDialog, { props: { visible: false } });
    await wrapper.setProps({ visible: true });
    await flushPromises();
    expect(mocks.apiPost).toHaveBeenCalledWith(
      "/workflow-templates/binding-compatibility-preview",
      expect.objectContaining({ binding: expect.objectContaining({ asset_id: assetId }) }),
    );
    const button = wrapper.findAll("button").find((candidate) => candidate.text() === "Use Project Dataset");
    expect(button?.attributes("disabled")).toBeUndefined();
    await button!.trigger("click");
    await flushPromises();
    expect(mocks.openTemplateAsSheet).toHaveBeenCalledWith(2, "PLS Regression", {
      launchMode: "user",
      dataBindings: { data_1: expect.objectContaining({ experimentId: 8, fileIds: [12], assetId }) },
    });
  });

  it.each(["Active project dataset is no longer exact", "Dataset service unavailable"])(
    "fails closed without offering alternate data when the project choice fails: %s",
    async (reason) => {
    mocks.workflowNodes = [{
      id: "data_1", type: "data.file_load", params: { experiment_id: 8, file_id: 10, stage: "raw" },
    }];
    mocks.apiGet.mockImplementation(async (url: string) => {
      if (url.includes("current-dataset")) throw new Error(reason);
      return { data: { templates: [{
        id: 2, slug: "pls-regression", name: "PLS Regression", description: "Quantitative analysis",
        category: "calibration", status: "ready", status_detail: null, is_active: true,
        template_data: {
          ...role("continuous"),
          nodes: [{ node_id: "data_1", node_type: "data.file_load", parameters: {},
            example_binding: { source: "sklearn", dataset_name: "diabetes" } }],
        },
      }], total: 1 } };
    });
    mocks.openTemplateAsSheet.mockResolvedValue({ name: "PLS Regression" });

    const wrapper = mount(TemplatePickerDialog, {
      props: { visible: false, preferredTemplateSlug: "pls-regression" },
    });
    await wrapper.setProps({ visible: true });
    await flushPromises();
    expect(wrapper.text()).toContain("PLS Regression");
    expect(wrapper.text()).toContain("Project dataset selection could not be verified");
    expect(wrapper.text()).not.toContain("Failed to load analysis starters");
    expect(wrapper.get(".tp-unavailable-status").text()).toBe("Not Available for Current Dataset");
    expect(wrapper.findAll(".tp-row button")).toHaveLength(0);
    expect(mocks.apiPost).not.toHaveBeenCalledWith("/workflow-templates/binding-compatibility-preview", expect.anything());
    expect(mocks.openTemplateAsSheet).not.toHaveBeenCalled();
  });

  it("refreshes stale readiness before offering the selected dataset", async () => {
    mocks.apiGet.mockResolvedValue({
      data: {
        templates: [
          {
            id: 3,
            slug: "raman_processing",
            name: "Raman Processing Pipeline",
            description: "Raman preprocessing",
            category: "spectroscopy",
            status: "ready",
            status_detail: null,
            is_active: true,
            template_data: {
              nodes: [{ node_id: "data_1", node_type: "data.file_load", parameters: {} }],
              data_roles: {
                X_spectra: {
                  role_type: "X_spectra",
                  node_binding: "data_1",
                  required: true,
                  binding_mode: "embedded",
                  accepted_techniques: ["Raman"],
                  technique_match: "required",
                },
              },
            },
          },
        ],
        total: 1,
      },
    });
    const receipt: DataSelectionReceipt = {
      schema_version: "spectra-my-dataset-workflow-selection/3",
      receipt_id: "selection-test-4",
      project_id: 7,
      datasets: [
        {
          experiment_id: 12,
          dataset_name: "Atmospheric FTIR",
          selection: "all",
          selected_file_count: 50,
          file_ids: null,
          stage: "synthetic",
        },
      ],
      target_authority: null,
      group: null,
      analysis_readiness_experiment_id: 12,
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "FTIR",
          target_type: null,
          target_fields: [],
          identity_fields: [],
          group_fields: [],
          ordered_samples: false,
        },
        template_count: 1,
        counts: {
          compatible: 1,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [
          {
            template_slug: "raman_processing",
            template_name: "Raman Processing Pipeline",
            category: "spectroscopy",
            display_status: "compatible",
            status: "compatible",
            reason_codes: [],
            reasons: [],
          },
        ],
        diagnostics: [],
      },
    };
    mocks.apiPost.mockResolvedValue({
      data: {
        ...receipt.analysis_readiness,
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 0,
          incompatible: 1,
          pending: 0,
          unavailable: 0,
        },
        decisions: [
          {
            template_slug: "raman_processing",
            template_name: "Raman Processing Pipeline",
            category: "spectroscopy",
            display_status: "incompatible",
            status: "incompatible",
            reason_codes: ["technique_incompatible"],
            reasons: [
              {
                code: "technique_incompatible",
                message: "Requires Raman data; the dataset technique is FTIR.",
                role: null,
              },
            ],
          },
        ],
      },
    });

    const wrapper = mount(TemplatePickerDialog, {
      props: { visible: false, dataSelection: receipt },
    });
    await wrapper.setProps({ visible: true });
    await flushPromises();

    expect(mocks.apiPost).toHaveBeenCalledWith("/workflow-templates/compatibility-preview", {
      analysis_profile: receipt.analysis_readiness?.profile,
    });
    expect(wrapper.text()).toContain("Requires Raman data; the dataset technique is FTIR.");
    expect(wrapper.text()).toContain("Not Available for Current Dataset");
    expect(wrapper.text()).not.toContain("Use Current Data");
  });

  it("shows incompatible starters as compact unavailable rows without alternate data actions", async () => {
    const templateData = role("continuous");
    templateData.nodes = [
      {
        node_id: "data_1",
        node_type: "data.file_load",
        parameters: {},
        example_binding: { source: "sklearn", dataset_name: "diabetes" },
      },
    ];
    mocks.apiGet.mockResolvedValue({
      data: {
        templates: [
          {
            id: 2,
            slug: "pls-regression",
            name: "PLS Regression",
            description: "Quantitative analysis",
            category: "calibration",
            status: "ready",
            status_detail: null,
            is_active: true,
            template_data: templateData,
          },
        ],
        total: 1,
      },
    });
    const receipt: DataSelectionReceipt = {
      schema_version: "spectra-my-dataset-workflow-selection/3",
      receipt_id: "selection-test-5",
      project_id: 7,
      datasets: [
        {
          experiment_id: 12,
          dataset_name: "Lavender",
          selection: "subset",
          selected_file_count: 3,
          file_ids: [1, 2, 3],
          stage: "raw",
        },
      ],
      target_authority: {
        schema_version: "spectrasherpa-target-authority/1",
        column: "species",
        target_type: "categorical",
        units: null,
        source_digest: "a".repeat(64),
      },
      group: null,
      analysis_readiness_experiment_id: 12,
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "IR",
          target_type: "categorical",
          target_fields: ["species"],
          identity_fields: ["sample_id"],
          group_fields: [],
          ordered_samples: false,
        },
        template_count: 1,
        counts: {
          compatible: 0,
          needs_target: 1,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [
          {
            template_slug: "pls-regression",
            template_name: "PLS Regression",
            category: "calibration",
            display_status: "needs_target",
            status: "needs_input",
            reason_codes: ["continuous_target_missing"],
            reasons: [
              {
                code: "continuous_target_missing",
                message: "Requires a numeric target; the selected target is categorical.",
                role: "target",
              },
            ],
          },
        ],
        diagnostics: [],
      },
    };

    const wrapper = mount(TemplatePickerDialog, {
      props: { visible: false, dataSelection: receipt },
    });
    await wrapper.setProps({ visible: true });
    await flushPromises();

    expect(wrapper.findAll(".tp-row button")).toHaveLength(0);
    expect(wrapper.get(".tp-unavailable-status").text()).toBe("Not Available for Current Dataset");
    expect(wrapper.get("[role=tooltip]").text()).toContain("Requires a numeric target");
    expect(wrapper.find(".tp-row-description").exists()).toBe(false);
    expect(mocks.openTemplateAsSheet).not.toHaveBeenCalled();
  });

  it("does not advertise a starter whose runtime dependency is unavailable", async () => {
    mocks.apiGet.mockResolvedValue({
      data: {
        templates: [
          {
            id: 7,
            slug: "mcr_als",
            name: "MCR-ALS Curve Resolution",
            description: "Resolve mixture components.",
            category: "curve_resolution",
            status: "ready",
            status_detail: null,
            runtime_readiness: {
              ready: false,
              blockers: ["spectrochempy_unavailable"],
              remediation: ["Install the optional SpectroChemPy support."],
              unavailable_nodes: [
                {
                  node_id: "model_1",
                  node_type: "model.mcr_als",
                  blockers: ["spectrochempy_unavailable"],
                },
              ],
            },
            is_active: true,
            template_data: {
              nodes: [{ node_id: "data_1", node_type: "data.collection_load", parameters: {} }],
              data_roles: {
                X_spectra: {
                  role_type: "X_spectra",
                  node_binding: "data_1",
                  required: true,
                  binding_mode: "embedded",
                },
              },
            },
          },
        ],
        total: 1,
      },
    });

    const wrapper = mount(TemplatePickerDialog, {
      props: { visible: false, dataSelection: null },
    });
    await wrapper.setProps({ visible: true });
    await flushPromises();

    const row = wrapper.get(".tp-row");
    expect(row.text()).toContain("unavailable");
    const button = row.get("button");
    expect(button.text()).toBe("Unavailable");
    expect(button.attributes("disabled")).toBeDefined();
    expect(button.attributes("title")).toContain("model.mcr_als");
    await button.trigger("click");
    expect(mocks.openTemplateAsSheet).not.toHaveBeenCalled();
  });

  it("maps exactly two selected data views to a two-source starter without guessing", async () => {
    mocks.openTemplateAsSheet.mockResolvedValue({ name: "Calibration Transfer" });
    mocks.apiGet.mockResolvedValue({
      data: {
        templates: [
          {
            id: 3,
            slug: "calibration_transfer",
            name: "Calibration Transfer",
            description: "Compare two explicitly paired instrument views.",
            category: "preprocessing",
            status: "ready",
            status_detail: null,
            is_active: true,
            template_data: {
              nodes: [
                {
                  node_id: "primary_1",
                  node_type: "data.file_load",
                  label: "Primary-Instrument Standards",
                  parameters: {},
                },
                {
                  node_id: "secondary_1",
                  node_type: "data.file_load",
                  label: "Secondary-Instrument Standards",
                  parameters: {},
                },
              ],
              data_roles: {
                X_primary: {
                  role_type: "X_spectra",
                  node_binding: "primary_1",
                  required: true,
                  binding_mode: "embedded",
                },
                X_secondary: {
                  role_type: "X_spectra",
                  node_binding: "secondary_1",
                  required: true,
                  binding_mode: "embedded",
                },
              },
            },
          },
        ],
        total: 1,
      },
    });
    const receipt: DataSelectionReceipt = {
      schema_version: "spectra-my-dataset-workflow-selection/3",
      receipt_id: "selection-test-6",
      project_id: 7,
      datasets: [
        {
          experiment_id: 12,
          dataset_name: "Eigenvector Corn",
          selection: "subset",
          selected_file_count: 2,
          file_ids: [51, 52],
          file_paths: ["raw/corn-m5.mat", "raw/corn-mp5.mat"],
          stage: "raw",
        },
      ],
      target_authority: null,
      group: null,
      analysis_readiness_experiment_id: 12,
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "NIR",
          target_type: "continuous",
          target_fields: ["Moisture", "Oil", "Protein", "Starch"],
          identity_fields: ["sample_id", "specimen_id"],
          group_fields: ["specimen_id"],
          ordered_samples: false,
        },
        template_count: 1,
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 1,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [
          {
            template_slug: "calibration_transfer",
            template_name: "Calibration Transfer",
            category: "preprocessing",
            display_status: "needs_source",
            status: "needs_input",
            reason_codes: ["additional_data_source_required"],
            reasons: [
              {
                code: "additional_data_source_required",
                message: "Requires an additional X_spectra data source.",
                role: "X_secondary",
              },
            ],
          },
        ],
        diagnostics: [],
      },
    };

    const wrapper = mount(TemplatePickerDialog, {
      props: { visible: false, dataSelection: receipt },
    });
    await wrapper.setProps({ visible: true });
    await flushPromises();

    expect(wrapper.text()).toContain(
      "corn-m5.mat → Primary-Instrument Standards; corn-mp5.mat → Secondary-Instrument Standards",
    );
    const button = wrapper.get(".tp-row button");
    expect(button.text()).toBe("Use Current Data");
    await button.trigger("click");
    await flushPromises();

    expect(mocks.openTemplateAsSheet).toHaveBeenLastCalledWith(3, "Calibration Transfer", {
      launchMode: "user",
      dataBindings: {
        primary_1: expect.objectContaining({
          experimentId: 12,
          fileIds: [51],
          allFiles: false,
        }),
        secondary_1: expect.objectContaining({
          experimentId: 12,
          fileIds: [52],
          allFiles: false,
        }),
      },
    });
  });
});
