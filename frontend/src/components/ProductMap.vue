<template>
  <aside class="product-map" :class="{ compact }" aria-label="SpectraSherpa products">
    <strong v-if="compact">Demo · Hosted evaluation</strong>
    <template v-else>
      <h2>SpectraSherpa products</h2>
      <dl>
        <div><dt>OSS</dt><dd>Local compute on your computer.</dd></div>
        <div><dt>Demo</dt><dd>Hosted evaluation with reference datasets and usage allowances.</dd></div>
        <div><dt>Pro</dt><dd>Hosted analysis with your own data and plan allowances.</dd></div>
      </dl>
    </template>
    <a href="https://docs.spectrascientific.ai/introduction/cloud-vs-local/" target="_blank" rel="noopener">
      OSS: local · Demo / Pro: hosted
    </a>
  </aside>
</template>

<script setup lang="ts">
defineProps<{ compact?: boolean }>();
</script>

<style scoped>
.product-map { padding: 1rem 1.25rem; border-bottom: 1px solid var(--surface-border); color: var(--text-color); }
.product-map h2 { margin: 0 0 0.75rem; font-size: 1rem; }
.product-map dl { display: flex; flex-wrap: wrap; gap: 1rem 2rem; margin: 0 0 0.75rem; }
.product-map dt { font-weight: 600; }
.product-map dd { margin: 0.25rem 0 0; }
.product-map a { color: var(--primary-color); }
.compact { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.5rem; padding: 0.5rem 1rem; font-size: 0.8125rem; }
</style>
