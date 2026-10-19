import { describe, expect, it } from "vitest";
import { componentInputHint } from "@/utils/componentInputHint";
import type { NodePresentationContract } from "@/types";

const contract = { payload: { presentations: [{
  kind: "validation_result", presentation_id: "component_selection", source_ports: ["component_curve"],
}] } } as NodePresentationContract;

describe("contract-owned component input hints", () => {
  it("does not invent a hint for an absent presentation", () => {
    expect(componentInputHint(null, [])).toBeNull();
  });
  it("distinguishes no partition, training pairs and held-out or crossed pairs", () => {
    expect(componentInputHint(contract, [])?.splitRole).toBe("none");
    const edge = { nodeType: "data.train_test_split", port: "X_train", toPort: "X" };
    expect(componentInputHint(contract, [edge])?.splitRole).toBe("train");
    expect(componentInputHint(contract, [edge, { ...edge, port: "y_train", toPort: "y" }])?.splitRole).toBe("train");
    expect(componentInputHint(contract, [{ ...edge, port: "X_test" }])?.splitRole).toBe("other");
    expect(componentInputHint(contract, [edge, { ...edge, port: "y_test", toPort: "y" }])?.splitRole).toBe("other");
  });
});
