<template>
  <span class="display-subset-indicator" role="status" title="Only part of the data is shown">Subset</span>
</template>

<style scoped>
.display-subset-indicator {
  display: inline-flex;
  align-items: center;
  padding: .1rem .4rem;
  border: 1px solid var(--ss-border-input);
  border-radius: .25rem;
  color: var(--ss-text-strong);
  background: var(--ss-surface-subtle);
  font-size: .75rem;
  font-weight: 600;
  line-height: 1.4;
}
</style>
