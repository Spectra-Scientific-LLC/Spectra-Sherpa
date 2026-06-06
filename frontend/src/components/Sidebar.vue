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
import { useDemoMode } from "@/composables/useDemoMode";

defineProps<{
  collapsed: boolean;
}>();

const { isDemoMode } = useDemoMode();

const mainNavItems = [
  { label: "Dashboard", to: "/dashboard", icon: "pi pi-home" },
  { label: "Project", to: "/project", icon: "pi pi-folder" },
  { label: "Data", to: "/data", icon: "pi pi-database" },
  { label: "Workflows", to: "/workflow", icon: "pi pi-sitemap" },
  { label: "Runs", to: "/runs", icon: "pi pi-history" },
  { label: "Deploy", to: "/deploy", icon: "pi pi-cloud-upload" },
  { label: "Report", to: "/report", icon: "pi pi-file-edit" },
];

const visibleMainNavItems = mainNavItems;

const secondaryNavItems = computed(() => [
  { label: "Logs", to: "/logs", icon: "pi pi-list", dimInDemo: false },
  { label: "Settings", to: "/settings", icon: "pi pi-sliders-h", dimInDemo: true },
  { label: "Documentation", to: "/documentation", icon: "pi pi-book", dimInDemo: false },
]);
</script>

<style scoped>
.sidebar {
  background: #1e293b;
  color: white;
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
  border-bottom: 1px solid #334155;
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
  color: #f1f5f9;
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
  background: #334155;
  color: white;
}

.nav-link.router-link-active {
  background: #3b82f6;
  color: white;
}

.nav-link i {
  font-size: 1.25rem;
  width: 24px;
  text-align: center;
}

.nav-label {
  font-size: 0.95rem;
  font-weight: 500;
}

.nav-separator {
  margin: 12px 8px;
  border-top: 1px solid #334155;
}

.nav-link.secondary {
  color: #64748b;
}

.nav-link.secondary:hover {
  color: #94a3b8;
}

.nav-link.secondary.router-link-active {
  background: #3b82f6;
  color: white;
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
