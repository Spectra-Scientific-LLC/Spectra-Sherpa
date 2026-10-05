type FilenameCapability = {
  readonly acceptedExtensions: readonly string[];
  readonly acceptedFilenamePatterns: readonly string[];
};

/** Match a filename only against the backend-generated ingestion capability. */
export function filenameAcceptedByCapabilities(
  filename: string,
  capability: FilenameCapability | null | undefined,
): boolean {
  if (!capability) return false;
  const normalized = filename.toLowerCase();
  if (capability.acceptedExtensions.some((extension) => normalized.endsWith(extension))) {
    return true;
  }
  const suffix = normalized.slice(normalized.lastIndexOf(".") + 1);
  return capability.acceptedFilenamePatterns.includes("numeric-extension") && /^\d+$/.test(suffix);
}
