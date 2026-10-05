import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import api from "@/api/client";
import { useWorkflowStore } from "@/stores/workflow";
import type { NodeLibraryResponse, NodeTypeMetadata } from "@/types";
import type { TypeRegistryPayload, WorkflowTemplate } from "@/stores/workflow-types";

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const datasetType = "spectrasherpa://types/SpectralDataset/1.0";
const targetType = "spectrasherpa://types/TargetVector/1.0";

const typeRegistry: TypeRegistryPayload = {
  version: "1.0.0",
  types: {
    SpectralDataset: {
      uri: datasetType,
      version: "1.0",
      parent: "Array2D",
      parent_uri: "spectrasherpa://types/Array2D/1.0",
      category: "dataset",
      description: "Dataset",
    },
    TargetVector: {
      uri: targetType,
      version: "1.0",
      parent: "Array1D",
      parent_uri: "spectrasherpa://types/Array1D/1.0",
      category: "target",
      description: "Target",
    },
    Array2D: {
      uri: "spectrasherpa://types/Array2D/1.0",
      version: "1.0",
      parent: null,
      parent_uri: null,
      category: "dataset",
      description: "Array2D",
    },
    Array1D: {
      uri: "spectrasherpa://types/Array1D/1.0",
      version: "1.0",
      parent: null,
      parent_uri: null,
      category: "array",
      description: "Array1D",
    },
  },
  subtypes: {
    Array2D: ["SpectralDataset"],
    Array1D: ["TargetVector"],
  },
};

const nodeLibraryNodes: NodeTypeMetadata[] = [
  {
    node_type: "data.file_load",
    category: "data",
    label: "Data Source",
    description: "",
    parameters: [],
    input_types: [],
    output_type: "SherpaDataset",
    output_ports: [
      { name: "default", label: "Dataset", type_ref: datasetType, required: true },
      { name: "target", label: "Target", type_ref: targetType, required: false },
    ],
  },
  {
    node_type: "preprocess.scale",
    category: "preprocessing",
    label: "Scale",
    description: "",
    parameters: [],
    input_types: ["SherpaDataset"],
    output_type: "SherpaDataset",
    input_ports: [
      { name: "default", label: "Input Data", type_ref: datasetType, required: true },
      { name: "reference", label: "Reference Data", type_ref: datasetType, required: false },
    ],
    output_ports: [
      { name: "default", label: "Scaled Data", type_ref: datasetType, required: true },
    ],
  },
  {
    node_type: "preprocess.clip_range",
    category: "preprocessing",
    label: "Clip Feature Range",
    description: "",
    parameters: [
      {
        name: "minimum",
        label: "Minimum Feature Coordinate",
        param_type: "number",
        default: 400,
        required: true,
      },
      {
        name: "maximum",
        label: "Maximum Feature Coordinate",
        param_type: "number",
        default: 4000,
        required: true,
      },
    ],
    input_types: ["SpectralDataset"],
    output_type: "SpectralDataset",
    input_ports: [
      { name: "default", label: "Input Spectra", type_ref: datasetType, required: true },
    ],
    output_ports: [
      { name: "default", label: "Clipped Spectra", type_ref: datasetType, required: true },
    ],
  },
  {
    node_type: "output.plot",
    category: "output",
    label: "Plot",
    description: "",
    parameters: [],
    input_types: ["plot"],
    output_type: "plot",
    input_ports: [{ name: "plot_data", label: "Plot Data", type_ref: datasetType, required: true }],
    output_ports: [{ name: "default", label: "Plot", type_ref: datasetType, required: true }],
  },
];

const nodeLibraryResponse: NodeLibraryResponse = {
  nodes: nodeLibraryNodes,
  total: nodeLibraryNodes.length,
  version: "1.0.0",
};

