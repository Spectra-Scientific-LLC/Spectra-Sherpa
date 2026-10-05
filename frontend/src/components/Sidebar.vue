<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="sidebar-header">
      <img src="/logo.png" alt="Spectra Sherpa" class="sidebar-logo" />
      <h2 v-if="!collapsed">Spectra Sherpa</h2>
    </div>
    <nav class="nav-list">
      <!-- Main Navigation -->
      <RouterLink
        v-for="item in visibleMainNavItems"
        :key="item.to"
        class="nav-link"
        :to="item.to"
        :title="item.label"
        :aria-label="item.label"
      >
        <i :class="item.icon" aria-hidden="true"></i>
        <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
      </RouterLink>

      <!-- Separator -->
      <div class="nav-separator"></div>

      <!-- Secondary Navigation -->
      <RouterLink
        v-for="item in secondaryNavItems"
        :key="item.to"
        class="nav-link secondary"
        :class="{ 'nav-dimmed': item.dimInDemo && isDemoMode }"
        :to="item.to"
        :title="item.dimInDemo && isDemoMode ? 'Managed by administrator' : item.label"
        :aria-label="item.label"
      >
        <i :class="item.icon" aria-hidden="true"></i>
        <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
      </RouterLink>
    </nav>
  </aside>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDemoMode } from "@/composables/useDemoMode";
import { usePrimaryNavigation } from "@/composables/usePrimaryNavigation";

defineProps<{
  collapsed: boolean;
}>();

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
  ...(appMode.value === "enterprise" && siteProfile?.value === "pro" ? [] :
    [{ label: "Logs", to: "/logs", icon: "pi pi-list", dimInDemo: false }]),
  { label: "Settings", to: "/settings", icon: "pi pi-sliders-h", dimInDemo: true },
  { label: "Documentation", to: "/documentation", icon: "pi pi-book", dimInDemo: false },
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
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 8px;
  color: #94a3b8;
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
  color: #94a3b8;
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
  opacity: 0.4;
}

.nav-dimmed:hover {
  opacity: 0.6;
}
</style>
