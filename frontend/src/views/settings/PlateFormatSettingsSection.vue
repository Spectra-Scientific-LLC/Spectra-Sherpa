<template>
  <section class="plate-preferences" aria-labelledby="plate-preferences-title">
    <div>
      <span class="eyebrow">Multi-well experiments</span>
      <h3 id="plate-preferences-title">Default plate format</h3>
      <p>New acquisition plans start with this backend-validated laboratory format.</p>
    </div>
    <div class="field">
      <label for="default-plate-format">Plate format</label>
      <Dropdown
        id="default-plate-format"
        v-model="defaultPlateFormatId"
        :options="formatOptions"
        option-label="label"
        option-value="value"
        :loading="loading"
        :disabled="loading || saving"
        @change="save"
      />
    </div>
    <small v-if="message" :class="{ error: failed }" role="status">{{ message }}</small>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import Dropdown from "primevue/dropdown";
import api from "@/api/client";
import { plateFormats } from "@/utils/plateFormats";
import { getErrorMessage } from "@/utils/errors";

const defaultPlateFormatId = ref("plate-96");
const loading = ref(true);
const saving = ref(false);
const message = ref("");
const failed = ref(false);
const formatOptions = plateFormats.map((format) => ({ label: format.label, value: format.id }));

async function load(): Promise<void> {
  loading.value = true;
  try {
    const { data } = await api.get<{ default_plate_format_id: string }>("/acquisition-preferences");
    defaultPlateFormatId.value = data.default_plate_format_id;
  } catch (error: unknown) {
    failed.value = true;
    message.value = getErrorMessage(error, "Unable to load the default plate format.");
  } finally {
    loading.value = false;
  }
}

async function save(): Promise<void> {
  saving.value = true;
  failed.value = false;
  message.value = "";
  try {
    await api.put("/acquisition-preferences", {
      default_plate_format_id: defaultPlateFormatId.value,
    });
    message.value = "Default plate format saved.";
  } catch (error: unknown) {
    failed.value = true;
    message.value = getErrorMessage(error, "Unable to save the default plate format.");
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.plate-preferences {
  align-items: end;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: var(--surface-card);
  display: grid;
  gap: 1rem;
  grid-template-columns: minmax(0, 2fr) minmax(14rem, 1fr);
  padding: 1.25rem;
}
.plate-preferences h3 {
  font-size: 1.125rem;
  font-weight: 500;
  margin: 0.2rem 0;
}
.plate-preferences p,
.plate-preferences small {
  color: var(--text-color-secondary);
  margin: 0;
}
.field {
  display: grid;
  gap: 0.35rem;
}
.eyebrow {
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.error {
  color: #b91c1c !important;
}
@media (max-width: 700px) {
  .plate-preferences {
    grid-template-columns: 1fr;
  }
}
</style>