describe("Workflow Store node-library contract cache", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    vi.mocked(api.post).mockResolvedValue({
      data: { workflow_id: -1, is_valid: true, issues: [], semantic_edges: [] },
    });
  });

  it("refreshes for a changed contract identity even when the app version is unchanged", async () => {
    let contractIdentity = "spectra-node-library/3:one";
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows/nodes/library") {
        return { data: { ...nodeLibraryResponse, cache_identity: contractIdentity } };
      }
      if (url === "/workflows/types/registry") return { data: typeRegistry };
      throw new Error(`Unexpected GET ${url}`);
    });

    const store = useWorkflowStore();
    await store.fetchNodeLibrary();
    await store.checkAndRefreshNodeLibrary();
    expect(
      vi.mocked(api.get).mock.calls.filter(([url]) => url === "/workflows/nodes/library"),
    ).toHaveLength(2);

    contractIdentity = "spectra-node-library/3:two";
    await store.checkAndRefreshNodeLibrary();
    expect(store.nodeLibraryCacheIdentity).toBe(contractIdentity);
    // One lightweight probe plus one complete refresh; the unchanged app
    // version must not hide the contract identity change.
    expect(
      vi.mocked(api.get).mock.calls.filter(([url]) => url === "/workflows/nodes/library"),
    ).toHaveLength(4);
  });

  it("matches the server's strict Clip Range ordering rule", async () => {
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows/nodes/library") return { data: nodeLibraryResponse };
      if (url === "/workflows/types/registry") return { data: typeRegistry };
      throw new Error(`Unexpected GET ${url}`);
    });
    const store = useWorkflowStore();
    await store.fetchNodeLibrary();

    expect(
      store.validateNodeParams("preprocess.clip_range", { minimum: 1800, maximum: 1800 }),
    ).toEqual([
      {
        param_name: "maximum",
        message: "Maximum Feature Coordinate must be greater than Minimum Feature Coordinate",
      },
    ]);
    expect(
      store.validateNodeParams("preprocess.clip_range", { minimum: 400, maximum: 4000 }),
    ).toEqual([]);
  });
});

