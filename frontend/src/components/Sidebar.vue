<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="sidebar-header">
      <img src="/logo.png" alt="Spectra Sherpa" class="sidebar-logo" />
      <h2 v-if="!collapsed">Spectra Sherpa</h2>
    </div>
    <nav class="nav-list" aria-label="Workspace navigation">
      <template v-for="group in navigationGroups" :key="group.id">
        <div v-if="group.id === 'secondary'" class="nav-separator"></div>
        <div v-for="item in group.items" :key="item.to" class="nav-group">
          <RouterLink
            class="nav-link"
            :class="{ secondary: group.id === 'secondary', 'nav-dimmed': item.dimInDemo && isDemoMode }"
            :to="item.to"
            :title="item.dimInDemo && isDemoMode ? 'Managed by administrator' : item.label"
            :aria-label="item.label"
            @click="emit('navigate')"
          >
            <i :class="item.icon" aria-hidden="true"></i>
            <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
          </RouterLink>
          <template v-if="hasSections(item.to)">
            <button v-if="collapsed" type="button" class="nav-expand"
              :aria-label="'Expand ' + item.label + ' sections'" :title="'Expand ' + item.label + ' sections'"
              :aria-expanded="false" @click="$emit('expand')">
              <i class="pi pi-angle-right" aria-hidden="true"></i>
            </button>
            <ul v-else class="nav-children" :aria-label="item.label + ' sections'">
              <li v-for="section in activeSections?.items" :key="section.id">
                <button type="button" class="nav-child"
                  :class="{ 'nav-child--active': activeSections?.selected === section.id }"
                  :aria-current="activeSections?.selected === section.id ? 'true' : undefined"
                  :aria-controls="section.panelId"
                  :disabled="section.disabled"
                  @click="selectSection(section.id)">
                  {{ section.label }}
                </button>
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
import { useRoute } from "vue-router";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDemoMode } from "@/composables/useDemoMode";
import { usePrimaryNavigation } from "@/composables/usePrimaryNavigation";
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
function hasSections(path: string): boolean {
  return !!activeSections.value?.items.length && (route.path === path || route.path.startsWith(path + "/"));
}
function selectSection(id: string): void {
  const entry = activeSections.value;
  if (!entry?.items.some((item) => item.id === id && !item.disabled)) return;
  entry.select(id);
  emit("navigate");
}

const { isDemoMode } = useDemoMode();
const { appMode, siteProfile } = useAppConfig();
const { items: contributedMainNavItems } = usePrimaryNavigation();

const mainNavItems = [
  { label: "Dashboard", to: "/dashboard", icon: "pi pi-home" },
  { label: "Project", to: "/project", icon: "pi pi-folder" },
  { label: "Data", to: "/data", icon: "pi pi-database" },
  { label: "Workflow", to: "/workflow", icon: "pi pi-sitemap" },
  { label: "Runs", to: "/runs", icon: "pi pi-history" },
  { label: "Deploy", to: "/deploy", icon: "pi pi-cloud-upload" },
  { label: "Report", to: "/report", icon: "pi pi-file-edit" },
];

const visibleMainNavItems = computed(() => {
  const result = [...mainNavItems];
  for (const item of contributedMainNavItems.value) {
    const duplicate = result.findIndex((existing) => existing.to === item.to);
    if (duplicate >= 0) result.splice(duplicate, 1);
    const insertion = item.before
      ? result.findIndex((existing) => existing.to === item.before)
      : -1;
    result.splice(insertion >= 0 ? insertion : result.length, 0, item);
  }
  return result;
});

const secondaryNavItems = computed(() => [
  ...(appMode.value === "enterprise" && (siteProfile?.value === "pro" ||
    (siteProfile?.value === "demo" && (!auth.user?.capabilities?.admin || auth.user?.is_active === false))) ? [] :
    [{ label: "Logs", to: "/logs", icon: "pi pi-list", dimInDemo: false }]),
  { label: "Settings", to: "/settings", icon: "pi pi-sliders-h", dimInDemo: true },
  { label: "Documentation", to: "/documentation", icon: "pi pi-book", dimInDemo: false },
]);
const navigationGroups = computed(() => [
  { id: "main", items: visibleMainNavItems.value.map((item) => ({ ...item, dimInDemo: false })) },
  { id: "secondary", items: secondaryNavItems.value },
]);
</script>

<style scoped>
.sidebar {
  background: #fefbff;
  color: #6504bd;
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
  border-bottom: 1px solid #e7e0ef;
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
  white-space: nowrap;
  color: #6504bd;
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
.nav-children {
  list-style: none;
  padding: 0 0 0.5rem 2.5rem;
  margin: 0;
}
.nav-child {
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
  position: absolute;
  right: 0;
  top: 0.5rem;
  min-width: 1.5rem;
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
  color: #475569;
  text-decoration: none;
  transition: background 0.15s ease, color 0.15s ease;
  white-space: nowrap;
}

.nav-link:hover {
  background: #f4edfa;
  color: #6504bd;
}

.nav-link.router-link-active {
  background: #fefbff;
  color: #6504bd;
}

.nav-link i {
  font-size: 1.25rem;
  width: 24px;
  text-align: center;
  color: #6504bd;
}

.nav-label {
  font-size: 0.95rem;
  font-weight: 500;
}

.nav-separator {
  margin: 12px 8px;
  border-top: 1px solid #e7e0ef;
}

.nav-link.secondary {
  color: #64748b;
}

.nav-link.secondary:hover {
  color: #6504bd;
}

.nav-link.secondary.router-link-active {
  background: #fefbff;
  color: #6504bd;
}

.collapsed .nav-link {
  justify-content: center;
  padding: 12px;
}

.collapsed .nav-link i {
  margin: 0;
}

.nav-dimmed {
  color: #64748b;
}

.nav-dimmed:hover {
  color: #6504bd;
}
.nav-link:focus-visible { outline: 2px solid #6504bd; outline-offset: -2px; }
.nav-child { color: #475569; }
</style>
