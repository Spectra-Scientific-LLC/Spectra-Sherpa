import { describe, expect, it } from "vitest";
import { modelSerializerDisclosure } from "@/utils/modelSerializerDisclosure";
describe("retained serialization layers", () => {
  it("distinguishes envelope and payload without modifying either", () => {
    const port = { value: { serializer: "mcr/2", metadata: { serializer: "mcr/1" } } };
    const original = JSON.stringify(port);
    expect(modelSerializerDisclosure(port)).toContain("Fitted-state envelope: mcr/2. Component payload: mcr/1.");
    expect(JSON.stringify(port)).toBe(original);
  });
  it("does not invent an envelope from payload metadata", () => {
    expect(modelSerializerDisclosure({ metadata: { serializer: "mcr/1" } })).toBeNull();
  });
});