describe("Workflow Store template edge validation", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("keeps explicit default ports valid when loading a template", async () => {
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows/nodes/library") {
        return { data: nodeLibraryResponse };
      }
      if (url === "/workflows/types/registry") {
        return { data: typeRegistry };
      }
      throw new Error(`Unexpected GET ${url}`);
    });

    const store = useWorkflowStore();
    await store.fetchNodeLibrary();

    store.templates = [
      {
        id: 1,
        slug: "template-with-default-port",
        name: "Template With Default Port",
        description: "",
        category: "test",
        status: "ready",
        is_active: true,
        created_at: "2026-03-25T00:00:00Z",
        updated_at: "2026-03-25T00:00:00Z",
        template_data: {
          nodes: [
            {
              node_id: "source",
              node_type: "data.file_load",
              label: "Source",
              parameters: {},
              position_x: 0,
              position_y: 0,
            },
            {
              node_id: "scale",
              node_type: "preprocess.scale",
              label: "Scale",
              parameters: {},
              position_x: 100,
              position_y: 0,
            },
          ],
          edges: [
            {
              from_node_id: "source",
              to_node_id: "scale",
              from_output: "default",
              to_input: "default",
            },
          ],
        },
      } satisfies WorkflowTemplate,
    ];

    expect(store.loadTemplate(1)).toBe(true);
    expect(store.edges).toHaveLength(1);
    expect(store.edges[0].toPort).toBe("default");
    expect(store.edges[0].isValid).toBe(true);
    expect(store.edges[0].validationError).toBeNull();
  });

  it("resolves backend default ports onto single-input nodes that use a non-default port name", async () => {
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows/nodes/library") {
        return { data: nodeLibraryResponse };
      }
      if (url === "/workflows/types/registry") {
        return { data: typeRegistry };
      }
      throw new Error(`Unexpected GET ${url}`);
    });

    const store = useWorkflowStore();
    await store.fetchNodeLibrary();

    store.templates = [
      {
        id: 2,
        slug: "template-single-input-fallback",
        name: "Template Single Input Fallback",
        description: "",
        category: "test",
        status: "ready",
        is_active: true,
        created_at: "2026-03-25T00:00:00Z",
        updated_at: "2026-03-25T00:00:00Z",
        template_data: {
          nodes: [
            {
              node_id: "source",
              node_type: "data.file_load",
              label: "Source",
              parameters: {},
              position_x: 0,
              position_y: 0,
            },
            {
              node_id: "plot",
              node_type: "output.plot",
              label: "Plot",
              parameters: {},
              position_x: 100,
              position_y: 0,
            },
          ],
          edges: [
            {
              from_node_id: "source",
              to_node_id: "plot",
              from_output: "default",
              to_input: "default",
            },
          ],
        },
      } satisfies WorkflowTemplate,
    ];

    expect(store.loadTemplate(2)).toBe(true);
    expect(store.edges).toHaveLength(1);
    expect(store.edges[0].toPort).toBe("default");
    expect(store.edges[0].isValid).toBe(true);
    expect(store.edges[0].validationError).toBeNull();
  });

  it("keeps the imported Harness file-load to model-apply edge visibly valid", async () => {
    const harnessNodes: NodeLibraryResponse = {
      ...nodeLibraryResponse,
      nodes: [
        {
          node_type: "data.file_load",
          category: "data",
          label: "Load File",
          description: "",
          parameters: [],
          input_types: [],
          output_type: "SpectralDataset",
          output_ports: [
            { name: "default", label: "Spectral Data", type_ref: datasetType, required: true },
          ],
        },
        {
          node_type: "model.load_apply",
          category: "deploy",
          label: "Apply Imported Model",
          description: "",
          parameters: [],
          input_types: ["SpectralDataset"],
          output_type: "array",
          input_ports: [
            { name: "X_new", label: "Data Matrix (X)", type_ref: datasetType, required: true },
          ],
        },
      ],
      total: 2,
    };
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows/nodes/library") return { data: harnessNodes };
      if (url === "/workflows/types/registry") return { data: typeRegistry };
      throw new Error(`Unexpected GET ${url}`);
    });
    const store = useWorkflowStore();
    await store.fetchNodeLibrary();
    store.templates = [
      {
        id: 3,
        slug: "harness-imported-apply",
        name: "Apply imported Harness model",
        description: "",
        category: "test",
        status: "ready",
        is_active: true,
        created_at: "2026-08-06T00:00:00Z",
        updated_at: "2026-08-06T00:00:00Z",
        template_data: {
          nodes: [
            {
              node_id: "harness-public-data",
              node_type: "data.file_load",
              label: "Load File",
              parameters: {},
              position_x: 0,
              position_y: 0,
            },
            {
              node_id: "pls",
              node_type: "model.load_apply",
              label: "Apply Imported Model",
              parameters: {},
              position_x: 100,
              position_y: 0,
            },
          ],
          edges: [
            {
              from_node_id: "harness-public-data",
              to_node_id: "pls",
              from_output: "default",
              to_input: "X_new",
            },
          ],
        },
      } satisfies WorkflowTemplate,
    ];
    expect(store.loadTemplate(3)).toBe(true);
    expect(store.edges[0].isValid).toBe(true);
    expect(store.edges[0].validationError).toBeNull();
  });
});

describe("Workflow Store template source bindings", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("preserves the scientist's explicit target through the API boundary", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { id: 91, project_id: 17, source_template_slug: "pls-calibration" },
    });
    const store = useWorkflowStore();

    await store.instantiateTemplate(4, {
      workflowName: "Moisture calibration",
      projectId: 17,
      launchMode: "user",
      dataBindings: {
        data_1: {
          source: "experiment",
          experimentId: 21,
          displayName: "Corn M5",
          fileId: 22,
          targetAuthority: {
            schema_version: "spectrasherpa-target-authority/1",
            column: "Moisture",
            target_type: "continuous",
            units: "%",
            source_digest: "a".repeat(64),
          },
        },
      },
    });

    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/workflow-templates/4/instantiate",
      expect.objectContaining({
        data_bindings: {
          data_1: expect.objectContaining({
            experiment_id: 21,
            display_name: "Corn M5",
            file_id: 22,
            target_authority: {
              schema_version: "spectrasherpa-target-authority/1",
              column: "Moisture",
              target_type: "continuous",
              units: "%",
              source_digest: "a".repeat(64),
            },
          }),
        },
      }),
    );
  });
});

/**
 * Regression guard for the "Sherpa sees all nodes as pending after refresh" bug.
 *
 * loadWorkflow() used to restore lastExecutionResults and lastExecutionDiagnostics
 * from /workflows/{id}/runs/latest, but did NOT restore node.executionState on
 * the node objects themselves. So after a page refresh, buildSyncPayload()
 * reported execution_status="pending" and output_shape=null to Sherpa, which
 * caused the LLM to hallucinate dimensions and say "workflow hasn't been run".
 */
