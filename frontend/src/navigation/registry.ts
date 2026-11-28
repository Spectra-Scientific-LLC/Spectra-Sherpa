import { shallowRef, type ShallowRef } from "vue";
import type { RouteLocationRaw } from "vue-router";
import type {
  NavActionContext, NavigationContribution, NavPage, NavPrimaryAction, NavScope, NavSection, NavView,
} from "@/extension-contract/navigation-v1";

export interface Owned<T> {
  id: string;
  contributor: string;
  entry: Readonly<T>;
  revision: number;
}

interface Registration {
  contributor: string;
  projectScoped: boolean;
  current: () => boolean;
  pages: Owned<NavPage>[];
  sections: Owned<NavSection>[];
  views: Owned<NavView>[];
  actions: Owned<NavPrimaryAction>[];
  controller: AbortController;
}

export interface NavigationSnapshot {
  context: Readonly<NavActionContext>;
  contributor: string;
  /** Changes whenever the selected location or verified object changes. */
  locationKey: string;
  isCurrent(): boolean;
  signal?: AbortSignal;
}

export interface NavigationInvocation {
  id: string;
  locationKey: string;
  revision: number;
}

const idPattern = /^[\w.-]+$/;
const cloneRoute = (route: RouteLocationRaw): RouteLocationRaw =>
  typeof route === "string" ? route : Object.freeze({
    ...route,
    ...("query" in route && route.query ? { query: Object.freeze({ ...route.query }) } : {}),
    ...("params" in route && route.params ? { params: Object.freeze({ ...route.params }) } : {}),
  });

function own<T extends { id: string; route?: RouteLocationRaw }>(contributor: string, entry: T, revision: number): Owned<T> {
  if (!idPattern.test(entry.id)) throw new Error(`Invalid navigation ID: ${entry.id}`);
  const copy = entry.route ? { ...entry, route: cloneRoute(entry.route) } : { ...entry };
  return Object.freeze({ id: `${contributor}:${entry.id}`, contributor, entry: Object.freeze(copy), revision });
}

const scopeKey = (scope: NavScope) => JSON.stringify([scope.pageId, scope.sectionId, scope.viewId]);

