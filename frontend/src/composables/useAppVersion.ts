/**
 * App version composable
 *
 * Surfaces the running frontend bundle version (build-time-injected) and the
 * backend package version (fetched once from ``GET /version``).  Used by the
 * page footer and the About dialog so users can spot bundle drift after an
 * upgrade — e.g. they pulled a new package but their browser is still serving
 * a cached old bundle.
 */

import { ref, computed, readonly } from "vue";
import { api } from "@/api";

const frontendVersion = __SHERPA_FRONTEND_VERSION__;

const backendVersion = ref<string | null>(null);
const loadError = ref<string | null>(null);
let inflight: Promise<void> | null = null;

async function loadBackendVersion(): Promise<void> {
  if (backendVersion.value !== null) return;
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const response = await api.get<{ backend_version: string }>("/version");
      backendVersion.value = response.data.backend_version;
      loadError.value = null;
    } catch (err: unknown) {
      loadError.value = err instanceof Error ? err.message : "Failed to load backend version";
      backendVersion.value = null;
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

// Returns the major.minor portion of a semver string, or null on a malformed
// input.  Used for drift detection — we ignore patch (and pre-release tags)
// because patches shouldn't be flagged as a mismatch.
function majorMinor(v: string | null): string | null {
  if (!v) return null;
  const match = v.match(/^(\d+)\.(\d+)/);
  return match ? `${match[1]}.${match[2]}` : null;
}

const versionDrift = computed(() => {
  const feMm = majorMinor(frontendVersion);
  const beMm = majorMinor(backendVersion.value);
  if (!feMm || !beMm) return false;
  return feMm !== beMm;
});

export function useAppVersion() {
  // Fire-and-forget on first call.  Components mounting the footer will
  // trigger the fetch; subsequent callers reuse the cached value.
  void loadBackendVersion();

  return {
    frontendVersion,
    backendVersion: readonly(backendVersion),
    loadError: readonly(loadError),
    versionDrift,
    reload: () => loadBackendVersion(),
  };
}
