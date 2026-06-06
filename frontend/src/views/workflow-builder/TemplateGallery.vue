<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import Button from "primevue/button";
import ProgressSpinner from "primevue/progressspinner";
import Message from "primevue/message";
import { useWorkflowStore, type WorkflowTemplate } from "@/stores/workflow";
import type { DataModality } from "@/stores/workflow-types";

const props = defineProps<{
  selectedTemplateId?: number | null;
  showHeader?: boolean;
}>();

const emit = defineEmits<{
  select: [template: WorkflowTemplate];
}>();

const workflowStore = useWorkflowStore();
const selectedModality = ref<"all" | DataModality>("all");

const templateStatus = (template: WorkflowTemplate) => template.status || template.template_data.status || "ready";

const modalityMeta: Record<DataModality, { label: string; icon: string; tooltip: string }> = {
  spectra: {
    label: "Spectra",
    icon: "pi-chart-line",
    tooltip: "Spectra: ordered wavelength, wavenumber, Raman-shift, NMR, or m/z axes",
  },
  features: {
    label: "Features",
    icon: "pi-table",
    tooltip: "Feature table: multivariate columns with no ordered spectral axis",
  },
  hsi: {
    label: "HSI",
    icon: "pi-image",
    tooltip: "Hyperspectral image cube: spectral axis plus spatial map",
  },
};

const modalityFilters: Array<{ label: string; value: "all" | DataModality }> = [
  { label: "All", value: "all" },
  { label: "Spectra", value: "spectra" },
  { label: "Features", value: "features" },
  { label: "HSI", value: "hsi" },
];

const templateModalities = (template: WorkflowTemplate): DataModality[] => {
  const modalities = template.data_modalities || template.template_data.data_modalities;
  if (Array.isArray(modalities) && modalities.length) {
    return modalities;
  }
  return ["spectra"];
};

const groupedTemplates = computed(() => {
  const groups = new Map<string, WorkflowTemplate[]>();
  const visibleTemplates = workflowStore.availableTemplates.filter((template) => {
    if (selectedModality.value === "all") {
      return true;
    }
    return templateModalities(template).includes(selectedModality.value);
  });

  for (const template of visibleTemplates) {
    const category = template.category || "other";
    if (!groups.has(category)) {
      groups.set(category, []);
    }
    groups.get(category)!.push(template);
  }

  return Array.from(groups.entries())
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([category, templates]) => ({
      category,
      label: category.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()),
      templates: [...templates].sort((left, right) => left.name.localeCompare(right.name)),
    }));
});

onMounted(async () => {
  // Always re-fetch to pick up backend template updates (e.g. new data_roles)
  if (!workflowStore.templatesLoading) {
    try {
      await workflowStore.fetchTemplates();
    } catch {
      // Store owns the error state shown below.
    }
  }
});
</script>

