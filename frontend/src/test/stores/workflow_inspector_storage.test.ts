import { describe, it, expect } from "vitest";

/**
 * Unit-tests for the sessionStorage tiering logic used by
 * WorkflowInspector's buildNodeDetailData().
 *
 * The actual function lives inside a Vue component and isn't directly
 * importable, so we replicate the exact branching logic here and test
 * that large output.* payloads are properly stripped in reduced tiers.
 */

interface NodeOutput {
  data: unknown;
  metadata: Record<string, unknown> | null;
  plots: unknown;
  ports: unknown;
  primary_port: unknown;
}

function buildNodeDetailData(
  level: "full" | "primary" | "minimal",
  nodeType: string,
  nodeOutput: NodeOutput | null,
) {
  const includeData = level !== "minimal";
  const includePorts = level === "full";

  // Metadata stripping — mirrors WorkflowInspector lines 2628-2654
  let metadata = nodeOutput?.metadata ?? null;
  if (level !== "full" && metadata && nodeType.startsWith("output.")) {
    const lightMetadata = { ...metadata };
    delete lightMetadata.data; // Plotly traces duplicated in output.data
    metadata = lightMetadata;
  }
  if (level === "minimal" && metadata) {
    const lightMetadata = { ...metadata };
    if (nodeType.startsWith("output.")) {
      delete lightMetadata.data;
    }
    metadata = lightMetadata;
  }

  return {
    output: nodeOutput
      ? {
          // For output.* nodes in reduced tiers, top-level data duplicates
          // the Plotly traces already stripped from metadata — omit it too.
          data:
            includeData && !(level !== "full" && nodeType.startsWith("output."))
              ? nodeOutput.data
              : null,
          metadata,
          plots: nodeOutput.plots || null,
          ports: includePorts ? (nodeOutput.ports || null) : null,
          primary_port: nodeOutput.primary_port || null,
        }
      : null,
  };
}

// ── Helpers ─────────────────────────────────────────────────────────────

/** Build a fake output.* nodeOutput with a large data payload. */
function makeLargeOutputPayload(nTraces = 100): NodeOutput {
  const bigTrace = {
    x: Array.from({ length: 2000 }, (_, i) => i),
    y: Array.from({ length: 2000 }, () => Math.random()),
    type: "scatter",
    mode: "lines",
    name: "Sample",
  };
  return {
    data: Array.from({ length: nTraces }, () => ({ ...bigTrace })),
    metadata: {
      plot_type: "spectra",
      data: Array.from({ length: nTraces }, () => ({ ...bigTrace })),
      layout: { title: "Test" },
    },
    plots: null,
    ports: null,
    primary_port: null,
  };
}

// ── Tests ───────────────────────────────────────────────────────────────

describe("WorkflowInspector sessionStorage tiers", () => {
  it("full tier preserves all data for output.* nodes", () => {
    const payload = makeLargeOutputPayload(60);
    const result = buildNodeDetailData("full", "output.plot", payload);

    expect(result.output!.data).not.toBeNull();
    expect(result.output!.metadata).toHaveProperty("data");
  });

  it("primary tier strips output.data AND metadata.data for output.* nodes", () => {
    const payload = makeLargeOutputPayload(60);
    const result = buildNodeDetailData("primary", "output.plot", payload);

    // Top-level data must be null — this is the fix
    expect(result.output!.data).toBeNull();
    // Metadata.data (Plotly traces duplicate) must also be gone
    expect(result.output!.metadata).not.toHaveProperty("data");
    // Layout survives
    expect(result.output!.metadata).toHaveProperty("layout");
  });

  it("minimal tier strips output.data for output.* nodes", () => {
    const payload = makeLargeOutputPayload(60);
    const result = buildNodeDetailData("minimal", "output.plot", payload);

    expect(result.output!.data).toBeNull();
    expect(result.output!.metadata).not.toHaveProperty("data");
  });

  it("primary tier preserves output.data for non-output nodes", () => {
    const payload: NodeOutput = {
      data: { scores: [[1, 2]] },
      metadata: { n_components: 3 },
      plots: null,
      ports: null,
      primary_port: null,
    };
    const result = buildNodeDetailData("primary", "model.pca", payload);

    // Non-output nodes keep their data in the primary tier
    expect(result.output!.data).not.toBeNull();
  });

  it("primary tier for output.contour also strips data", () => {
    const payload = makeLargeOutputPayload(20);
    const result = buildNodeDetailData("primary", "output.contour", payload);

    expect(result.output!.data).toBeNull();
    expect(result.output!.metadata).not.toHaveProperty("data");
  });

  it("serialised primary payload is smaller than full for large output nodes", () => {
    const payload = makeLargeOutputPayload(100);
    const full = JSON.stringify(buildNodeDetailData("full", "output.plot", payload));
    const primary = JSON.stringify(buildNodeDetailData("primary", "output.plot", payload));

    // Primary should be dramatically smaller — data was the dominant cost
    expect(primary.length).toBeLessThan(full.length * 0.05);
  });
});