describe("Workflow Store execution state restoration on loadWorkflow", () => {
  it('discloses reduced retained evidence and clears that notice when changing to an unexecuted sheet', async () => {
    setActivePinia(createPinia());
    vi.mocked(api.post).mockResolvedValue({ data: { is_valid: true, issues: [], semantic_edges: [] } });
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === '/workflows/nodes/library') return { data: nodeLibraryResponse };
      if (url === '/workflows/types/registry') return { data: typeRegistry };
      if (url === '/workflows/42/runs/latest') return { data: {
        id: 19, results_summary: {}, evidence_completeness: { qualification: 'qualified', outputs: {
          pca: { scores: { state: 'reduced', reason: 'Only a preview was retained.' } },
        } },
        evidence_gaps: [{ node_id: 'pca', output: 'scores', role: 'scores', state: 'reduced',
          category: 'reduced', reason: 'Only a preview was retained.',
          recovery: 'Inspect the retained preview or rerun to recreate the complete output.' }],
      } };
      if (url === '/workflows/43/runs/latest') return { data: null };
      return { data: { id: url.endsWith('42') ? 42 : 43, name: 'Test', nodes: [], edges: [] } };
    });
    const store = useWorkflowStore();
    await store.loadWorkflow(42);
    expect(store.restoredRunId).toBe(19);
    expect(store.restoredEvidenceNotice).toContain('1 retained outputs are incomplete');
    expect(store.restoredEvidenceGaps[0]).toMatchObject({ node_id: 'pca', output: 'scores' });
    await store.loadWorkflow(43);
    expect(store.restoredRunId).toBeNull();
    expect(store.restoredEvidenceNotice).toBeNull();
    expect(store.restoredEvidenceGaps).toEqual([]);
  });

  const scientificDescriptor = (portName: string, kind: string, shape: number[]) => ({
    schema_version: "spectrasherpa-scientific-value/1",
    port_name: portName,
    type_ref: `spectrasherpa://types/Array2D/1.0`,
    label: portName,
    scientific_kind: kind,
    view_kind: "matrix",
    shape,
    dimensions: shape.map((size, index) => ({ role: `axis_${index + 1}`, size })),
    view_modes: ["table"],
    content_categories: ["unclassified"],
    shape_valid: true,
    shape_issue: null,
  });

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    vi.mocked(api.post).mockResolvedValue({
      data: { workflow_id: -1, is_valid: true, issues: [], semantic_edges: [] },
    });
  });

  it("ignores an earlier workflow response after a newer load starts", async () => {
    let resolveFirstWorkflow!: (value: { data: Record<string, unknown> }) => void;
    const firstWorkflow = new Promise<{ data: Record<string, unknown> }>((resolve) => {
      resolveFirstWorkflow = resolve;
    });
    const workflowPayload = (id: number, name: string) => ({
      id,
      name,
      description: null,
      integrity_hash: `hash-${id}`,
      warnings: [],
      nodes: [],
      edges: [],
    });

    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows/nodes/library") return { data: nodeLibraryResponse };
      if (url === "/workflows/types/registry") return { data: typeRegistry };
      if (url === "/workflows/1") return firstWorkflow;
      if (url === "/workflows/2") return { data: workflowPayload(2, "Project 2 Workflow") };
      if (url === "/workflows/2/runs/latest") return { data: null };
      throw new Error(`Unexpected GET ${url}`);
    });

    const store = useWorkflowStore();
    const firstLoad = store.loadWorkflow(1);
    await vi.waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/workflows/1");
    });
    const secondLoad = store.loadWorkflow(2);
    await secondLoad;
    resolveFirstWorkflow({ data: workflowPayload(1, "Project 1 Workflow") });
    await firstLoad;

    expect(store.workflowId).toBe(2);
    expect(store.workflowName).toBe("Project 2 Workflow");
  });

  it("restores node status and output_shape from the latest run", async () => {
    const workflowPayload = {
      id: 42,
      name: "Iris PLS-DA",
      description: null,
      integrity_hash: "abc123",
      warnings: [],
      nodes: [
        {
          node_id: "data_1",
          node_type: "data.file_load",
          label: "Data",
          parameters: {},
          position_x: 0,
          position_y: 0,
        },
        {
          node_id: "plsda_1",
          node_type: "classification.plsda",
          label: "PLS-DA",
          parameters: { n_components: 2 },
          position_x: 100,
          position_y: 0,
        },
      ],
      edges: [
        { from_node_id: "data_1", to_node_id: "plsda_1", from_output: "default", to_input: "X" },
      ],
    };

    const latestRunPayload = {
      integrity_hash: "abc123",
      executed_at: "2026-04-10T12:00:00Z",
      node_statuses: {
        data_1: "completed",
        plsda_1: "completed",
      },
      results_summary: {
        data_1: { type: "SherpaDataset", n_samples: 150, n_features: 4 },
        plsda_1: {
          type: "PLS_DA",
          default: { type: "SherpaDataset", n_samples: 150, n_features: 2 },
        },
      },
      diagnostics: {
        plsda_1: { accuracy: 0.98, n_components: 2, n_classes: 3 },
        _scientific_values: {
          data_1: {
            default: scientificDescriptor("default", "spectral_dataset", [150, 4]),
          },
          plsda_1: {
            default: scientificDescriptor("default", "class_score_matrix", [150, 2]),
            comparison: scientificDescriptor("comparison", "regression_comparison", [150, 6]),
          },
        },
        _scientific_presentations: {
          plsda_1: {
            schema_version: "spectrasherpa-executed-presentation/1",
            contract_digest: "a".repeat(64),
            contract: {
              schema_version: "spectrasherpa-node-presentation/1",
              default_presentation: "comparison",
              presentations: [
                {
                  presentation_id: "comparison",
                  label: "Sample Comparison",
                  kind: "regression_comparison",
                  source_ports: ["comparison"],
                  modes: ["plot", "table"],
                  description: "Persisted class scores.",
                },
              ],
            },
            presentations: [],
          },
        },
      },
    };

    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows/42") {
        return { data: workflowPayload };
      }
      if (url === "/workflows/42/runs/latest") {
        return { data: latestRunPayload };
      }
      if (url === "/workflows/nodes/library") {
        return { data: { nodes: [], total: 0 } };
      }
      if (url === "/workflows/types/registry") {
        return { data: typeRegistry };
      }
      throw new Error(`Unexpected GET ${url}`);
    });

    const store = useWorkflowStore();
    await store.loadWorkflow(42);

    // Both nodes must be marked completed, not pending.
    const dataNode = store.nodes.find((n) => n.id === "data_1");
    const plsdaNode = store.nodes.find((n) => n.id === "plsda_1");
    expect(dataNode).toBeDefined();
    expect(plsdaNode).toBeDefined();
    expect(dataNode?.label).toBe("Data");
    expect(plsdaNode?.label).toBe("PLS-DA");
    expect(dataNode?.executionState?.status).toBe("completed");
    expect(plsdaNode?.executionState?.status).toBe("completed");

    // CRITICAL: output_shape must be restored so Sherpa sees the real shapes.
    // Without this the LLM hallucinates dimensions from common datasets.
    expect(dataNode?.executionState?.output_shape).toEqual([150, 4]);
    expect(plsdaNode?.executionState?.output_shape).toEqual([150, 6]);
    expect(plsdaNode?.executionState?.output_shape_label).toBe("Sample Comparison");

    // output_type must also be restored.
    expect(dataNode?.executionState?.output_type).toBe("spectral_dataset");

    // lastExecutionResults and lastExecutionDiagnostics preserved.
    expect(store.lastExecutionResults).toEqual(latestRunPayload.results_summary);
    expect(store.lastExecutionDiagnostics).toEqual(latestRunPayload.diagnostics);
    expect(store.lastExecutionResultDescriptors).toEqual(
      latestRunPayload.diagnostics._scientific_values,
    );
    expect(store.lastExecutionPresentations).toEqual(
      latestRunPayload.diagnostics._scientific_presentations,
    );
    expect(store.isWorkflowStale).toBe(false);
  });

  it.each(["Source", "data.file_load", null])("restores labels (%s) without overriding backend edge validity", async (label) => {
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows/91") {
        return {
          data: {
            id: 91,
            name: "Persisted",
            description: null,
            integrity_hash: null,
            warnings: [],
            nodes: [
              {
                node_id: "source",
                node_type: "data.file_load",
                label,
                parameters: {},
                position_x: 0,
                position_y: 0,
              },
              {
                node_id: "target",
                node_type: "model.pca",
                label: "Target",
                parameters: {},
                position_x: 100,
                position_y: 0,
              },
            ],
            edges: [
              {
                from_node_id: "source",
                to_node_id: "target",
                from_output: "default",
                to_input: "default",
              },
            ],
          },
        };
      }
      if (url === "/workflows/91/runs/latest") throw new Error("404 Not Found");
      if (url === "/workflows/nodes/library") return { data: nodeLibraryResponse };
      if (url === "/workflows/types/registry") return { data: typeRegistry };
      throw new Error(`Unexpected GET ${url}`);
    });
    vi.mocked(api.post).mockResolvedValue({
      data: {
        workflow_id: 91,
        is_valid: false,
        issues: [
          {
            level: "error",
            code: "incompatible_semantic_edge",
            message: "Server says this edge is incompatible.",
          },
        ],
        semantic_edges: [
          {
            from_node_id: "source",
            from_output: "default",
            to_node_id: "target",
            to_input: "default",
            status: "invalid",
            reason: "semantic mismatch",
          },
        ],
      },
    });

    const store = useWorkflowStore();
    await store.loadWorkflow(91);

    expect(vi.mocked(api.post)).toHaveBeenCalledWith("/workflows/91/preflight");
    expect(store.edges[0].isValid).toBe(false);
    expect(store.edges[0].validationError).toBe("semantic mismatch");
    expect(store.edges[0].dataType).toBe("SpectralDataset@1.0");
    expect(store.nodes[0].label).toBe(label === "Source" ? "Source" : "Data Source");
    expect(store.workflowWarnings).toContain("Server says this edge is incompatible.");
  });

  it("sets stale from the workflow hash and latest-run hash on load", async () => {
    const workflowPayload = {
      id: 44,
      name: "Modified since run",
      description: null,
      integrity_hash: "current-hash",
      warnings: [],
      nodes: [
        {
          node_id: "data_1",
          node_type: "data.file_load",
          label: "Data",
          parameters: {},
          position_x: 0,
          position_y: 0,
        },
      ],
      edges: [],
    };

    const latestRunPayload = {
      integrity_hash: "last-run-hash",
      executed_at: "2026-04-10T12:00:00Z",
      node_statuses: {
        data_1: "completed",
      },
      results_summary: {
        data_1: { type: "SherpaDataset", n_samples: 150, n_features: 4 },
      },
      diagnostics: {},
    };

    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows/44") {
        return { data: workflowPayload };
      }
      if (url === "/workflows/44/runs/latest") {
        return { data: latestRunPayload };
      }
      if (url === "/workflows/nodes/library") {
        return { data: { nodes: [], total: 0 } };
      }
      if (url === "/workflows/types/registry") {
        return { data: typeRegistry };
      }
      throw new Error(`Unexpected GET ${url}`);
    });

    const store = useWorkflowStore();
    store.markWorkflowStale();

    await store.loadWorkflow(44);

    expect(store.isWorkflowStale).toBe(true);
    expect(store.workflowWarnings).toContain(
      "Current graph and retained run identity are different or unverified — results may be stale.",
    );
  });

  it("does not restore state when there is no latest run", async () => {
    const workflowPayload = {
      id: 43,
      name: "Unexecuted",
      description: null,
      integrity_hash: null,
      warnings: [],
      nodes: [
        {
          node_id: "data_1",
          node_type: "data.file_load",
          label: "Data",
          parameters: {},
          position_x: 0,
          position_y: 0,
        },
      ],
      edges: [],
    };

    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows/43") {
        return { data: workflowPayload };
      }
      if (url === "/workflows/43/runs/latest") {
        throw new Error("404 Not Found");
      }
      if (url === "/workflows/nodes/library") {
        return { data: { nodes: [], total: 0 } };
      }
      if (url === "/workflows/types/registry") {
        return { data: typeRegistry };
      }
      throw new Error(`Unexpected GET ${url}`);
    });

    const store = useWorkflowStore();
    await store.loadWorkflow(43);

    const dataNode = store.nodes.find((n) => n.id === "data_1");
    expect(dataNode).toBeDefined();
    // No latest run — executionState is not initialized (no shapes to restore).
    // The important contract is that we did NOT fabricate a "completed" state.
    expect(dataNode?.executionState?.status).not.toBe("completed");
    expect(dataNode?.executionState?.output_shape).toBeFalsy();
    expect(store.lastExecutionResults).toBeNull();
    expect(store.isWorkflowStale).toBe(false);
  });
});

