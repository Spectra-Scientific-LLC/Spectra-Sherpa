import { describe, expect, it } from "vitest";
import { observationOutputMembership } from "@/utils/observationOutputMembership";

describe("computed observation membership", () => {
  it("uses only the output's exact sample axis, not its larger display companion", () => {
    const display = { data: [[1], [2], [3]], sample_axis: {
      workflow_observation_refs: ["source:one", "source:two", "source:three"],
    } };
    const output = { data: [[1], [3]], presentation_value: { sample_axis: {
      workflow_observation_refs: ["source:one", "source:three"], include_mask: [true, true],
    } }, metadata: { workflow_population: { outputs: { default: display } } } };
    expect([...observationOutputMembership(output)!]).toEqual([["source:one", true], ["source:three", true]]);
  });
  it("preserves recorded inclusion and refuses malformed alignment", () => {
    const sample_axis = { workflow_observation_refs: ["one", "two"], include_mask: [true, false] };
    expect([...observationOutputMembership({ data: [[1], [2]], presentation_value: { sample_axis } })!])
      .toEqual([["one", true], ["two", false]]);
    expect(observationOutputMembership({ data: [[1]], presentation_value: { sample_axis } })).toBeNull();
    expect(observationOutputMembership({ data: [[1], [2]], presentation_value: { sample_axis: {
      ...sample_axis, include_mask: [true, "false"],
    } } })).toBeNull();
  });
  it("does not infer specimen use from matching labels, shape, or input context", () => {
    expect(observationOutputMembership({ data: [[1], [2]], metadata: { sample_labels: ["Same", "Same"],
      observation_axis: { workflow_observation_refs: ["one", "two"] } },
      presentation_value: { sample_axis: { labels: ["Same", "Same"] } },
    })).toBeNull();
  });
  it("rejects display projections and previews smaller than a declared retained shape", () => {
    const output = { data: [[1], [2]], presentation_value: { sample_axis: { workflow_observation_refs: ["one", "two"] } } };
    expect(observationOutputMembership({ ...output, metadata: { workflow_population_projected: true } })).toBeNull();
    expect(observationOutputMembership({ ...output, descriptor: { shape: [3, 1] } })).toBeNull();
    expect(observationOutputMembership({ ...output, presentation_value: { ...output.presentation_value, shape: [3, 1] } })).toBeNull();
  });
  it("uses the declared paired T²/Q axis but never a coincident loading axis", () => {
    const metadata = { sample_labels: ["A", "B"], observation_axis: {
      workflow_observation_refs: ["one", "two"], include_mask: [true, true],
    }, scientific_presentation: { schema_version: "spectrasherpa-node-presentation/1", contract_digest: "a".repeat(64),
      presentation_id: "diagnostics", kind: "t2_q_diagnostics", source_port: "T2", source_ports: ["T2", "Q"], modes: ["plot", "table"] } };
    const output = { data: [1, 2], presentation_value: { T2: [1, 2], Q: [.1, .2] }, metadata };
    expect([...observationOutputMembership(output)!]).toEqual([["one", true], ["two", true]]);
    expect(observationOutputMembership({ ...output, metadata: { ...metadata, scientific_presentation: {
      ...metadata.scientific_presentation, kind: "pca_loadings",
    } } })).toBeNull();
  });
});
