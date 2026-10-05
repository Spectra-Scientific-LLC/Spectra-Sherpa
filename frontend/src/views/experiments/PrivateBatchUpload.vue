<template>
  <section v-if="allowed" class="private-batch-upload">
    <label for="private-prediction-files">Prediction files</label>
    <input id="private-prediction-files" ref="fileInput" type="file" multiple :disabled="busy" @change="selectFiles" />
    <span v-if="files.length">{{ files.length }} files</span>
    <Button label="Predict Files" icon="pi pi-play" :loading="busy" :disabled="!files.length || busy" @click="predict" />
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import Button from "primevue/button";
import api from "@/api/client";
import { useProjectStore } from "@/stores/project";
import type { ExecutionRunSummary } from "@/types";
import { getErrorMessage } from "@/utils/errors";

const props = defineProps<{ artifactUid: string }>();
const emit = defineEmits<{ completed: [run: ExecutionRunSummary] }>();
const project = useProjectStore();
const allowed = ref(false);
const busy = ref(false);
const files = ref<File[]>([]);
const fileInput = ref<HTMLInputElement | null>(null);
const error = ref("");
const maxFiles = ref(16);
const maxBytes = ref(31 * 1024 * 1024);
let generation = 0;
let controller: AbortController | null = null;

async function refresh() {
  const current = ++generation;
  controller?.abort();
  controller = new AbortController();
  allowed.value = false;
  busy.value = false;
  files.value = [];
  error.value = "";
  if (fileInput.value) fileInput.value.value = "";
  try {
    const { data } = await api.get("/deploy/capabilities", { signal: controller.signal });
    if (current === generation) {
      allowed.value = data.privateBatchUpload === true;
      maxFiles.value = data.maxFiles;
      maxBytes.value = Math.max(0, data.maxRequestBytes - 1024 * 1024);
    }
  } catch { /* Fail closed; reference-dataset application remains available. */ }
}

function selectFiles(event: Event) {
  files.value = Array.from((event.target as HTMLInputElement).files || []);
  error.value = "";
  if (files.value.length > maxFiles.value || files.value.reduce((n, file) => n + file.size, 0) > maxBytes.value) {
    files.value = [];
    error.value = `Select at most ${maxFiles.value} files totaling ${(maxBytes.value / (1024 * 1024)).toFixed(1)} MiB or less.`;
    if (fileInput.value) fileInput.value.value = "";
  }
}

async function predict() {
  const current = generation;
  const artifact = props.artifactUid;
  busy.value = true;
  error.value = "";
  const form = new FormData();
  for (const file of files.value) form.append("files", file);
  try {
    const { data } = await api.post(`/runs/batch/files/${encodeURIComponent(artifact)}`, form, {
      signal: controller?.signal,
    });
    if (current !== generation) return;
    const result = await api.get<ExecutionRunSummary>(`/runs/${data.run_id}`, { signal: controller?.signal });
    if (current === generation) emit("completed", result.data);
  } catch (exc) {
    if (current === generation) error.value = getErrorMessage(exc, "Prediction submission failed.");
  } finally {
    if (current === generation) busy.value = false;
  }
}

onMounted(refresh);
watch(() => [props.artifactUid, project.currentProjectId], refresh);
onBeforeUnmount(() => { ++generation; controller?.abort(); });
</script>

<style scoped>
.private-batch-upload { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; padding-block: 1rem; border-bottom: 1px solid var(--surface-border); }
.private-batch-upload input { max-width: 100%; min-width: 0; }
.private-batch-upload p { flex-basis: 100%; color: var(--red-600); }
</style>
