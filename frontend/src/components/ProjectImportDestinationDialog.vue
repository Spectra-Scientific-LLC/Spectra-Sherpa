<template>
  <Dialog :visible="visible" @update:visible="emit('update:visible', $event)" modal header="Import destination" :style="{ width: '30rem' }">
    <p>The imported project receives a new project identity in the selected workspace.</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <Dropdown v-model="selected" :options="options" optionLabel="label" placeholder="Choose a workspace"
      aria-label="Import workspace" :loading="loading" />
    <template #footer>
      <Button label="Cancel" text @click="emit('update:visible', false)" />
      <Button label="Choose archive" :disabled="!selected || loading" @click="choose" />
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { ref, watch } from "vue";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import Button from "primevue/button";
import { api } from "@/api";
import { useScopedRequest } from "@/composables/useScopedRequest";
import { useAuthStore } from "@/stores/auth";
interface Destination { subscription_id: number; workspace_id: number | null; label: string }
const props = defineProps<{ visible: boolean }>();
const emit = defineEmits<{ "update:visible": [boolean]; choose: [Destination] }>();
const selected = ref<Destination | null>(null);
const options = ref<Destination[]>([]);
const loading = ref(false);
const error = ref("");
const auth = useAuthStore();
const identity = () => [auth.user?.id, auth.sessionRevision, props.visible];
const requests = useScopedRequest(identity);
watch(identity, async () => {
  const request = requests.begin();
  selected.value = null;
  options.value = [];
  error.value = "";
  loading.value = false;
  if (!props.visible) return;
  loading.value = true;
  try {
    const { data } = await api.get<{ options: Destination[] }>("/commercial/projects/options", { signal: request.signal });
    if (!request.isCurrent()) return;
    options.value = data.options;
    if (data.options.length === 1) selected.value = data.options[0];
    if (!data.options.length) error.value = "No authorized import workspace is available.";
  } catch {
    if (request.isCurrent()) error.value = "Unable to load import workspaces. Close and retry.";
  } finally {
    if (request.isCurrent()) loading.value = false;
  }
}, { immediate: true });
function choose() {
  if (!selected.value || loading.value) return;
  emit("choose", selected.value);
  emit("update:visible", false);
}
</script>
