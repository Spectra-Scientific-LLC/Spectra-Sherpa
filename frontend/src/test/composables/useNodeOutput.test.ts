import { describe, it, expect, vi } from "vitest";
import { ref } from "vue";
import {
  useNodeOutput,
  resolvePortPayload,
} from "@/views/workflow-builder/node-detail/composables/useNodeOutput";

vi.mock("@/utils/nodeOutput", () => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  buildNodeOutput: (result: any, ports: any) => ({ result, ports }),
}));

describe("resolvePortPayload", () => {
  it("returns primitives untouched", () => {
    expect(resolvePortPayload(42)).toBe(42);
    expect(resolvePortPayload("x")).toBe("x");
    expect(resolvePortPayload(null)).toBeNull();
    expect(resolvePortPayload(undefined)).toBeUndefined();
  });

  it("unwraps a {value} envelope", () => {
    expect(resolvePortPayload({ value: { foo: 1 } })).toEqual({ foo: 1 });
  });

  it("returns the object as-is when no value key exists", () => {
    expect(resolvePortPayload({ foo: 1 })).toEqual({ foo: 1 });
  });
});

describe("useNodeOutput", () => {
  it("normalizeNodeOutput forwards to buildNodeOutput with metadata.output_ports", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const nodeOutput = ref<any>(null);
    const nodeMetadata = ref({ output_ports: ["a", "b"] });
    const { normalizeNodeOutput } = useNodeOutput(nodeOutput, nodeMetadata);
    expect(normalizeNodeOutput({ x: 1 })).toEqual({ result: { x: 1 }, ports: ["a", "b"] });
  });

  it("primaryOutputPayload resolves the primary port value", () => {
    const nodeOutput = ref({
      primary_port: "scores",
      ports: { scores: { value: { shape: [10, 2] } } },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    }) as any;
    const nodeMetadata = ref({});
    const { primaryOutputPayload } = useNodeOutput(nodeOutput, nodeMetadata);
    expect(primaryOutputPayload.value).toEqual({ shape: [10, 2] });
  });

  it("primaryOutputPayload is null when no primary_port is set", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const nodeOutput = ref<any>({ ports: {} });
    const nodeMetadata = ref({});
    const { primaryOutputPayload } = useNodeOutput(nodeOutput, nodeMetadata);
    expect(primaryOutputPayload.value).toBeNull();
  });
});
