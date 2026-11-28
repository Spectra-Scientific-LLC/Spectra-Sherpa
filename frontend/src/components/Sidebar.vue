<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="sidebar-header">
      <img src="/logo.png" alt="Spectra Sherpa" class="sidebar-logo" />
      <h2 v-if="!collapsed">Spectra Sherpa</h2>
    </div>
    <nav class="nav-list" aria-label="Workspace navigation">
      <template v-for="group in navigationGroups" :key="group.id">
        <div v-if="group.id === 'secondary'" class="nav-separator"></div>
        <div
          v-for="item in group.items"
          :key="item.id"
          class="nav-group"
          :class="{ 'nav-group--sections': hasSections(item.id) }"
        >
          <RouterLink
            class="nav-link"
            :class="{ secondary: group.id === 'secondary', 'nav-dimmed': item.dimInDemo && isDemoMode, 'router-link-active': activePage?.id === item.id }"
            :to="workspaceDestination(item.route, route)"
            :title="item.dimInDemo && isDemoMode ? 'Managed by administrator' : item.label"
            :aria-label="item.label"
            @click="emit('navigate')"
          >
            <i :class="item.icon" aria-hidden="true"></i>
            <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
          </RouterLink>
          <template v-if="hasSections(item.id)">
            <button
              v-if="collapsed" type="button" class="nav-expand"
              :aria-label="'Expand ' + item.label + ' sections'" :title="'Expand ' + item.label + ' sections'"
              :aria-expanded="false" @click="$emit('expand')">
              <i class="pi pi-angle-right" aria-hidden="true"></i>
            </button>
            <ul v-else class="nav-children" :aria-label="item.label + ' sections'">
              <li v-for="section in activePageSections" :key="section.id">
                <button v-if="legacySection(section.entry.id)"
                  type="button" class="nav-child"
                  :class="{ 'nav-child--active': isActiveSection(section) }"
                  :aria-current="isActiveSection(section) ? 'true' : undefined"
                  :aria-controls="legacySection(section.entry.id)?.panelId"
                  :disabled="legacySection(section.entry.id)?.disabled"
                  @click="selectLegacySection(section.entry.id)">
                  {{ section.entry.label }}
                </button>
                <RouterLink v-else class="nav-child"
                  :class="{ 'nav-child--active': isActiveSection(section) }"
                  :to="workspaceDestination(section.entry.route, route)"
                  @click="emit('navigate')">{{ section.entry.label }}</RouterLink>
                <ul v-if="isActiveSection(section) && section.views.length" class="nav-views" :aria-label="`${section.entry.label} views`">
                  <li v-for="view in section.views" :key="view.id">
                    <RouterLink class="nav-child"
                      :to="workspaceDestination(view.entry.route, route)"
                      :aria-current="isActiveView(view.entry.route, section.entry.route) ? 'page' : undefined"
                      :class="{ 'nav-child--active': isActiveView(view.entry.route, section.entry.route) }"
                      @click="emit('navigate')">{{ view.entry.label }}</RouterLink>
                  </li>
                </ul>
              </li>
            </ul>
          </template>
        </div>
      </template>
    </nav>
  </aside>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useAuthStore } from "@/stores/auth";
import { useRoute, type RouteLocationRaw } from "vue-router";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDemoMode } from "@/composables/useDemoMode";
import { navigationPage, navigationRegistry, routePath, workspaceDestination, workspaceView } from "@/navigation/workspace";
import type { NavSection } from "@/extension-contract/navigation-v1";
import type { Owned } from "@/navigation/registry";
import { navigationTab } from "@/router/legacyRoutes";
import { useWorkspaceNavigation } from "@/composables/useWorkspaceNavigation";

defineProps<{
  collapsed: boolean;
}>();
const emit = defineEmits<{ expand: []; navigate: [] }>();

const route = useRoute();
const auth = useAuthStore();
const navigation = useWorkspaceNavigation();
const activeSections = computed(() => {
  const entry = navigation?.entry.value;
  return entry?.path === route.path ? entry : null;
});
const activePage = computed(() => navigationPage(route.path));
function hasSections(id: string): boolean {
  return activePage.value?.id === id && activePageSections.value.length > 0;
}
function legacySection(id: string) {
  return activeSections.value?.items.find((item) => `${activePage.value?.entry.id}.${item.id}` === id);
}
function isActiveSection(section: Owned<NavSection>): boolean {
  const item = legacySection(section.entry.id);
  if (item) return item.id === activeSections.value?.selected;
  const target = section.entry.route;
  return routePath(target) === route.path &&
    (typeof target === "string" || !("query" in target) || !target.query?.section || target.query.section === navigationTab(route.query));
}
function isActiveView(target: RouteLocationRaw, section: RouteLocationRaw): boolean {
  const view = workspaceView(target);
  return view != null && routePath(target) === route.path && view === (route.query.view ?? workspaceView(section));
}
function selectLegacySection(id: string): void {
  const item = legacySection(id);
  if (!item || item.disabled) return;
  activeSections.value?.select(item.id);
  emit("navigate");
}

