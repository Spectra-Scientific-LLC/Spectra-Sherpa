import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import api from "@/api/client";
import { useWorkbookStore } from "@/stores/workbook";
import { useWorkflowStore } from "@/stores/workflow";
import type { NodeLibraryResponse } from "@/types";
import type { TypeRegistryPayload } from "@/stores/workflow-types";

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const datasetType = "spectrasherpa://types/SpectralDataset/1.0";

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
    Array2D: {
      uri: "spectrasherpa://types/Array2D/1.0",
      version: "1.0",
      parent: null,
      parent_uri: null,
      category: "dataset",
      description: "Array2D",
    },
  },
  subtypes: {
    Array2D: ["SpectralDataset"],
  },
};

const nodeLibraryResponse: NodeLibraryResponse = {
  version: "1.0.0",
  total: 3,
  nodes: [
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
      ],
    },
    {
      node_type: "model.pca",
      category: "analysis",
      label: "PCA",
      description: "",
      parameters: [],
      input_types: ["NDDataset"],
      output_type: "PCAModel",
      input_ports: [
        { name: "default", label: "Input Data", type_ref: datasetType, required: true },
      ],
      output_ports: [
        { name: "default", label: "PCA Model", type_ref: datasetType, required: true },
      ],
    },
    {
      node_type: "model.pls",
      category: "regression",
      label: "PLS",
      description: "",
      parameters: [],
      input_types: ["NDDataset"],
      output_type: "PLSModel",
      input_ports: [
        { name: "default", label: "Input Data", type_ref: datasetType, required: true },
      ],
      output_ports: [
        { name: "default", label: "PLS Model", type_ref: datasetType, required: true },
      ],
    },
  ],
};

const baseWorkflowPayload = {
  id: 10,
  name: "PCA Analysis",
  description: null,
  integrity_hash: "base-hash",
  warnings: [],
  nodes: [
    {
      node_id: "data_1",
      node_type: "data.source",
      label: "Data Source",
      parameters: { source: "example" },
      position_x: 100,
      position_y: 100,
    },
    {
      node_id: "model_1",
      node_type: "model.pca",
      label: "PCA",
      parameters: { n_components: 2 },
      position_x: 360,
      position_y: 100,
    },
  ],
  edges: [
    {
      from_node_id: "data_1",
      to_node_id: "model_1",
      from_output: "default",
      to_input: "default",
    },
  ],
};

const duplicatedWorkflowPayload = {
  ...baseWorkflowPayload,
  id: 20,
  name: "PCA Analysis (copy)",
  integrity_hash: "copy-hash",
};

