<template>
  <Button label="Inspect archive" icon="pi pi-eye" class="p-button-text p-button-sm" @click="fileInput?.click()" />
  <input ref="fileInput" type="file" accept=".sherpa,.spectrapy,.zip" hidden aria-label="Inspect project archive" @change="selectFile" />
  <Dialog
    :visible="visible" @update:visible="value => { if (!value) close(); }" modal header="Retained workflow"
    :style="{ width: 'min(64rem, 95vw)' }" :draggable="false">
    <p>Read-only evidence. Inspecting this archive does not import a project or run its nodes.</p>
    <p v-if="loading" role="status">Reading archived workflow…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="inspection">
      <h3>{{ inspection.project_name }} · {{ inspection.graph.name }}</h3>
      <p>Workflow {{ inspection.workflow_index + 1 }} of {{ inspection.workflow_count }}</p>
      <div class="retained-archive__navigation">
        <Button label="Previous" text :disabled="loading || inspection.workflow_index === 0" @click="load(inspection.workflow_index - 1)" />
        <Button label="Next" text :disabled="loading || inspection.workflow_index + 1 >= inspection.workflow_count" @click="load(inspection.workflow_index + 1)" />
      </div>
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
          <tbody><tr v-for="node in inspection.graph.nodes" :key="node.node_id">
            <td>{{ node.label || node.node_id }}<small v-if="node.label">{{ node.node_id }}</small></td>
            <td><code>{{ node.node_type }}</code></td>
            <td><pre>{{ node.parameters_json }}</pre></td>
          </tr></tbody>
        </table>
      </div>
      <h4>Connections</h4>
      <ul v-if="inspection.graph.edges.length">
        <li v-for="(edge, index) in inspection.graph.edges" :key="index">
          {{ edge.from_node_id }} / {{ edge.from_output }} → {{ edge.to_node_id }} / {{ edge.to_input }}
        </li>
      </ul>
      <p v-else>No connections were recorded.</p>
    </template>
    <template #footer><Button label="Close" text @click="close" /></template>
  </Dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { api } from "@/api";
import { useAppConfig } from "@/composables/useAppConfig";
import { useScopedRequest } from "@/composables/useScopedRequest";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import type { components } from "@/types/api/v1";

type Inspection = components["schemas"]["RetainedArchiveWorkflow"];
const auth = useAuthStore();
const project = useProjectStore();
const { config } = useAppConfig();
const fileInput = ref<HTMLInputElement | null>(null);
const file = ref<File | null>(null);
const fileRevision = ref(0);
const visible = ref(false);
const loading = ref(false);
const error = ref("");
const inspection = ref<Inspection | null>(null);
const identity = () => [auth.user?.id, auth.sessionRevision, project.currentProjectId];
const requests = useScopedRequest(() => [...identity(), visible.value, fileRevision.value]);
watch(identity, close);
const packs = computed(() => {
  const found = new Map<string, components["schemas"]["PackReference"]>();
  for (const node of inspection.value?.graph.pack_binding?.nodes ?? []) {
    for (const pack of node.required) found.set(pack.pack_id, pack);
  }
  return [...found.values()];
});

function close(): void {
  requests.invalidate();
  fileRevision.value += 1;
  visible.value = false;
  file.value = null;
  inspection.value = null;
  loading.value = false;
  error.value = "";
}

async function selectFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const selected = input.files?.[0];
  input.value = "";
  if (!selected) return;
  close();
  visible.value = true;
  const limit = (config.value?.limits?.maxFileSizeMB ?? 200) * 1024 * 1024;
  if (selected.size > limit) {
    error.value = "This archive exceeds the configured file size limit.";
    return;
  }
  file.value = selected;
  await load(0);
}

async function load(index: number): Promise<void> {
  if (!file.value) return;
  const request = requests.begin();
  const form = new FormData();
  form.append("file", file.value);
  loading.value = true;
  error.value = "";
  inspection.value = null;
  try {
    const { data } = await api.post<Inspection>("/projects/objects/inspect-workflow", form,
      { params: { workflow_index: index }, signal: request.signal });
    if (request.isCurrent()) inspection.value = data;
  } catch {
    if (request.isCurrent()) error.value = "This archive has no readable workflow at the selected position.";
  } finally {
    if (request.isCurrent()) loading.value = false;
  }
}
</script>

<style scoped>
.retained-archive__navigation { display: flex; gap: 0.5rem; }
.retained-archive__table { overflow: auto; max-height: 24rem; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; vertical-align: top; padding: 0.6rem; border-bottom: 1px solid var(--surface-border); }
small { display: block; }
pre, code { white-space: pre-wrap; overflow-wrap: anywhere; }
pre { margin: 0; max-width: 30rem; }
</style>