describe("Workflow Store node updates", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("ignores equivalent node updates so opening the inspector does not stale a run", () => {
    const store = useWorkflowStore();
    store.nodes = [
      {
        id: "model_1",
        type: "model.pca",
        x: 0,
        y: 0,
        params: { n_components: 2, scale: false },
        executionState: { status: "completed" },
      },
    ];
    store.hasUnsavedChanges = false;
    store.clearWorkflowStale();

    store.updateNode("model_1", {
      params: { scale: false, n_components: 2 },
    });

    expect(store.hasUnsavedChanges).toBe(false);
    expect(store.isWorkflowStale).toBe(false);
    expect(store.nodes[0].executionState?.status).toBe("completed");
  });

  it("marks the workflow stale when node params actually change", () => {
    const store = useWorkflowStore();
    store.nodes = [
      {
        id: "model_1",
        type: "model.pca",
        x: 0,
        y: 0,
        params: { n_components: 2, scale: false },
        executionState: { status: "completed" },
      },
    ];
    store.hasUnsavedChanges = false;
    store.clearWorkflowStale();

    store.updateNode("model_1", {
      params: { n_components: 3, scale: false },
    });

    expect(store.hasUnsavedChanges).toBe(true);
    expect(store.isWorkflowStale).toBe(true);
    expect(store.nodes[0].params).toEqual({ n_components: 3, scale: false });
  });

  it("saves position-only canvas updates without marking a completed workflow stale", () => {
    const store = useWorkflowStore();
    store.nodes = [
      {
        id: "model_1",
        type: "model.pca",
        x: 0,
        y: 0,
        params: { n_components: 2 },
        executionState: { status: "completed" },
      },
    ];
    store.edges = [];
    store.hasUnsavedChanges = false;
    store.clearWorkflowStale();

    store.setNodes([
      {
        ...store.nodes[0],
        x: 120,
        y: 48,
      },
    ]);

    expect(store.hasUnsavedChanges).toBe(true);
    expect(store.isWorkflowStale).toBe(false);
    expect(store.nodes[0].x).toBe(120);
    expect(store.nodes[0].executionState?.status).toBe("completed");
  });

  it("does not mark stale when edges are semantically unchanged but reordered", () => {
    const store = useWorkflowStore();
    store.nodes = [
      { id: "data_1", type: "data.file_load", x: 0, y: 0, params: {} },
      { id: "scale_1", type: "preprocess.scale", x: 100, y: 0, params: {} },
      { id: "model_1", type: "model.pca", x: 200, y: 0, params: { n_components: 2 } },
    ];
    store.edges = [
      { from: "data_1", to: "scale_1", fromPort: "default", toPort: "default" },
      { from: "scale_1", to: "model_1", fromPort: "default", toPort: "default" },
    ];
    store.hasUnsavedChanges = false;
    store.clearWorkflowStale();

    store.setEdges([...store.edges].reverse());

    expect(store.hasUnsavedChanges).toBe(true);
    expect(store.isWorkflowStale).toBe(false);
  });
});


