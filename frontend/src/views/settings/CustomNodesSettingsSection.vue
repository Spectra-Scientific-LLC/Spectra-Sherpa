<template>
  <section v-if="state" class="custom-nodes-settings">
    <h3>Custom nodes</h3>
    <p>Load your own Python functions as workflow nodes from your My nodes folder and from installed packages. You are responsible for the science of your nodes.</p>
    <label>
      <input type="checkbox" :checked="state.enabled" :disabled="busy" name="custom_nodes_enabled" @change="toggle($event.target as HTMLInputElement)" />
      Load custom nodes
    </label>
    <p>My nodes folder: <code>{{ state.folder }}</code></p>
    <p v-if="state.restart_required" role="status">Restart Spectra Sherpa to apply this change.</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <ul v-if="state.sources.length" aria-label="Custom node sources">
      <li v-for="source in state.sources" :key="`${source.kind}:${source.location}`">
        {{ source.source }} ({{ source.kind === 'package' ? source.location : 'My nodes folder' }}) —
        <template v-if="source.status === 'loaded'">loaded: {{ source.nodes.join(', ') }}</template>
        <template v-else>not loaded: {{ source.message }}</template>
      </li>
    </ul>
    <p v-else-if="state.active">No custom node sources were found at startup.</p>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import api from '@/api/client';

interface CustomNodeSource {
  source: string;
  kind: 'folder' | 'package';
  location: string;
  version: string | null;
  status: 'loaded' | 'failed';
  nodes: string[];
  message: string | null;
}

interface CustomNodesState {
  available: boolean;
  enabled: boolean;
  active: boolean;
  restart_required: boolean;
  folder: string;
  sources: CustomNodeSource[];
}

const state = ref<CustomNodesState | null>(null);
const busy = ref(false);
const error = ref('');

async function load() {
  try {
    const { data } = await api.get<CustomNodesState>('/config/custom-nodes');
    state.value = data;
  } catch {
    // Unavailable outside local Workbench, or from another computer: show nothing.
    state.value = null;
  }
}

async function toggle(input: HTMLInputElement) {
  if (busy.value) return;
  busy.value = true; error.value = '';
  try {
    const { data } = await api.put<CustomNodesState>('/config/custom-nodes', { enabled: input.checked });
    state.value = data;
  } catch {
    error.value = 'Could not change this setting.';
    await load();
    // The bound value may not have changed, so put the clicked box back too.
    input.checked = state.value?.enabled ?? !input.checked;
  } finally { busy.value = false; }
}

onMounted(load);
</script>

<style scoped>
.custom-nodes-settings { margin-top: 2rem; }
label { display: flex; gap: 0.5rem; align-items: center; }
li { margin: 0.5rem 0; }
code { word-break: break-all; }
</style>
