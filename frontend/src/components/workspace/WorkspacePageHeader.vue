<!-- Gives each workspace one decision beside its role and identity. -->
<template>
  <header class="workspace-page-header">
    <div class="workspace-page-heading">
      <span v-if="role" class="workspace-page-role">{{ role }}</span>
      <h1>{{ title }}</h1>
      <p v-if="identity" class="workspace-page-identity">{{ identity }}</p>
    </div>
    <ResponsiveHeaderActions :items="actions" :menu-label="menuLabel" :menu-only="!$slots.secondary && actions.length > 0">
      <template v-if="$slots.primary || primary" #primary>
        <slot name="primary">
          <Button v-if="primary" :label="primary.label" :disabled="primary.disabled" :loading="busy" @click="invoke(primary)" />
        </slot>
      </template>
      <slot name="secondary" />
      <template v-if="$slots.after" #after><slot name="after" /></template>
    </ResponsiveHeaderActions>
    <p v-if="error" class="workspace-page-error" role="alert">{{ error }}</p>
  </header>
</template>

<script setup lang="ts">
import Button from "primevue/button";
import ResponsiveHeaderActions, { type HeaderActionMenuItem } from "@/components/ResponsiveHeaderActions.vue";
import { useNavigationActionContext } from "@/navigation/actionContext";

withDefaults(defineProps<{ title: string; role?: string; identity?: string; actions?: HeaderActionMenuItem[]; menuLabel?: string }>(), {
  role: "",
  identity: "",
  actions: () => [],
  menuLabel: "Actions",
});
const { primary, invoke, busy, error } = useNavigationActionContext();
</script>

<style scoped>
.workspace-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: .75rem 1rem;
  min-width: 0;
}
.workspace-page-heading { min-width: 0; flex: 1 1 15rem; overflow-wrap: anywhere; }
.workspace-page-heading h1 { margin: 0; }
.workspace-page-role {
  display: inline-block;
  margin-block-end: .25rem;
  padding: .15rem .5rem;
  border-radius: 999px;
  background: var(--ss-accent-faint);
  color: var(--ss-accent);
}
.workspace-page-identity { margin: .25rem 0 0; color: var(--text-color-secondary); }
.workspace-page-error { margin: 0; width: 100%; color: var(--ss-danger); }
</style>
