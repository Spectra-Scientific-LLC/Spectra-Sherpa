<script setup lang="ts">
import { computed, onMounted } from "vue";
import Button from "primevue/button";
import ProgressSpinner from "primevue/progressspinner";
import Message from "primevue/message";
import { useWorkflowStore, type WorkflowTemplate } from "@/stores/workflow";

const props = defineProps<{
  selectedTemplateId?: number | null;
  showHeader?: boolean;
}>();

const emit = defineEmits<{
  select: [template: WorkflowTemplate];
}>();

const workflowStore = useWorkflowStore();

const templateStatus = (template: WorkflowTemplate) => template.status || template.template_data.status || "ready";

const groupedTemplates = computed(() => {
  const groups = new Map<string, WorkflowTemplate[]>();
  for (const template of workflowStore.availableTemplates) {
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
      <h3>Workflow Templates</h3>
      <p>Start from a validated backend template instead of rebuilding common chemometric workflows by hand.</p>
    </div>

    <div v-if="workflowStore.templatesLoading" class="gallery-state">
      <ProgressSpinner style="width: 36px; height: 36px" />
      <span>Loading templates...</span>
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
      <span>No templates are available.</span>
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
                <h5>{{ template.name }}</h5>
                <span class="template-status" :class="templateStatus(template)">
                  {{ templateStatus(template) }}
                </span>
              </div>
              <p>{{ template.description }}</p>
            </div>
            <Button
              label="Use Template"
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
