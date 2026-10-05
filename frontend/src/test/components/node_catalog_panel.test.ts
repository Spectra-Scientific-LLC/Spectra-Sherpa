import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { NodeTypeMetadata } from "@/types";
import NodeCatalogPanel from "@/views/workflow-builder/NodeCatalogPanel.vue";

const contract = (lifecycle: string, task: string, overrides: Record<string, unknown> = {}) => ({
  digest: "a".repeat(64),
  payload: {
    runtime_family: "sherpa_native",
    lifecycle_kind: lifecycle,
    supervised_task: task,
    target_access: task === "none" ? "none" : "fit_only",
    group_access: "none",
    sample_effect: "preserves_samples",
    feature_effect: "generates_features",
    axis_effect: "changes_axis",
    unit_effect: "changes_units",
    input_rank_policy: "matrix_2d",
    deterministic: true,
    seed_parameter: null,
    fitted_state_serializer: lifecycle.startsWith("fitted") ? "spectra-state/1" : null,
    implementation_id: `spectrasherpa.test.${lifecycle}`,
    implementation_version: "1.0.0",
    implementation_digest: "b".repeat(64),
    help_reference: "docs/nodes/test.md",
    citations: ["Example scientific citation"],
    runtime_requirements: [],
    ...overrides,
  },
});

const node = (
  nodeType: string,
  label: string,
  category: string,
  lifecycle: string,
  task: string,
  managed: boolean,
  requiresScp = false,
): NodeTypeMetadata => ({
  node_type: nodeType,
  label,
  category,
  description: `${label} scientific purpose.`,
  parameters: [
    {
      name: "components",
      label: "Components",
      param_type: "number",
      default: 3,
      min_value: 1,
      max_value: 10,
      description: "Number of retained components.",
      required: true,
    },
    {
      name: "artifact_digest",
      label: "Artifact Digest",
      param_type: "text",
      required: false,
      category: "internal",
    },
  ],
  input_types: ["SherpaDataset"],
  output_type: "SherpaDataset",
  input_ports: [
    {
      name: "X",
      type_ref: "spectrasherpa://types/Array2D/1.0",
      required: true,
      label: "Spectra",
    },
  ],
  output_ports: [
    {
      name: "default",
      type_ref: "spectrasherpa://types/ScoreMatrix/1.0",
      required: true,
      label: "Scores",
    },
  ],
  execution_contract: contract(
    lifecycle,
    task,
    requiresScp
      ? {
          runtime_requirements: [{ distribution: "spectrochempy", version: "0.8.1" }],
        }
      : {},
  ),
  dependency_readiness: requiresScp
    ? {
        ready: false,
        blockers: ["spectrochempy_unavailable"],
        remediation: [
          "Install the optional SpectroChemPy support: pip install 'spectra-sherpa[scp]'.",
        ],
      }
    : { ready: true, blockers: [], remediation: [] },
  requires_scp: requiresScp,
  catalog_classification: {
    contract_status: "contracted",
    runtime_family: "sherpa_native",
    lifecycle_kind: lifecycle,
    typed_port_status: "typed_input_output",
    managed_optimization_eligible: managed,
    reason: managed
      ? "managed_optimization_profile_exact_contract"
      : "outside_managed_optimization_profile",
  },
  managed_optimization_profile: {
    profile_id: "spectra-managed-optimization-profile",
    profile_version: "7",
    profile_digest: "c".repeat(64),
    eligible: managed,
    reason: managed
      ? "managed_optimization_profile_exact_contract"
      : "outside_managed_optimization_profile",
  },
});

const nodes = [
  node("data.file_load", "File Load", "data", "data_source", "none", false),
  node("model.pca", "Principal Component Analysis", "exploratory", "fitted_model", "none", true),
  node("classification.plsda", "PLS-DA", "classification", "fitted_model", "classification", true),
  node(
    "classification.apply_plsda",
    "Apply PLS-DA",
    "classification",
    "artifact_application",
    "classification",
    false,
  ),
  node(
    "model.efa",
    "Evolving Factor Analysis",
    "exploratory",
    "stateless_transform",
    "none",
    false,
    true,
  ),
];

const mountPanel = () =>
  mount(NodeCatalogPanel, {
    props: {
      nodes,
      addableNodeTypes: nodes
        .filter((item) => item.node_type !== "data.file_load")
        .map((item) => item.node_type),
    },
  });

