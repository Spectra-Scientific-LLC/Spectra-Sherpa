<template>
  <section aria-label="Local AI exchanges">
    <h2>Local AI exchanges</h2>
    <p>Last 20 basic BYOK requests in this session. History clears when the backend exits.
      Secrets are redacted; records may still contain scientific information you typed.</p>
    <Button label="Refresh exchanges" @click="refresh" />
    <Button label="Clear exchanges" :disabled="!exchanges.length" @click="clear" />
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!exchanges.length">No exchanges recorded in this session.</p>
    <details v-for="entry in exchanges" :key="entry.id" class="exchange">
      <summary>{{ entry.timestamp }} · {{ entry.provider }} / {{ entry.model }} · {{ entry.status }}</summary>
      <p>{{ entry.duration_ms }} ms · Usage: {{ entry.usage ? JSON.stringify(entry.usage) : 'Not supplied by provider' }}</p>
      <p v-if="entry.truncated" role="status">This record is truncated. It is not a complete exchange.</p>
      <h3>Question</h3><pre>{{ section(entry.request, 'user') }}</pre>
      <h3>Instructions and current view</h3><pre>{{ section(entry.request, 'system') }}</pre>
      <h3>Provider response</h3><pre>{{ entry.response || 'No response received.' }}</pre>
      <details><summary>Request details (redacted)</summary><pre>{{ entry.request || 'No provider request sent.' }}</pre></details>
      <Button label="Save exchange" @click="save(entry)" />
    </details>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import Button from 'primevue/button';
import api from '@/api/client';
import { downloadText } from '@/utils/download';

interface Exchange {
  id: string; timestamp: string; provider: string; model: string;
  status: string; duration_ms: number; request: string | null;
  response: string; usage: Record<string, number> | null; truncated: boolean;
}
const exchanges = ref<Exchange[]>([]);
const error = ref('');
async function refresh() {
  error.value = '';
  try { exchanges.value = (await api.get('/chat/exchanges')).data.exchanges; }
  catch { error.value = 'Unable to load local exchanges.'; }
}
async function clear() {
  try { await api.delete('/chat/exchanges'); exchanges.value = []; error.value = ''; }
  catch { error.value = 'Unable to clear local exchanges.'; }
}
function section(request: string | null, role: string): string {
  if (!request) return 'No provider request sent.';
  try {
    const body = JSON.parse(request);
    const parts = (body.messages || []).filter((m: { role: string }) => m.role === role)
      .map((m: { content: string }) => m.content);
    if (role === 'system' && body.system) parts.unshift(body.system);
    return parts.join('\n\n') || 'None.';
  } catch { return 'Request record truncated; see Request details.'; }
}
function save(entry: Exchange) {
  downloadText(JSON.stringify(entry, null, 2), `sherpa-exchange-${entry.id}.json`, 'application/json');
}
onMounted(refresh);
</script>

<style scoped>
.exchange { margin-block: 1rem; padding: 0.75rem; border: 1px solid var(--surface-border); }
pre { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
