/**
 * Remember a workspace's last sub-tab per user and project.
 *
 * The tab is stored by id, never by position, so adding or reordering tabs
 * cannot restore the wrong one. A stored value is used only when it is still
 * one of the current tabs and `restorable` allows it (a tab that needs context,
 * such as a selected run, is not reopened empty). A tab named in the URL always
 * wins over the remembered one. Storage may be unavailable; reading then
 * returns null and writing does nothing.
 */
export function readRememberedTab<T extends string>(
  storageKey: string,
  tabIds: readonly T[],
  restorable: (id: T) => boolean = () => true,
): T | null {
  try {
    const stored = localStorage.getItem(storageKey);
    const id = tabIds.find((tab) => tab === stored);
    return id !== undefined && restorable(id) ? id : null;
  } catch {
    return null;
  }
}

export function writeRememberedTab(storageKey: string, id: string): void {
  try {
    localStorage.setItem(storageKey, id);
  } catch {
    /* Storage may be unavailable; the tab simply is not remembered. */
  }
}

/** The tab to open: the URL's when valid, else the remembered one, else the default. */
export function initialTab<T extends string>(
  urlTab: unknown,
  remembered: T | null,
  tabIds: readonly T[],
  fallback: T,
): T {
  const fromUrl = tabIds.find((tab) => tab === urlTab);
  return fromUrl ?? remembered ?? fallback;
}
