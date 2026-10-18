<template>
  <details class="scientific-basis" @toggle="loadWhenOpened">
    <summary>Scientific basis</summary>
    <p v-if="loading" role="status">Loading scientific guidance…</p>
    <p v-else-if="error" role="alert">{{ error }} <button type="button" @click="load">Retry</button></p>
    <template v-else-if="basis">
      <p>{{ basis.journey }}</p>
      <p class="muted">{{ basis.scope }} Guidance version: {{ basis.version }}.</p>
      <details v-for="entry in basis.entries" :key="entry.id">
        <summary>{{ entry.title }}</summary>
        <p>{{ entry.summary }}</p>
        <p><strong>Next step:</strong> {{ entry.action }}</p>
        <p><strong>Limit:</strong> {{ entry.limitations }}</p>
        <ul><li v-for="source in entry.sources" :key="source">
          <a v-if="source.startsWith('https://')" :href="source" target="_blank" rel="noopener noreferrer">{{ source }}</a>
          <span v-else>{{ source }}</span>
        </li></ul>
      </details>
    </template>
  </details>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import api from '@/api/client';
interface Basis {
  version: string; scope: string; journey: string;
  entries: Array<{ id: string; title: string; summary: string; action: string; limitations: string; sources: string[] }>;
}
const basis = ref<Basis | null>(null);
const loading = ref(false);
const error = ref('');
async function load() {
  if (loading.value) return;
  loading.value = true;
  error.value = '';
  try { basis.value = (await api.get<Basis>('/runs/scientific-guidance')).data; }
  catch { error.value = 'Could not load local scientific guidance.'; }
  finally { loading.value = false; }
}
function loadWhenOpened(event: Event) {
  if ((event.target as HTMLDetailsElement).open && !basis.value && !loading.value) void load();
}
</script>

<style scoped>
.scientific-basis { padding: .75rem; border: 1px solid #cbd5e1; border-radius: 6px; }
summary { cursor: pointer; font-weight: 600; }
details details { margin-top: .75rem; }
p, li { font-size: .85rem; line-height: 1.5; }
.muted { color: #64748b; }
a { overflow-wrap: anywhere; }
</style>
