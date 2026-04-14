import { describe, it, expect } from "vitest";
import { ref, computed } from "vue";
import { useNodeValidation } from "@/views/workflow-builder/node-detail/composables/useNodeValidation";

type Fake = {
  isLoadingNodeLibrary: boolean;
  nodeLibraryLoadError: unknown;
  nodeLibrary: Map<string, unknown>;
  validateNodeParams: (t: string, p: Record<string, unknown>) => Array<{ param_name: string; message: string }>;
};

function makeStore(overrides: Partial<Fake> = {}): Fake {
  return {
    isLoadingNodeLibrary: false,
    nodeLibraryLoadError: null,
    nodeLibrary: new Map([["data.source", {}]]),
    validateNodeParams: () => [],
    ...overrides,
  };
}

describe("useNodeValidation", () => {
  it("returns empty errors when nodeType is falsy", () => {
    const store = makeStore();
    const nodeType = computed(() => "");
    const params = ref({});
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const v = useNodeValidation(store as any, nodeType, params);
    v.validateParams();
    expect(v.validationErrors.value).toEqual([]);
  });

  it("skips validation while node library is loading", () => {
    const store = makeStore({ isLoadingNodeLibrary: true, validateNodeParams: () => [{ param_name: "x", message: "bad" }] });
    const nodeType = computed(() => "data.source");
    const params = ref({});
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const v = useNodeValidation(store as any, nodeType, params);
    v.validateParams();
    expect(v.validationErrors.value).toEqual([]);
  });

  it("skips validation when node library failed to load", () => {
    const store = makeStore({ nodeLibraryLoadError: new Error("fail"), validateNodeParams: () => [{ param_name: "x", message: "bad" }] });
    const nodeType = computed(() => "data.source");
    const params = ref({});
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const v = useNodeValidation(store as any, nodeType, params);
    v.validateParams();
    expect(v.validationErrors.value).toEqual([]);
  });

  it("filters _metadata errors from display and excludes them from getParamError", () => {
    const errors = [
      { param_name: "_metadata", message: "internal" },
      { param_name: "n_components", message: "must be >= 1" },
    ];
    const store = makeStore({ validateNodeParams: () => errors });
    const nodeType = computed(() => "model.pca");
    const params = ref({ n_components: 0 });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const v = useNodeValidation(store as any, nodeType, params);
    v.validateParams();
    expect(v.displayedValidationErrors.value.map((e) => e.param_name)).toEqual(["n_components"]);
    expect(v.hasValidationErrors.value).toBe(true);
    expect(v.getParamError("n_components")).toBe("must be >= 1");
    expect(v.getParamError("_metadata")).toBeNull();
    expect(v.getParamError("missing")).toBeNull();
  });
});
