<template>
  <aside class="sidebar" :class="{ collapsed }">
    <div class="sidebar-header">
      <h2 v-if="!collapsed">Spectra Platform</h2>
      <div v-else class="sidebar-mark">SP</div>
    </div>
    <nav class="nav-list">
      <!-- Workspace (Main Hub) -->
      <RouterLink
        class="nav-link workspace-link"
        to="/workspace"
        title="Workspace"
        aria-label="Workspace"
      >
        <i class="pi pi-th-large" aria-hidden="true"></i>
        <span v-if="!collapsed" class="nav-label">Workspace</span>
      </RouterLink>

      <!-- Operations Section -->
      <div class="nav-section">
        <span v-if="!collapsed" class="nav-section-label">Operations</span>
        <RouterLink
          v-for="item in operationsNavItems"
          :key="item.to"
          class="nav-link"
          :to="item.to"
          :title="item.label"
          :aria-label="item.label"
        >
          <i :class="item.icon" aria-hidden="true"></i>
          <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
        </RouterLink>
      </div>

      <!-- Templates -->
      <div class="nav-section">
        <RouterLink
          class="nav-link"
          to="/templates"
          title="Templates"
          aria-label="Templates"
        >
          <i class="pi pi-file" aria-hidden="true"></i>
          <span v-if="!collapsed" class="nav-label">Templates</span>
        </RouterLink>
      </div>

      <!-- Separator -->
      <div class="nav-separator"></div>

      <!-- Secondary Navigation -->
      <RouterLink
        v-for="item in secondaryNavItems"
        :key="item.to"
        class="nav-link secondary"
        :to="item.to"
        :title="item.label"
        :aria-label="item.label"
      >
        <i :class="item.icon" aria-hidden="true"></i>
        <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
      </RouterLink>
    </nav>
  </aside>
</template>

<script setup lang="ts">
defineProps<{
  collapsed: boolean;
}>();

// Operations section
const operationsNavItems = [
  { label: "Calibration", to: "/operations/calibration", icon: "pi pi-sliders-v" },
  { label: "Process", to: "/operations/process", icon: "pi pi-cog" },
  { label: "Analysis", to: "/operations/analysis", icon: "pi pi-chart-line" },
];

// Secondary navigation
const secondaryNavItems = [
  { label: "Settings", to: "/settings", icon: "pi pi-sliders-h" },
];
</script>

<style scoped>
.sidebar {
  background: #1e293b;
  color: white;
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
  width: var(--nav-width, 240px);
  flex-shrink: 0;
}

.sidebar.collapsed {
  width: 72px;
}

.sidebar-header {
  padding: 20px;
  border-bottom: 1px solid #334155;
}

.sidebar-header h2 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  white-space: nowrap;
}

.sidebar-mark {
  font-size: 1.25rem;
  font-weight: 700;
  text-align: center;
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

.nav-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 8px;
}

.nav-section-label {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  padding: 8px 16px 4px;
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
  background: #334155;
  color: white;
}

.collapsed .nav-link {
  justify-content: center;
  padding: 12px;
}

.collapsed .nav-link i {
  margin: 0;
}

/* Workspace link - primary hub */
.workspace-link {
  font-weight: 600;
  margin-bottom: 12px;
}

.workspace-link i {
  font-size: 1.35rem;
}
</style>
