<template>
  <details v-if="runs.length === 2" class="evaluation-controls">
    <summary>Optional common evaluation and robustness</summary>
    <p>Select the saved PLS output from each workflow. This creates a new development evaluation and keeps the original runs unchanged.</p>
    <slot />
  </details>
</template>
<script setup lang="ts">
defineProps<{ runs: readonly unknown[] }>();
</script>
