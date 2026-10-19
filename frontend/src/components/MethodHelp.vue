<template>
  <a
    class="method-help" :href="`https://docs.spectrascientific.ai/${path}`"
    target="_blank" rel="noopener noreferrer" :title="label"
    :aria-label="`${label} (opens documentation in a new tab)`">?</a>
</template>

<script setup lang="ts">
defineProps<{ path: string; label: string }>();
</script>

<style scoped>
.method-help { display: inline-flex; align-items: center; justify-content: center;
  width: 1.25rem; height: 1.25rem; margin-inline-start: .4rem; border: 1px solid currentColor;
  border-radius: 50%; font-size: .8rem; font-weight: 600; line-height: 1;
  color: inherit; text-decoration: none; vertical-align: middle; flex-shrink: 0; }
.method-help:focus-visible { outline: 2px solid #818cf8; outline-offset: 3px; }
</style>
