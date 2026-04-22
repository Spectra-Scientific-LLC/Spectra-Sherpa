<template>
  <!--
    Fail-closed overlay: when a server-provided frontend module fails
    to load in a server-backed deployment, stop rendering the app
    entirely. Falling through would expose protected views (chat,
    workflow) without identity. The user's only remediation path is
    to retry the page — the underlying fetch/register failure is a
    deployment problem, not a client-state problem.
  -->
  <div v-if="serverModuleLoadFailed" class="server-module-failure">
    <div class="panel">
      <i class="pi pi-exclamation-triangle icon" />
      <h1>Application unavailable</h1>
      <p>
        A required server module failed to load. The application cannot
        start until this is resolved.
      </p>
      <p class="meta">Module: <code>{{ serverModuleLoadFailed.module }}</code></p>
      <button @click="reload">Reload</button>
    </div>
  </div>
  <template v-else>
    <MainLayout />
    <!--
      Server-module outlet. Server-provided modules call
      `ctx.mountShell(component)` during registration so they can own
      persistent UI (dialogs, listeners) outside of any route. Each
      entry renders once, tagged by contributorId so re-registration
      can replace it.
    -->
    <component
      v-for="shell in serverModuleShells"
      :key="shell.contributorId"
      :is="shell.component"
    />
  </template>
</template>

<script setup lang="ts">
import MainLayout from "@/layouts/MainLayout.vue";
import {
  serverModuleLoadFailed,
  serverModuleShells,
} from "@/boot/serverModules";

const reload = () => window.location.reload();
</script>

<style scoped>
.server-module-failure {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #111827;
  color: #f9fafb;
  z-index: 100000;
  padding: 24px;
}

.server-module-failure .panel {
  max-width: 480px;
  text-align: center;
  background: #1f2937;
  border: 1px solid #374151;
  border-radius: 12px;
  padding: 32px;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.4);
}

.server-module-failure .icon {
  font-size: 2.5rem;
  color: #f59e0b;
  margin-bottom: 16px;
}

.server-module-failure h1 {
  font-size: 1.25rem;
  margin: 0 0 12px;
}

.server-module-failure p {
  font-size: 0.95rem;
  line-height: 1.5;
  margin: 8px 0;
  color: #d1d5db;
}

.server-module-failure .meta {
  font-size: 0.85rem;
  color: #9ca3af;
}

.server-module-failure code {
  background: rgba(255, 255, 255, 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: "Monaco", "Courier New", monospace;
}

.server-module-failure button {
  margin-top: 20px;
  background: #3b82f6;
  color: white;
  border: none;
  padding: 10px 24px;
  border-radius: 8px;
  font-size: 0.95rem;
  cursor: pointer;
  transition: background 0.15s;
}

.server-module-failure button:hover {
  background: #2563eb;
}
</style>
