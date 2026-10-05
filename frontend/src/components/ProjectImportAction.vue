<template>
  <Button
    label="Import Project"
    icon="pi pi-upload"
    class="p-button-outlined p-button-sm"
    :disabled="disabled"
    :loading="projectStore.isImporting"
    @click="triggerImport"
  />

  <input ref="fileInput" type="file" accept=".sherpa,.spectrapy,.zip" class="hidden-file-input" @change="onFileSelected" />
  <input ref="referenceFileInput" type="file" multiple class="hidden-file-input" @change="onReferenceFilesSelected" />

  <Dialog
    v-model:visible="referenceRebindVisible"
    modal
    :draggable="false"
    :closable="!projectStore.isImporting"
    :style="{ width: 'min(42rem, 92vw)' }"
    header="Restore reference data"
    @hide="clearReferenceRebind"
  >
    <div class="reference-rebind">
      <p>
        This project refers to provider-hosted data that is not included in the project archive.
        Download each required file from its provider, then select the downloaded file here.
      </p>
      <ul class="reference-rebind__list">
        <li v-for="requirement in referenceRequirements" :key="requirement.artifact_id">
          <div>
            <strong>{{ referenceDisplayName(requirement.artifact_id) }}</strong>
            <small>{{ requirement.provider }} · {{ formatFileSize(requirement.artifact_size_bytes) }}</small>
          </div>
          <a :href="requirement.download_url" target="_blank" rel="noopener noreferrer">
            Download from {{ requirement.provider }}
            <i class="pi pi-external-link" aria-hidden="true"></i>
          </a>
        </li>
      </ul>
      <p class="reference-rebind__note">
        Filenames and folders do not matter. Sherpa verifies the exact file size and SHA-256,
        then restores the new project atomically. A file that does not match is refused and not retained.
      </p>
      <p v-if="referenceRebindError" class="reference-rebind__error" role="alert">{{ referenceRebindError }}</p>
    </div>
    <template #footer>
      <Button label="Cancel" class="p-button-text" :disabled="projectStore.isImporting" @click="referenceRebindVisible = false" />
      <Button label="Import downloaded file(s)" icon="pi pi-upload" :loading="projectStore.isImporting" @click="referenceFileInput?.click()" />
    </template>
  </Dialog>

  <Dialog v-model:visible="publisherTrustVisible" header="Verify campaign publisher" :modal="true" :style="{ width: '520px' }">
    <p>This signed campaign needs the publisher's public verification keys. Obtain the JSON document independently from the publisher's trusted site or administrator. Do not trust a key solely because it arrived with the package.</p>
    <p>The campaign package creates a separate project without the provider-owned training spectra. Reattach source data locally to reproduce training; supply new data separately for Deploy predictions.</p>
    <label>Publisher public-key JSON <input type="file" accept=".json" @change="selectPublisherKey" /></label>
    <label><input type="checkbox" v-model="publisherTrustConfirmed" /> I verified the source of these public keys.</label>
    <p>The key is used for this import only. No private key or training data is needed.</p>
    <Button label="Verify and import" :disabled="!publisherTrustFile || !publisherTrustConfirmed" :loading="projectStore.isImporting" @click="retryPublisherImport" />
  </Dialog>
  <ProjectImportDestinationDialog v-model:visible="importDestinationVisible" @choose="chooseImportDestination" />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { useToast } from "primevue/usetoast";
import ProjectImportDestinationDialog from "@/components/ProjectImportDestinationDialog.vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDemoMode } from "@/composables/useDemoMode";
import { useProjectAvailability } from "@/composables/useProjectAvailability";
import { useProjectStore, type ProjectReferenceArtifactRequirement } from "@/stores/project";
import type { ProjectDetail } from "@/types";

interface ImportDestination { subscription_id: number; workspace_id: number | null; label: string }

const router = useRouter();
const toast = useToast();
const projectStore = useProjectStore();
const { config: appConfig, appMode, isCapabilityDisabled } = useAppConfig();
const { qualified } = useProjectAvailability();
const { isDemoMode, uploadsLastWeek, uploadsLimitWeek, uploadsResetWeekAt, fetchQuota } = useDemoMode();

const uploadQuotaExhausted = computed(() =>
  isDemoMode.value && uploadsLastWeek.value !== null && uploadsLimitWeek.value > 0 &&
  uploadsLimitWeek.value < 999999 && uploadsLastWeek.value >= uploadsLimitWeek.value,
);
const disabled = computed(() =>
  projectStore.isImporting || isCapabilityDisabled("data_upload") ||
  uploadQuotaExhausted.value || isCapabilityDisabled("project_import"),
);
const uploadDisabledMessage = computed(() => {
  if (isCapabilityDisabled("data_upload") || isCapabilityDisabled("project_import")) {
    return "Project import is disabled for this deployment.";
  }
  if (uploadQuotaExhausted.value) {
    const reset = uploadsResetWeekAt.value ? new Date(uploadsResetWeekAt.value).toLocaleString() : "later";
    return `Demo upload limit reached. Your next import is available ${reset}.`;
  }
  return "";
});
const maxProjectImportBytes = computed(() => (appConfig.value?.limits?.maxFileSizeMB ?? 200) * 1024 * 1024);

