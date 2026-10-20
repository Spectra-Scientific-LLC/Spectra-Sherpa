import { ref } from "vue";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";
import type { ExperimentFile, ExperimentFileAssets, ScientificAsset } from "@/types";

export type InspectionSelection =
  | { kind: "file"; experimentId: number; file: ExperimentFile }
  | { kind: "experiment"; experimentId: number };

/** Inspection lifecycle and source inventory; scientific projections stay unchanged. */
export function useDatasetInspection(
  identity: () => readonly ScopeIdentity[],
  fetchAssets: (experimentId: number, fileId: number) => Promise<ExperimentFileAssets>,
) {
  const assets = ref<ScientificAsset[]>([]);
  const assetId = ref<string | null>(null);
  const warnings = ref<string[]>([]);
  const pending = ref<InspectionSelection | null>(null);
  const inventories = new Map<string, Promise<ExperimentFileAssets>>();
  const contents = useScopedRequest(identity, () => {
    assets.value = [];
    assetId.value = null;
    warnings.value = [];
    pending.value = null;
    inventories.clear();
  });
  const focus = useScopedRequest(identity);
  const selection = useScopedRequest(() => [...identity(), assetId.value]);

  function inventory(experimentId: number, fileId: number): Promise<ExperimentFileAssets> {
    const key = `${experimentId}:${fileId}`;
    const cached = inventories.get(key);
    if (cached) return cached;
    const request = fetchAssets(experimentId, fileId).catch((error) => {
      // An old rejection must not evict a replacement loaded after A → B → A.
      if (inventories.get(key) === request) inventories.delete(key);
      throw error;
    });
    inventories.set(key, request);
    return request;
  }

  return { assets, assetId, warnings, pending, inventories, inventory, contents, focus, selection };
}
