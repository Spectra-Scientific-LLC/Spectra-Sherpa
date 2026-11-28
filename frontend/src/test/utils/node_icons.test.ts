import { describe, expect, it } from "vitest";
import { nodeIcon, paletteLabel } from "@/utils/nodeIcons";

describe("node palette presentation", () => {
  it("gives every node an icon from its own entry, its category or its family, never a placeholder", () => {
    expect(nodeIcon("data.file_load")).toBe("📂");
    expect(nodeIcon("model.fitted_pcr", "modeling")).not.toBe("📦");
    expect(nodeIcon("transfer.ds")).toBe("🔁");
    expect(nodeIcon("unknown.thing")).toBe("⚙️");
  });

  it("drops version tags and citations from palette names only", () => {
    expect(paletteLabel("Reference Regression Evaluator (v2)")).toBe("Reference Regression Evaluator");
    expect(paletteLabel("SPA-MLR Variable Selection (Araújo 2001)")).toBe("SPA-MLR Variable Selection");
    expect(paletteLabel("Apply Reference MSC (Imported)")).toBe("Apply Reference MSC (Imported)");
  });
});
