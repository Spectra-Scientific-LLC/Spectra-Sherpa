import { describe, expect, it } from "vitest";
import { isUserEditableNodeParameter } from "@/utils/nodeParameterVisibility";

describe("node parameter visibility", () => {
  it("hides artifact and execution contract fields from editable settings", () => {
    for (const name of [
      "artifact_digest",
      "serializer",
      "source_contract_digest",
      "state_content_digest",
    ]) {
      expect(isUserEditableNodeParameter({ name })).toBe(false);
    }
  });

  it("keeps scientific controls editable", () => {
    expect(isUserEditableNodeParameter({ name: "n_components", category: "model" })).toBe(true);
  });

  it("honors metadata that explicitly marks a parameter internal", () => {
    expect(isUserEditableNodeParameter({ name: "custom_field", category: "internal" })).toBe(
      false,
    );
  });
});