describe("Workflow sheet frontend consistency", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    localStorage.clear();

    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/workflows") {
        return {
          data: [
            {
              id: 10,
              name: "PCA Analysis",
              created_at: "2026-05-01T00:00:00Z",
              updated_at: "2026-05-01T00:00:00Z",
              project_id: 1,
              tab_color: "#3b82f6",
              sheet_order: 0,
              node_count: 2,
              edge_count: 1,
            },
          ],
        };
      }
      if (url === "/workflows/nodes/library") {
        return { data: nodeLibraryResponse };
      }
      if (url === "/workflows/types/registry") {
        return { data: typeRegistry };
      }
      if (url === "/workflows/10") {
        return { data: baseWorkflowPayload };
      }
      if (url === "/workflows/20") {
        return { data: duplicatedWorkflowPayload };
      }
      if (url === "/workflows/10/runs/latest" || url === "/workflows/20/runs/latest") {
        throw new Error("404 Not Found");
      }
      throw new Error(`Unexpected GET ${url}`);
    });

    vi.mocked(api.post).mockImplementation(async (url: string) => {
      if (url === "/workflows/10/duplicate") {
        return {
          data: {
            id: 20,
            name: "PCA Analysis (copy)",
            created_at: "2026-05-01T00:00:00Z",
            updated_at: "2026-05-01T00:00:00Z",
            project_id: 1,
            tab_color: "#3b82f6",
            sheet_order: 1,
            node_count: 2,
            edge_count: 1,
          },
        };
      }
      if (url === "/workflows/20/execute") {
        return {
          data: {
            workflow_id: 20,
            status: "completed",
            executed_at: "2026-05-01T00:00:00Z",
            integrity_hash: "executed-hash",
            node_statuses: {
              data_1: "completed",
              model_1: "completed",
            },
            results: {
              data_1: { type: "SherpaDataset", n_samples: 150, n_features: 4 },
              model_1: { type: "PLSModel", n_samples: 150, n_features: 2 },
            },
            diagnostics: {
              model_1: { r2: 0.94 },
            },
          },
        };
      }
      throw new Error(`Unexpected POST ${url}`);
    });

    vi.mocked(api.put).mockImplementation(async (url: string) => {
      if (url === "/workflows/20") {
        return { data: { id: 20, integrity_hash: "saved-hash" } };
      }
      throw new Error(`Unexpected PUT ${url}`);
    });
  });

  it("duplicates a sheet, substitutes the algorithm, reconnects the graph, and runs the duplicate workflow", async () => {
    const workbookStore = useWorkbookStore();
    const workflowStore = useWorkflowStore();

    await workbookStore.loadSheets(1);
    expect(workbookStore.activeSheet?.workflowId).toBe(10);
    expect(workflowStore.workflowId).toBe(10);
    expect(workflowStore.edges).toHaveLength(1);
    expect(workflowStore.edges[0].isValid).toBe(true);

    await workbookStore.duplicateSheet(10);
    expect(workbookStore.sheets.map((sheet) => sheet.workflowId)).toEqual([10, 20]);
    expect(workbookStore.activeSheet?.workflowId).toBe(20);
    expect(workflowStore.workflowId).toBe(20);

    workflowStore.updateNode("model_1", {
      type: "model.pls",
      params: { n_components: 2, validation: "venetian_blinds" },
    });
    workflowStore.setEdges([]);
    workflowStore.addEdge({
      from: "data_1",
      to: "model_1",
      fromPort: "default",
      toPort: "default",
    });

    expect(workflowStore.nodes.find((node) => node.id === "model_1")?.type).toBe("model.pls");
    expect(workflowStore.edges).toEqual([
      expect.objectContaining({
        from: "data_1",
        to: "model_1",
        fromPort: "default",
        toPort: "default",
        isValid: true,
        validationError: null,
      }),
    ]);

    await workflowStore.executeWorkflow();

    expect(api.put).toHaveBeenCalledWith(
      "/workflows/20",
      expect.objectContaining({
        nodes: expect.arrayContaining([
          expect.objectContaining({
            node_id: "model_1",
            node_type: "model.pls",
            parameters: { n_components: 2, validation: "venetian_blinds" },
          }),
        ]),
        edges: [
          {
            from_node_id: "data_1",
            to_node_id: "model_1",
            from_output: "default",
            to_input: "default",
          },
        ],
      }),
    );
    // executeStoredWorkflow wraps the call with a fresh Idempotency-Key
    // header per request (REM-4). The key value is opaque; we only assert
    // the URL + body + that some Idempotency-Key was sent.
    expect(api.post).toHaveBeenCalledWith(
      "/workflows/20/execute",
      { initial_data: {} },
      expect.objectContaining({
        headers: expect.objectContaining({
          "Idempotency-Key": expect.any(String),
        }),
      }),
    );
    expect(workflowStore.lastExecutionResults?.model_1).toEqual({
      type: "PLSModel",
      n_samples: 150,
      n_features: 2,
    });
    expect(workflowStore.nodes.find((node) => node.id === "model_1")?.executionState?.status).toBe("completed");
    expect(workbookStore.activeSheet?.executionStatus).toBe("success");
  });
});
