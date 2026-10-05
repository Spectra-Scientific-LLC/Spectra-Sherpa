import { isProxy, reactive, readonly } from "vue";
import { describe, expect, it } from "vitest";
import { cloneNodeDetailParams, resolveNodeDetailPayload } from "@/utils/nodeDetailPayload";

describe("resolveNodeDetailPayload", () => {
  it("uses the embedded in-memory payload without serializing it", () => {
    const payload: Record<string, unknown> = {
      id: "model_1",
      type: "model.fitted_pls",
    };
    payload.self = payload;
    expect(resolveNodeDetailPayload(payload, null)).toBe(payload);
  });

  it("parses the session-storage fallback for a separate browser tab", () => {
    expect(resolveNodeDetailPayload(null, '{"id":"model_1"}')).toEqual({ id: "model_1" });
  });

  it("rejects malformed payloads", () => {
    expect(() => resolveNodeDetailPayload([], null)).toThrow("must be an object");
  });

  it("clones reactive parameter objects without cloning Vue proxies", () => {
    const params = reactive({ n_components: 3, autoscale: true, nested: [1, 2] });

    const cloned = cloneNodeDetailParams(params);

    expect(cloned).toEqual({ n_components: 3, autoscale: true, nested: [1, 2] });
    expect(cloned).not.toBe(params);
    expect(cloned.nested).not.toBe(params.nested);
  });

  it("clones target names after the detail view merges defaults with reactive parameters", () => {
    const params = reactive({ target_names: ["Weight"] });
    const merged = { ...params };
    expect(isProxy(merged.target_names)).toBe(true);
    const cloned = cloneNodeDetailParams(merged);
    expect(cloned).toEqual({ target_names: ["Weight"] });
    expect(isProxy(cloned.target_names)).toBe(false);
    expect(() => structuredClone(cloned)).not.toThrow();
    cloned.target_names[0] = "Other";
    expect(params.target_names).toEqual(["Weight"]);
  });

  it("copies nested proxies and readonly defaults without altering parameter values", () => {
    const params = {
      rules: [reactive({ columns: readonly(["a", "b"]), threshold: null })],
      unset: undefined,
      invalid: NaN,
    };
    const cloned = cloneNodeDetailParams(params);
    expect(cloned).toEqual(params);
    expect(isProxy(cloned.rules[0])).toBe(false);
    expect(isProxy(cloned.rules[0].columns)).toBe(false);
    expect(cloned.rules[0].columns).not.toBe(params.rules[0].columns);
    expect(Object.hasOwn(cloned, "unset")).toBe(true);
    expect(Number.isNaN(cloned.invalid)).toBe(true);
  });
});
