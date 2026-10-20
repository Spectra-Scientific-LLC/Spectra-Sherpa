import type { components } from "@/types/api/v1";
import type { FolderWatch } from "@/types";

/** Keep transport ownership explicit even where the current view is lossless. */
export function folderWatch(value: components["schemas"]["FolderWatchOut"]): FolderWatch {
  return { ...value };
}