describe("NodeCatalogPanel", () => {
  it("uses the same scientist-facing family names and order as the Add panel", () => {
    const wrapper = mountPanel();
    const options = wrapper
      .get('[data-testid="catalog-family-filter"]')
      .findAll("option")
      .map((option) => option.text());

    expect(options).toEqual([
      "All families",
      "Data",
      "Exploration & Decomposition",
      "Classification",
    ]);
    expect(wrapper.get('[data-testid="catalog-node-model.pca"]').text()).toContain(
      "Exploration & Decomposition",
    );
    expect(wrapper.findAll(".catalog-family-heading").map((heading) => heading.text())).toEqual([
      "Data1",
      "Exploration & Decomposition2",
      "Classification2",
    ]);
  });

  it("shows the complete registry while keeping source-bound operations inspectable but not addable", () => {
    const wrapper = mountPanel();
    expect(wrapper.findAll(".catalog-card")).toHaveLength(5);
    expect(wrapper.get('[data-testid="catalog-node-data.file_load"]').text()).toContain(
      "Starter/source bound",
    );
    expect(wrapper.find('[data-testid="catalog-add-data.file_load"]').exists()).toBe(false);
  });

  it("combines text, family, lifecycle, task, managed, application, and runtime filters", async () => {
    const wrapper = mountPanel();

    await wrapper.get('[data-testid="catalog-family-filter"]').setValue("classification");
    expect(wrapper.findAll(".catalog-card")).toHaveLength(2);

    await wrapper.get('[data-testid="catalog-lifecycle-filter"]').setValue("artifact_application");
    expect(wrapper.findAll(".catalog-card")).toHaveLength(1);
    expect(wrapper.text()).toContain("Apply PLS-DA");

    await wrapper.get('[data-testid="catalog-reset"]').trigger("click");
    await wrapper.get('[data-testid="catalog-task-filter"]').setValue("classification");
    await wrapper.get('[data-testid="catalog-managed-filter"]').setValue("eligible");
    expect(wrapper.findAll(".catalog-card")).toHaveLength(1);
    expect(wrapper.text()).toContain("PLS-DA");

    await wrapper.get('[data-testid="catalog-reset"]').trigger("click");
    await wrapper.get('[data-testid="catalog-runtime-filter"]').setValue("optional");
    expect(wrapper.findAll(".catalog-card")).toHaveLength(1);
    expect(wrapper.text()).toContain("Evolving Factor Analysis");

    await wrapper.get('[data-testid="catalog-reset"]').trigger("click");
    await wrapper.get('[data-testid="catalog-text-filter"]').setValue("scientific citation");
    expect(wrapper.findAll(".catalog-card")).toHaveLength(5);
  });

  it("renders every required nested detail from canonical metadata", async () => {
    const wrapper = mountPanel();
    const card = wrapper.get('[data-testid="catalog-node-classification.plsda"]');
    await card.get("summary").trigger("click");

    const text = card.text();
    expect(text).toContain("Scientific purpose");
    expect(text).toContain("Parameters");
    expect(text).toContain("Typed ports");
    expect(text).toContain("Lifecycle, fitting, and preprocessing semantics");
    expect(text).toContain("Deterministic; no seed parameter");
    expect(text).toContain("Validation cautions");
    expect(text).toContain("Implementation and contract identity");
    expect(text).toContain("Managed optimization");
    expect(text).toContain("Optional runtime");
    expect(text).toContain("Citations");
    expect(text).toContain("Example scientific citation");
    expect(text).toContain("Performance claims require an explicit held-out validation plan");
    expect(text).not.toContain("Artifact Digest");
    expect(text).not.toContain("artifact_digest");
  });

  it("does not match internal custody fields in scientist-facing catalog search", async () => {
    const wrapper = mountPanel();

    await wrapper.get('[data-testid="catalog-text-filter"]').setValue("artifact_digest");

    expect(wrapper.findAll(".catalog-card")).toHaveLength(0);
  });

  it("shows the exact optional-runtime remediation and refuses to imply ingestion uses SCP", async () => {
    const wrapper = mountPanel();
    const card = wrapper.get('[data-testid="catalog-node-model.efa"]');
    await card.get("summary").trigger("click");
    expect(card.text()).toContain("pip install 'spectra-sherpa[scp]'");
    expect(card.text()).toContain("SpectroChemPy does not supply ingestion");
    expect(card.text()).toContain("Execution is unavailable until the dependency check passes");
  });

  it("emits an add request without opening or hiding the catalog entry", async () => {
    const wrapper = mountPanel();
    await wrapper.get('[data-testid="catalog-add-model.pca"]').trigger("click");
    expect(wrapper.emitted("add-node")).toEqual([["model.pca"]]);
    expect(
      wrapper.get('[data-testid="catalog-node-model.pca"]').attributes("open"),
    ).toBeUndefined();
  });

  it("links the contract help authority safely in a keyboard-native new-tab control", async () => {
    const wrapper = mountPanel();
    const card = wrapper.get('[data-testid="catalog-node-model.pca"]');
    await card.get("summary").trigger("click");

    const link = card.get('[data-testid="catalog-help-model.pca"]');
    expect(link.element.tagName).toBe("A");
    expect(link.attributes("href")).toBe("https://docs.spectrascientific.ai/nodes/test/");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
    expect(link.attributes("aria-label")).toContain("opens in a new tab");
  });

  it("does not render a link for an unsafe help reference", async () => {
    const unsafeNode = {
      ...nodes[1],
      execution_contract: contract("fitted_model", "none", {
        help_reference: "https://example.test/redirect.md",
      }),
    };
    const wrapper = mount(NodeCatalogPanel, {
      props: { nodes: [unsafeNode], addableNodeTypes: [unsafeNode.node_type] },
    });
    await wrapper.get("summary").trigger("click");
    expect(wrapper.find('[data-testid="catalog-help-model.pca"]').exists()).toBe(false);
  });
});