<template>
  <div class="template-gallery">
    <div v-if="props.showHeader !== false" class="gallery-header">
      <h3>Analysis Starters</h3>
      <p>Choose a validated analysis starter instead of rebuilding common chemometric workflows by hand.</p>
      <div class="modality-filters" aria-label="Filter templates by data shape">
        <Button
          v-for="filter in modalityFilters"
          :key="filter.value"
          :label="filter.label"
          :class="{ active: selectedModality === filter.value }"
          class="p-button-sm p-button-text modality-filter"
          @click="selectedModality = filter.value"
        />
      </div>
    </div>

    <div v-if="workflowStore.templatesLoading" class="gallery-state">
      <ProgressSpinner style="width: 36px; height: 36px" />
      <span>Loading analysis starters...</span>
    </div>

    <Message
      v-else-if="workflowStore.templatesError"
      severity="error"
      :closable="false"
    >
      {{ workflowStore.templatesError }}
    </Message>

    <div v-else-if="!groupedTemplates.length" class="gallery-state empty">
      <i class="pi pi-th-large"></i>
      <span>No analysis starters are available.</span>
    </div>

    <div v-else class="template-groups">
      <section
        v-for="group in groupedTemplates"
        :key="group.category"
        class="template-group"
      >
        <div class="group-header">
          <h4>{{ group.label }}</h4>
          <span>{{ group.templates.length }}</span>
        </div>

        <div class="template-cards">
          <article
            v-for="template in group.templates"
            :key="template.id"
            class="template-card"
            :class="{ selected: props.selectedTemplateId === template.id }"
          >
            <div class="template-card-body">
              <div class="template-card-heading">
                <div class="template-title-row">
                  <h5>{{ template.name }}</h5>
                  <span class="modality-icons" aria-label="Accepted data modalities">
                    <i
                      v-for="modality in templateModalities(template)"
                      :key="modality"
                      class="pi"
                      :class="modalityMeta[modality].icon"
                      :title="modalityMeta[modality].tooltip"
                    />
                  </span>
                </div>
                <span class="template-status" :class="templateStatus(template)">
                  {{ templateStatus(template) }}
                </span>
              </div>
              <p>{{ template.description }}</p>
            </div>
            <Button
              label="Start"
              icon="pi pi-arrow-right"
              icon-pos="right"
              class="p-button-outlined"
              :disabled="templateStatus(template) !== 'ready'"
              @click="emit('select', template)"
            />
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.template-gallery {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.gallery-header h3 {
  margin: 0 0 0.35rem;
  font-size: 1.2rem;
}

.gallery-header p {
  margin: 0;
  color: var(--text-color-secondary);
  line-height: 1.5;
}

.modality-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.85rem;
}

.modality-filter {
  color: var(--text-color-secondary);
}

.modality-filter.active {
  background: color-mix(in srgb, var(--primary-color) 9%, transparent);
  color: var(--primary-color);
}

.gallery-state {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-height: 120px;
  justify-content: center;
  color: var(--text-color-secondary);
}

.gallery-state.empty {
  flex-direction: column;
}

.template-groups {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.template-group {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.group-header h4 {
  margin: 0;
  font-size: 1rem;
}

.group-header span {
  color: var(--text-color-secondary);
  font-size: 0.9rem;
}

.template-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 0.9rem;
}

.template-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem;
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  background: var(--surface-card);
  transition: border-color 120ms ease, box-shadow 120ms ease, background-color 120ms ease, transform 120ms ease;
}

.template-card:hover {
  border-color: color-mix(in srgb, var(--primary-color) 28%, var(--surface-border));
  transform: translateY(-1px);
}

.template-card.selected {
  border-color: color-mix(in srgb, var(--primary-color) 65%, var(--surface-border));
  box-shadow:
    0 0 0 3px color-mix(in srgb, var(--primary-color) 20%, transparent),
    0 10px 24px rgba(15, 23, 42, 0.08);
  background: color-mix(in srgb, var(--primary-color) 5%, var(--surface-card));
}

.template-card-body h5 {
  margin: 0;
  font-size: 1rem;
}

.template-title-row {
  align-items: center;
  display: flex;
  gap: 0.5rem;
  min-width: 0;
}

.modality-icons {
  align-items: center;
  color: var(--text-color-secondary);
  display: inline-flex;
  gap: 0.35rem;
  white-space: nowrap;
}

.modality-icons i {
  font-size: 0.88rem;
}

.template-card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.45rem;
}

.template-status {
  display: inline-flex;
  align-items: center;
  padding: 0.12rem 0.48rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.template-status.ready {
  background: color-mix(in srgb, var(--green-500) 15%, white);
  color: var(--green-700);
}

.template-status.wip {
  background: color-mix(in srgb, var(--yellow-500) 18%, white);
  color: var(--yellow-800);
}

.template-card-body p {
  margin: 0;
  color: var(--text-color-secondary);
  line-height: 1.5;
}
</style>