describe("Sherpa explicit run identity", () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); });
  it("loads the requested retained run and never substitutes latest", async () => {
    const store = useWorkflowStore();
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url === "/workflows/42") return { data: { id: 42, nodes: [], edges: [] } };
      if (url === "/workflows/42/runs/99") return { data: { id: 99, results_summary: {}, node_statuses: {} } };
      if (url === "/workflows/nodes") return { data: { nodes: [] } };
      return { data: {} };
    });
    await store.loadWorkflow(42, 99);
    expect(store.restoredRunId).toBe(99);
    expect(api.get).not.toHaveBeenCalledWith("/workflows/42/runs/latest");
  });
});

describe("Workflow partial execution status", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("keeps skipped descendants pending when one node fails", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: {
        workflow_id: 77,
        status: "partial",
        error: "Install the optional SpectroChemPy support",
        node_statuses: {
          source: "completed",
          mcr: "error",
          report: "error",
          unrelated: "pending",
        },
        results: { source: { type: "SherpaDataset", n_samples: 2, n_features: 3 } },
        diagnostics: {},
      },
    } as never);

    const store = useWorkflowStore();
    store.workflowId = 77;
    store.nodes = [
      { id: "source", type: "data.file_load", x: 0, y: 0, params: {} },
      { id: "mcr", type: "model.mcr_als", x: 100, y: 0, params: {} },
      { id: "report", type: "output.plot", x: 200, y: 0, params: {} },
      { id: "unrelated", type: "stats.summary", x: 0, y: 100, params: {} },
    ];
    store.edges = [
      { from: "source", to: "mcr", fromPort: "default", toPort: "default" },
      { from: "mcr", to: "report", fromPort: "default", toPort: "default" },
    ];
    store.hasUnsavedChanges = false;

    await store.executeWorkflow();

    expect(store.nodes.find((node) => node.id === "source")?.executionState?.status).toBe("completed");
    expect(store.nodes.find((node) => node.id === "mcr")?.executionState).toMatchObject({
      status: "error",
      error_message: "Install the optional SpectroChemPy support",
    });
    expect(store.nodes.find((node) => node.id === "report")?.executionState).toMatchObject({
      status: "pending",
      error_message: "Not run because upstream node 'mcr' failed.",
    });
    expect(store.nodes.find((node) => node.id === "unrelated")?.executionState?.status).toBe("pending");
  });

  it("keeps FastICA descendants pending and preserves the recovery guidance", async () => {
    const recovery =
      "fit_fastica: FastICA did not converge under the declared settings (n_components=3, algorithm=parallel, contrast=logcosh, whiten=unit-variance, max_iter=400, tol=0.0001, random_seed=42). No component scores were accepted and downstream nodes were not run. Increase Maximum Iterations up to 2000 first; if convergence still fails, reduce Number of Components, review preprocessing, and then deliberately try the deflation algorithm or a looser tolerance.";
    vi.mocked(api.post).mockResolvedValueOnce({
      data: {
        workflow_id: 78,
        status: "partial",
        error: recovery,
        node_statuses: {
          source: "completed",
          fit_fastica: "error",
          source_scores: "error",
          mixing_profiles: "error",
          residual_summary: "error",
        },
        results: { source: { type: "SherpaDataset", n_samples: 155, n_features: 650 } },
        diagnostics: {},
      },
    } as never);

    const store = useWorkflowStore();
    store.workflowId = 78;
    store.nodes = [
      { id: "source", type: "data.file_load", x: 0, y: 0, params: {} },
      { id: "fit_fastica", type: "model.ica", x: 100, y: 0, params: {} },
      { id: "source_scores", type: "output.plot", x: 200, y: 0, params: {} },
      { id: "mixing_profiles", type: "output.plot", x: 200, y: 100, params: {} },
      { id: "residual_summary", type: "stats.summary", x: 200, y: 200, params: {} },
    ];
    store.edges = [
      { from: "source", to: "fit_fastica", fromPort: "default", toPort: "default" },
      { from: "fit_fastica", to: "source_scores", fromPort: "sources", toPort: "default" },
      { from: "fit_fastica", to: "mixing_profiles", fromPort: "components", toPort: "default" },
      { from: "fit_fastica", to: "residual_summary", fromPort: "residuals", toPort: "default" },
    ];
    store.hasUnsavedChanges = false;

    await store.executeWorkflow();

    expect(store.nodes.find((node) => node.id === "fit_fastica")?.executionState).toMatchObject({
      status: "error",
      error_message: recovery,
    });
    for (const nodeId of ["source_scores", "mixing_profiles", "residual_summary"]) {
      expect(store.nodes.find((node) => node.id === nodeId)?.executionState).toMatchObject({
        status: "pending",
        error_message: "Not run because upstream node 'fit_fastica' failed.",
      });
    }
  });
});