export function createNavigationRegistry() {
  const registrations: ShallowRef<Registration[]> = shallowRef([]);
  let nextRevision = 0;
  const active = () => registrations.value.filter((record) => record.current());

  function register(contributor: string, contribution: NavigationContribution, current = () => true): () => void {
    if (!/^[\w.:-]+$/.test(contributor)) throw new Error(`Invalid navigation contributor: ${contributor}`);
    if (!current()) return () => {};
    const revision = ++nextRevision;
    const registration: Registration = {
      contributor, current, projectScoped: contribution.projectScoped === true, controller: new AbortController(),
      pages: (contribution.pages ?? []).map((item) => own(contributor, item, revision)),
      sections: (contribution.sections ?? []).map((item) => own(contributor, item, revision)),
      views: (contribution.views ?? []).map((item) => own(contributor, item, revision)),
      actions: (contribution.primaryActions ?? []).map((item) => own(contributor, {
        ...item, scope: Object.freeze({ ...item.scope }),
      }, revision)),
    };
    const records = [...active().filter((record) => record.contributor === contributor), registration];
    const entities = records.flatMap((record) => [...record.pages, ...record.sections, ...record.views, ...record.actions]);
    if (new Set(entities.map((item) => item.id)).size !== entities.length) {
      throw new Error(`Duplicate navigation ID for ${contributor}`);
    }
    const pages = new Set(records.flatMap((record) => record.pages.map((page) => page.entry.id)));
    const sections = new Map(records.flatMap((record) => record.sections.map((section) => [section.entry.id, section.entry.pageId])));
    const views = new Map(records.flatMap((record) => record.views.map((view) => [view.entry.id, view.entry.sectionId])));
    const actionScopes = records.flatMap((record) => record.actions.map((action) => scopeKey(action.entry.scope)));
    if (new Set(actionScopes).size !== actionScopes.length) {
      throw new Error(`Duplicate navigation action scope for ${contributor}`);
    }
    if (registration.sections.some(({ entry }) => !pages.has(entry.pageId))
      || registration.views.some(({ entry }) => !sections.has(entry.sectionId))
      || registration.actions.some(({ entry: { scope } }) => !pages.has(scope.pageId)
        || (scope.sectionId != null && sections.get(scope.sectionId) !== scope.pageId)
        || (scope.viewId != null && (!scope.sectionId || views.get(scope.viewId) !== scope.sectionId)))) {
      throw new Error(`Unknown navigation parent for ${contributor}`);
    }
    registrations.value = [...registrations.value, registration];
    return () => dispose(registration);
  }

  function dispose(record: Registration): void {
    if (!registrations.value.includes(record)) return;
    registrations.value = registrations.value.filter((candidate) => candidate !== record);
    record.controller.abort();
  }

  function disposeProjectScoped(): void {
    for (const record of registrations.value.filter((item) => item.projectScoped)) dispose(record);
  }

  function tree() {
    const all = active();
    const registeredPages = all.flatMap((record) => record.pages);
    const before = new Map<string, Owned<NavPage>[]>();
    for (const page of registeredPages) {
      const target = registeredPages.find((candidate) => candidate.id !== page.id
        && candidate.entry.id === page.entry.before && candidate.contributor === page.contributor)
        ?? registeredPages.find((candidate) => candidate.id !== page.id
          && candidate.entry.id === page.entry.before && candidate.contributor === "host");
      if (target) before.set(target.id, [...(before.get(target.id) ?? []), page]);
    }
    const pages: Owned<NavPage>[] = [];
    const visited = new Set<string>();
    function insert(page: Owned<NavPage>): void {
      if (visited.has(page.id)) return;
      visited.add(page.id);
      for (const preceding of before.get(page.id) ?? []) insert(preceding);
      pages.push(page);
    }
    const positioned = new Set([...before.values()].flat().map((page) => page.id));
    for (const page of registeredPages) if (!positioned.has(page.id)) insert(page);
    for (const page of registeredPages) insert(page);
    return pages.map((page) => ({
      ...page,
      sections: all.flatMap((record) => record.sections)
        .filter((section) => section.contributor === page.contributor && section.entry.pageId === page.entry.id)
        .map((section) => ({
          ...section,
          views: all.flatMap((record) => record.views)
            .filter((view) => view.contributor === section.contributor && view.entry.sectionId === section.entry.id),
        })),
    }));
  }

  function primary(snapshot: NavigationSnapshot): Owned<NavPrimaryAction> | undefined {
    if (!snapshot.isCurrent()) return undefined;
    const { context } = snapshot;
    const actions = active().filter((record) => record.contributor === snapshot.contributor)
      .flatMap((record) => record.actions)
      .filter((action) => action.entry.scope.pageId === context.pageId);
    const scopes: NavScope[] = [];
    if (context.viewId) scopes.push(context);
    if (context.sectionId) scopes.push({ pageId: context.pageId, sectionId: context.sectionId });
    scopes.push({ pageId: context.pageId });
    for (const scope of scopes) {
      const action = actions.find((item) => scopeKey(item.entry.scope) === scopeKey(scope));
      if (action?.entry.available(context)) return action;
    }
  }

  async function invoke(expected: NavigationInvocation, snapshot: NavigationSnapshot): Promise<boolean> {
    if (expected.locationKey !== snapshot.locationKey || snapshot.signal?.aborted) return false;
    const action = primary(snapshot);
    if (!action || action.id !== expected.id || action.revision !== expected.revision || action.entry.disabled?.(snapshot.context)) return false;
    const record = active().find((item) => item.actions.includes(action));
    if (!record || !snapshot.isCurrent()) return false;
    const controller = new AbortController();
    const abort = () => controller.abort();
    const signals = [record.controller.signal, snapshot.signal].filter((signal): signal is AbortSignal => !!signal);
    for (const signal of signals) signal.addEventListener("abort", abort, { once: true });
    try {
      await action.entry.execute(snapshot.context, controller.signal);
      return !controller.signal.aborted && snapshot.isCurrent();
    } finally {
      for (const signal of signals) signal.removeEventListener("abort", abort);
    }
  }

  function serialize(resolve: (route: RouteLocationRaw) => string, snapshot: NavigationSnapshot) {
    const action = primary(snapshot);
    return {
      pages: tree().map((page) => ({
        id: page.id, label: page.entry.label, icon: page.entry.icon, href: resolve(page.entry.route),
        sections: page.sections.map((section) => ({
          id: section.id, label: section.entry.label, href: resolve(section.entry.route),
          views: section.views.map((view) => ({
            id: view.id, label: view.entry.label, href: resolve(view.entry.route),
          })),
        })),
      })),
      primary: action ? {
        id: action.id, revision: action.revision, label: action.entry.label, accelerator: action.entry.accelerator,
        disabled: action.entry.disabled?.(snapshot.context) ?? false, locationKey: snapshot.locationKey,
      } : null,
    };
  }

  return { register, tree, primary, invoke, serialize, disposeProjectScoped };
}
