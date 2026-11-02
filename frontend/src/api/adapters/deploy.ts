import type { components } from "@/types/api/v1";
import type { DeployApplication, FolderWatch } from "@/types";

/** Trust is recorded at import; absence never means unsigned or approved. */
export function packageTrust(provenance: unknown): DeployApplication["package_trust"] {
  if (!provenance || typeof provenance !== "object") return null;
  const trust = (provenance as Record<string, unknown>).package_trust;
  if (!trust || typeof trust !== "object") return null;
  const value = trust as Record<string, unknown>;
  if (value.status === "unsigned") return "unsigned";
  if (value.status === "verified" && typeof value.authentication_digest === "string"
    && /^[a-f0-9]{64}$/.test(value.authentication_digest)) return "verified";
  return "unverified";
}

/** Keep transport ownership explicit even where the current view is lossless. */
export function folderWatch(value: components["schemas"]["FolderWatchOut"]): FolderWatch {
  return { ...value };
}