const fileInput = ref<HTMLInputElement | null>(null);
const referenceFileInput = ref<HTMLInputElement | null>(null);
const importDestinationVisible = ref(false);
const importDestination = ref<ImportDestination | null>(null);
const referenceRebindVisible = ref(false);
const pendingProjectArchive = ref<File | null>(null);
const referenceRequirements = ref<ProjectReferenceArtifactRequirement[]>([]);
const referenceRebindError = ref("");
const publisherTrustVisible = ref(false);
const publisherTrustFile = ref<File | null>(null);
const publisherTrustConfirmed = ref(false);
const pendingCampaignArchive = ref<File | null>(null);

onMounted(() => { void fetchQuota(); });
defineExpose({ triggerImport, disabled });

function chooseImportDestination(destination: ImportDestination): void {
  importDestination.value = destination;
  fileInput.value?.click();
}

function triggerImport(): void {
  if (disabled.value) {
    toast.add({ severity: "warn", summary: "Import Disabled", detail: uploadDisabledMessage.value || "Project import is disabled for this deployment.", life: 4000 });
    return;
  }
  if (qualified.value) {
    importDestination.value = null;
    importDestinationVisible.value = true;
    return;
  }
  fileInput.value?.click();
}

function formatFileSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function referenceDisplayName(artifactId: string): string {
  return artifactId.split(/[._-]+/).filter(Boolean).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

async function finishImport(project: ProjectDetail, detail?: string): Promise<void> {
  await fetchQuota();
  const application = projectStore.lastImportedApplication;
  if (application?.handle) {
    await router.push({ path: "/deploy", query: { project: String(project.id), application: application.handle } });
  } else {
    await router.push("/project");
  }
  toast.add({ severity: "success", summary: `Imported ${project.name}`, detail: detail || "A separate project was created and selected.", life: 3500 });
}

function selectPublisherKey(event: Event): void {
  publisherTrustFile.value = (event.target as HTMLInputElement).files?.[0] ?? null;
  publisherTrustConfirmed.value = false;
}

async function retryPublisherImport(): Promise<void> {
  if (!pendingCampaignArchive.value || !publisherTrustFile.value || !publisherTrustConfirmed.value) return;
  const project = await projectStore.importProject(pendingCampaignArchive.value, [], undefined,
    { file: publisherTrustFile.value, confirmed: publisherTrustConfirmed.value });
  if (!project) {
    toast.add({ severity: "error", summary: "Publisher verification failed", detail: projectStore.error || undefined, life: 5000 });
    return;
  }
  publisherTrustVisible.value = false;
  pendingCampaignArchive.value = null;
  publisherTrustFile.value = null;
  publisherTrustConfirmed.value = false;
  await finishImport(project);
}

async function onFileSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || disabled.value) return;
  if (file.size > maxProjectImportBytes.value) {
    toast.add({ severity: "error", summary: "Import file too large", detail: `Choose a project archive up to ${formatFileSize(maxProjectImportBytes.value)}.`, life: 4500 });
    return;
  }
  const project = await projectStore.importProject(file, [], importDestination.value ?? undefined);
  if (project) {
    await finishImport(project);
  } else if (projectStore.campaignTrustRequired && appMode.value === "local") {
    pendingCampaignArchive.value = file;
    publisherTrustFile.value = null;
    publisherTrustConfirmed.value = false;
    publisherTrustVisible.value = true;
  } else if (projectStore.referenceRebindRequirements.length) {
    pendingProjectArchive.value = file;
    referenceRequirements.value = [...projectStore.referenceRebindRequirements];
    referenceRebindError.value = "";
    referenceRebindVisible.value = true;
  } else {
    toast.add({ severity: "error", summary: "Import failed", detail: projectStore.error || undefined, life: 3500 });
  }
}

function clearReferenceRebind(): void {
  if (projectStore.isImporting) return;
  pendingProjectArchive.value = null;
  referenceRequirements.value = [];
  referenceRebindError.value = "";
  if (referenceFileInput.value) referenceFileInput.value.value = "";
}

async function onReferenceFilesSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const referenceFiles = Array.from(input.files ?? []);
  input.value = "";
  const archive = pendingProjectArchive.value;
  if (!archive || referenceFiles.length === 0) return;
  referenceRebindError.value = "";
  const project = await projectStore.importProject(archive, referenceFiles, importDestination.value ?? undefined);
  if (!project) {
    referenceRebindError.value = projectStore.error || "The selected file did not match the required reference data.";
    return;
  }
  referenceRebindVisible.value = false;
  pendingProjectArchive.value = null;
  await finishImport(project, "Reference data verified and restored into the new project.");
}
</script>

<style scoped>
.hidden-file-input { display: none; }
.reference-rebind { display: grid; gap: 1rem; }
.reference-rebind > p { margin: 0; line-height: 1.5; }
.reference-rebind__list { display: grid; gap: 0.75rem; margin: 0; padding: 0; list-style: none; }
.reference-rebind__list li { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.8rem; border: 1px solid var(--surface-border); border-radius: 6px; }
.reference-rebind__list div { display: grid; gap: 0.2rem; min-width: 0; }
.reference-rebind__list small, .reference-rebind__note { color: var(--text-color-secondary); }
.reference-rebind__list a { flex-shrink: 0; font-weight: 600; text-decoration: none; }
.reference-rebind__error { color: var(--red-500); font-weight: 600; }
@media (max-width: 900px) { .reference-rebind__list li { align-items: flex-start; flex-direction: column; } }
</style>
