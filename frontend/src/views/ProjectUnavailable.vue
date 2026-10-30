<template>
  <section class="page-content" aria-label="Project unavailable">
    <WorkspaceHeader title="Project unavailable" />
    <WorkspaceState kind="unavailable" message="This project isn’t available. It may have been removed, or your account may not have access.">
      <RouterLink to="/dashboard">Back to Dashboard</RouterLink>
      <Button v-if="retryable" label="Retry project" class="p-button-text" @click="$emit('retry')" />
    </WorkspaceState>
  </section>
</template>
<script setup lang="ts">
import { RouterLink } from "vue-router";
import Button from "primevue/button";
defineProps<{ retryable?: boolean }>();
defineEmits<{ retry: [] }>();
import WorkspaceHeader from "@/components/workspace/WorkspaceHeader.vue";
import WorkspaceState from "@/components/workspace/WorkspaceState.vue";
</script>
