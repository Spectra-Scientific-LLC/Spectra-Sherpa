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
