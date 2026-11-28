<!-- Keeps secondary row actions behind one accessible menu. -->
<template>
  <span class="row-actions" @click.stop>
    <Button
      icon="pi pi-ellipsis-h"
      class="p-button-text p-button-sm p-button-rounded"
      :aria-label="`More actions for ${subject}`"
      :title="`More actions for ${subject}`"
      aria-haspopup="true"
      @click="toggle"
    />
    <Menu ref="menu" :model="menuItems" :popup="true" />
  </span>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import Button from "primevue/button";
import Menu from "primevue/menu";

export interface RowAction {
  label: string;
  icon?: string;
  /** Destructive actions are listed last and styled as dangerous. */
  danger?: boolean;
  disabled?: boolean;
  command: () => void;
}

const props = defineProps<{ subject: string; actions: RowAction[] }>();
const menu = ref<{ toggle: (event: Event) => void } | null>(null);

const menuItems = computed(() => [
  ...props.actions.filter((action) => !action.danger),
  ...props.actions.filter((action) => action.danger),
].map((action) => ({
  label: action.label,
  icon: action.icon,
  disabled: action.disabled,
  class: action.danger ? "row-actions__danger" : undefined,
  command: action.command,
})));

function toggle(event: Event) {
  menu.value?.toggle(event);
}
</script>

<style>
.row-actions__danger .p-menuitem-text,
.row-actions__danger .p-menuitem-icon {
  color: var(--ss-danger-strong, var(--red-600));
}
</style>
