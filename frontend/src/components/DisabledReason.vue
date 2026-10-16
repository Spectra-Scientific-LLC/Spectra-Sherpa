<template>
  <small v-if="reason" :id="id" class="disabled-reason">
    <i class="pi pi-info-circle" aria-hidden="true" />
    <span>{{ reason }}</span>
  </small>
</template>
<script setup lang="ts">
// Says, in visible text, why the action beside it is unavailable. Hover-only
// titles are invisible on touch screens and to keyboard users; the action
// points at this text with aria-describedby="<id>".
defineProps<{ id: string; reason?: string | null }>();
</script>
<style scoped>
.disabled-reason {
  display: flex;
  align-items: flex-start;
  gap: 0.375rem;
  margin-top: 0.375rem;
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  line-height: 1.4;
}
.disabled-reason .pi {
  margin-top: 0.125rem;
  font-size: 0.8125rem;
}
</style>
