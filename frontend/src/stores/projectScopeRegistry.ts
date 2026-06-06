// Project-scope reset registry.
//
// Each project-scoped Pinia store self-registers a reset callback during its
// setup function. ``useProjectStore().selectProject(id)`` and
// ``deleteProject(activeId)`` call ``runProjectScopeResets()`` to clear stale
// state BEFORE loading the new project, so the UI never briefly renders a
// mixture of the previous and the next project's data.
//
// The registry lives in its own module (not in project.ts) so consumer stores
// can import it without creating a project.ts ↔ runs.ts / advisor.ts / etc.
// import cycle.
//
// Only stores that have been instantiated (``useXxxStore()`` called at least
// once) participate — that's the desired behaviour: a store with no live
// instance has no state to reset.

const callbacks = new Set<() => void>();

/**
 * Register a reset callback for a project-scoped store.
 *
 * Returns an unregister function — useful for component-level scopes and
 * test teardown. Pinia stores can ignore the return value; the registry
 * survives the lifetime of the app.
 */
export function registerProjectScopeReset(fn: () => void): () => void {
  callbacks.add(fn);
  return () => callbacks.delete(fn);
}

/**
 * Run every registered reset callback. Called by the project store when the
 * active project changes (selectProject) or is destroyed (deleteProject).
 *
 * Failures in individual callbacks are logged and swallowed — one buggy
 * store must not prevent the rest from clearing.
 */
export function runProjectScopeResets(): void {
  for (const fn of callbacks) {
    try {
      fn();
    } catch (err) {
      console.warn("[projectScope] reset callback failed", err);
    }
  }
}

/** Test-only — drop every registered callback. */
export function _clearProjectScopeRegistryForTests(): void {
  callbacks.clear();
}
