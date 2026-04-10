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
    node_type: "data.source",
    category: "data",
    label: "Data Source",
    description: "",
    parameters: [],
    input_types: [],
    output_type: "NDDataset",
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
    input_types: ["NDDataset"],
    output_type: "NDDataset",
    input_ports: [
      { name: "default", label: "Input Data", type_ref: datasetType, required: true },
      { name: "reference", label: "Reference Data", type_ref: datasetType, required: false },
    ],
    output_ports: [
      { name: "default", label: "Scaled Data", type_ref: datasetType, required: true },
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
    input_ports: [
      { name: "plot_data", label: "Plot Data", type_ref: datasetType, required: true },
    ],
    output_ports: [
      { name: "default", label: "Plot", type_ref: datasetType, required: true },
    ],
  },
];

const nodeLibraryResponse: NodeLibraryResponse = {
  nodes: nodeLibraryNodes,
  total: nodeLibraryNodes.length,
  version: "1.0.0",
};

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
            { node_id: "source", node_type: "data.source", label: "Source", parameters: {}, position_x: 0, position_y: 0 },
            { node_id: "scale", node_type: "preprocess.scale", label: "Scale", parameters: {}, position_x: 100, position_y: 0 },
          ],
          edges: [
            { from_node_id: "source", to_node_id: "scale", from_output: "default", to_input: "default" },
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
            { node_id: "source", node_type: "data.source", label: "Source", parameters: {}, position_x: 0, position_y: 0 },
            { node_id: "plot", node_type: "output.plot", label: "Plot", parameters: {}, position_x: 100, position_y: 0 },
          ],
          edges: [
            { from_node_id: "source", to_node_id: "plot", from_output: "default", to_input: "default" },
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
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("restores node status and output_shape from the latest run", async () => {
    const workflowPayload = {
      id: 42,
      name: "Iris PLS-DA",
      description: null,
      integrity_hash: "abc123",
      warnings: [],
      nodes: [
        { node_id: "data_1", node_type: "data.source", label: "Data", parameters: {}, position_x: 0, position_y: 0 },
        { node_id: "plsda_1", node_type: "classification.plsda", label: "PLS-DA", parameters: { n_components: 2 }, position_x: 100, position_y: 0 },
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
        plsda_1: { type: "PLS_DA", default: { type: "SherpaDataset", n_samples: 150, n_features: 2 } },
      },
      diagnostics: {
        plsda_1: { accuracy: 0.98, n_components: 2, n_classes: 3 },
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
    expect(dataNode?.executionState?.status).toBe("completed");
    expect(plsdaNode?.executionState?.status).toBe("completed");

    // CRITICAL: output_shape must be restored so Sherpa sees the real shapes.
    // Without this the LLM hallucinates dimensions from common datasets.
    expect(dataNode?.executionState?.output_shape).toEqual([150, 4]);
    expect(plsdaNode?.executionState?.output_shape).toEqual([150, 2]);

    // output_type must also be restored.
    expect(dataNode?.executionState?.output_type).toBe("SherpaDataset");

    // lastExecutionResults and lastExecutionDiagnostics preserved.
    expect(store.lastExecutionResults).toEqual(latestRunPayload.results_summary);
    expect(store.lastExecutionDiagnostics).toEqual(latestRunPayload.diagnostics);
  });

  it("does not restore state when there is no latest run", async () => {
    const workflowPayload = {
      id: 43,
      name: "Unexecuted",
      description: null,
      integrity_hash: null,
      warnings: [],
      nodes: [
        { node_id: "data_1", node_type: "data.source", label: "Data", parameters: {}, position_x: 0, position_y: 0 },
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
  });
});