const { isDemoMode } = useDemoMode();
const { appMode, siteProfile, appConfig } = useAppConfig();
const activePageSections = computed(() => {
  const audit = appConfig?.value?.audit;
  const showAudit = !["demo", "pro"].includes(siteProfile?.value ?? "") && (audit?.localQuery || audit?.fullPipeline);
  return activePage.value?.sections.filter(({ id }) => id !== "host:project.audit" || showAudit) ?? [];
});
const secondary = new Set(["logs", "settings", "documentation"]);
const navigationGroups = computed(() => {
  const showLogs = !(appMode.value === "enterprise" && (siteProfile?.value === "pro" ||
    (siteProfile?.value === "demo" && (!auth.user?.capabilities?.admin || auth.user?.is_active === false))));
  const items = navigationRegistry.tree()
    .filter((page) => page.id !== "host:logs" || showLogs)
    .map((page) => ({ ...page.entry, id: page.id, dimInDemo: page.id === "host:settings" }));
  return [
    { id: "main", items: items.filter((page) => !secondary.has(page.id.slice(5)) || !page.id.startsWith("host:")) },
    { id: "secondary", items: items.filter((page) => page.id.startsWith("host:") && secondary.has(page.id.slice(5))) },
  ];
});
</script>

<style scoped>
.sidebar {
  background: var(--ss-workspace-paper);
  color: var(--ss-accent);
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
  width: var(--nav-width, 224px);
  flex-shrink: 0;
  padding: 0;
  gap: 0;
}

.sidebar.collapsed {
  width: 72px;
  padding: 0;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  padding: 0 16px;
  min-height: 56px;
  max-height: 56px;
  border-bottom: 1px solid var(--ss-accent-border);
}

.collapsed .sidebar-header {
  justify-content: center;
  padding: 0 12px;
}

.sidebar-logo {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
}

.sidebar-header h2 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  line-height: 1.1;
  color: var(--ss-accent);
}

.nav-list {
  display: flex;
  flex-direction: column;
  padding: 12px 8px;
  gap: 4px;
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.nav-group { position: relative; }
/* Keep the section disclosure out of the page link's pointer target. */
.collapsed .nav-group--sections {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 24px;
  align-items: center;
}
.collapsed .nav-group--sections .nav-link { grid-column: 1; }
.nav-children {
  list-style: none;
  padding: 0 0 0.5rem 2.5rem;
  margin: 0;
}
.nav-views { list-style: none; padding-inline-start: .65rem; }
.nav-child {
  text-decoration: none;
  display: block;
  width: 100%;
  padding: 0.55rem 0.75rem;
  border: 0;
  border-left: 2px solid var(--surface-border);
  border-radius: 0 6px 6px 0;
  background: transparent;
  color: var(--text-color-secondary);
  text-align: left;
  font: inherit;
  font-size: 0.875rem;
  line-height: 1.35;
  cursor: pointer;
}
.nav-child:hover:not(:disabled), .nav-child--active {
  color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 8%, transparent);
}
.nav-child--active { border-left-color: var(--primary-color); font-weight: 600; }
.nav-child:disabled { opacity: 0.5; cursor: not-allowed; }
.nav-child:focus-visible, .nav-expand:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: -2px;
}
.nav-expand {
  grid-column: 2;
  grid-row: 1;
  min-width: 24px;
  min-height: 2rem;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--primary-color);
  cursor: pointer;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 8px;
  color: var(--ss-text-secondary);
  text-decoration: none;
  transition: background 0.15s ease, color 0.15s ease;
  white-space: nowrap;
}

.nav-link:hover {
  background: var(--ss-accent-faint);
  color: var(--ss-accent);
}

.nav-link.router-link-active {
  background: var(--ss-workspace-paper);
  color: var(--ss-accent);
}

.nav-link i {
  font-size: 1.25rem;
  width: 24px;
  text-align: center;
  color: var(--ss-accent);
}

.nav-label {
  font-size: 0.95rem;
  font-weight: 500;
}

.nav-separator {
  margin: 12px 8px;
  border-top: 1px solid var(--ss-accent-border);
}

.nav-link.secondary {
  color: var(--ss-text-muted);
}

.nav-link.secondary:hover {
  color: var(--ss-accent);
}

.nav-link.secondary.router-link-active {
  background: var(--ss-workspace-paper);
  color: var(--ss-accent);
}

.collapsed .nav-link {
  justify-content: center;
  padding: 12px 4px;
}

.collapsed .nav-link i {
  margin: 0;
}

.nav-dimmed {
  color: var(--ss-text-muted);
}

.nav-dimmed:hover {
  color: var(--ss-accent);
}
.nav-link:focus-visible { outline: 2px solid var(--ss-accent); outline-offset: -2px; }
.nav-views { list-style: none; padding-inline-start: .65rem; }
.nav-child {
  text-decoration: none; color: var(--ss-text-secondary); }
</style>
