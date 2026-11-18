<template>
      <h4>Recorded pack builds</h4>
      <ul v-if="packs.length">
        <li v-for="pack in packs" :key="pack.pack_id">
          {{ pack.pack_id }} {{ pack.version }} <code>{{ pack.build_sha256 }}</code>
        </li>
      </ul>
      <p v-else>No pack build identity was recorded in this graph.</p>
      <h4>Nodes and parameters</h4>
      <div class="retained-archive__table">
        <table>
          <thead><tr><th>Node</th><th>Operation</th><th>Retained parameters</th></tr></thead>
          <tbody><tr v-for="node in graph.nodes" :key="node.node_id">
            <td>{{ node.label || node.node_id }}<small v-if="node.label">{{ node.node_id }}</small></td>
            <td><code>{{ node.node_type }}</code></td>
            <td><pre>{{ node.parameters_json }}</pre></td>
          </tr></tbody>
        </table>
      </div>
      <h4>Connections</h4>
      <ul v-if="graph.edges.length">
        <li v-for="(edge, index) in graph.edges" :key="index">
          {{ edge.from_node_id }} / {{ edge.from_output }} → {{ edge.to_node_id }} / {{ edge.to_input }}
        </li>
      </ul>
      <p v-else>No connections were recorded.</p>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { components } from "@/types/api/v1";
const props = defineProps<{ graph: components["schemas"]["RetainedGraph"] }>();
const packs = computed(() => {
  const found = new Map<string, components["schemas"]["PackReference"]>();
  for (const node of props.graph.pack_binding?.nodes ?? []) {
    for (const pack of node.required) found.set(pack.pack_id, pack);
  }
  return [...found.values()];
});
</script>

<style scoped>
.retained-archive__table { overflow: auto; max-height: 24rem; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; vertical-align: top; padding: 0.6rem; border-bottom: 1px solid var(--surface-border); }
small { display: block; }
pre, code { white-space: pre-wrap; overflow-wrap: anywhere; }
pre { margin: 0; max-width: 30rem; }
</style>
