<template>
  <Dialog
    v-model:visible="visible"
    modal
    :draggable="false"
    :style="{ width: '720px' }"
    header="Start from a template"
    class="template-picker-dialog"
  >
    <div v-if="loading" class="tp-status">
      <i class="pi pi-spin pi-spinner"></i> Loading templates…
    </div>
    <div v-else-if="loadError" class="tp-status tp-status-error">
      <i class="pi pi-exclamation-triangle"></i>
      {{ loadError }}
    </div>
    <div v-else-if="templates.length === 0" class="tp-status">
      No templates are available. Reinstall <code>spectra-sherpa</code> to refresh the catalog.
    </div>
    <template v-else>
      <p class="tp-tagline">
        Curated starter workflows. Each one comes with a sample dataset so you can
        see the pipeline run end-to-end before swapping in your own data.
      </p>
      <div v-for="(group, idx) in groupedTemplates" :key="group.category" class="tp-group">
        <h4 class="tp-group-title">
          {{ group.category }}
          <span class="tp-group-count">({{ group.items.length }})</span>
        </h4>
        <ul class="tp-list">
          <li v-for="tpl in group.items" :key="tpl.id" class="tp-row">
            <div class="tp-row-main">
              <div class="tp-row-title">
                {{ tpl.name }}
                <span v-if="!supportsExample(tpl)" class="tp-needs-data" title="This template needs you to bind it to your own data after creation.">
                  needs data
                </span>
              </div>
              <p v-if="tpl.description" class="tp-row-description">{{ tpl.description }}</p>
            </div>
            <Button
              :label="instantiating === tpl.id ? 'Creating…' : 'Use'"
              :icon="instantiating === tpl.id ? 'pi pi-spin pi-spinner' : 'pi pi-arrow-right'"
              icon-pos="right"
              class="p-button-sm"
              :disabled="instantiating !== null || !projectAvailable"
              @click="onUse(tpl)"
            />
          </li>
        </ul>
        <hr v-if="idx < groupedTemplates.length - 1" class="tp-group-sep" />
      </div>
      <div v-if="!projectAvailable" class="tp-status tp-status-warning">
        <i class="pi pi-info-circle"></i>
        Create or open a project first — templates land as sheets inside the active project.
      </div>
    </template>

    <template #footer>
      <Button label="Close" icon="pi pi-times" @click="visible = false" autofocus />
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Dialog from "primevue/dialog";
import Button from "primevue/button";
import { useToast } from "primevue/usetoast";
import { api } from "@/api";
import { useWorkbookStore } from "@/stores/workbook";
import { getErrorMessage } from "@/utils/errors";

interface TemplateNode {
  node_id?: string;
  node_type?: string;
  parameters?: Record<string, unknown>;
}

interface TemplateOut {
  id: number;
  slug: string;
  name: string;
  description: string;
  category: string;
  status: "ready" | "wip";
  is_active: boolean;
  template_data: {
    nodes?: TemplateNode[];
    [key: string]: unknown;
  };
}

const visible = defineModel<boolean>("visible", { default: false });

const workbookStore = useWorkbookStore();
const toast = useToast();

const templates = ref<TemplateOut[]>([]);
const loading = ref(false);
const loadError = ref<string | null>(null);
const instantiating = ref<number | null>(null);

const projectAvailable = computed(() => workbookStore.projectId !== null);

// "Pretty" category labels — keys match the slugs in the YAML catalog
// (calibration, classification, curve_resolution, etc.).  Anything not
// listed here falls through to a title-cased version of the slug.
const CATEGORY_LABELS: Record<string, string> = {
  calibration: "Calibration",
  classification: "Classification",
  clustering: "Clustering",
  curve_resolution: "Curve Resolution",
  exploratory: "Exploratory Analysis",
  preprocessing: "Preprocessing",
  quality_control: "Quality Control",
  selection_design: "Variable Selection & Design",
  spectroscopy: "Spectroscopy",
};

const labelFor = (category: string): string =>
  CATEGORY_LABELS[category] ??
  category
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

const groupedTemplates = computed(() => {
  const groups = new Map<string, TemplateOut[]>();
  for (const tpl of templates.value) {
    const arr = groups.get(tpl.category) ?? [];
    arr.push(tpl);
    groups.set(tpl.category, arr);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([category, items]) => ({
      category: labelFor(category),
      items: items.slice().sort((a, b) => a.name.localeCompare(b.name)),
    }));
});

// Mirror of the backend's _extract_example_reference: a template supports
// example mode if any data.source node references a bundled dataset (one
// of eigenvector / sklearn / spectrochempy / oes).  Templates that don't
// support it instantiate via launch_mode=example with a 400 we surface,
// so we flag them upfront with a "needs data" chip.
const supportsExample = (tpl: TemplateOut): boolean => {
  const nodes = tpl.template_data?.nodes ?? [];
  return nodes.some((n) => {
    if (n.node_type !== "data.source") return false;
    const p = (n.parameters ?? {}) as Record<string, unknown>;
    const src = p.source;
    if (src === "eigenvector" && typeof p.eigenvector_dataset === "string") return true;
    if (src === "sklearn" && typeof p.sklearn_dataset === "string") return true;
    if (src === "spectrochempy" && (typeof p.example_dataset === "string" || typeof p.example_file === "string")) return true;
    if (src === "oes" && typeof p.oes_dataset === "string") return true;
    return false;
  });
};

const loadTemplates = async () => {
  loading.value = true;
  loadError.value = null;
  try {
    const response = await api.get<{ templates: TemplateOut[]; total: number }>(
      "/workflow-templates",
    );
    templates.value = response.data.templates;
  } catch (err) {
    loadError.value = getErrorMessage(err, "Failed to load templates.");
    templates.value = [];
  } finally {
    loading.value = false;
  }
};

watch(visible, (next) => {
  if (next) {
    void loadTemplates();
  }
});

const onUse = async (tpl: TemplateOut) => {
  if (!projectAvailable.value) return;
  instantiating.value = tpl.id;
  try {
    const workflowName = `${tpl.name}`;
    const sheet = await workbookStore.openTemplateAsSheet(tpl.id, workflowName);
    toast.add({
      severity: "success",
      summary: "Template applied",
      detail: `"${sheet.name}" is now active in the workbook.`,
      life: 2500,
    });
    visible.value = false;
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Could not start from template",
      detail: getErrorMessage(err, "Template instantiation failed."),
      life: 4000,
    });
  } finally {
    instantiating.value = null;
  }
};
</script>

<style scoped>
.tp-status {
  padding: 20px 8px;
  text-align: center;
  color: #6b7280;
  font-size: 0.9rem;
}

.tp-status-error {
  color: #b91c1c;
}

.tp-status-warning {
  margin-top: 16px;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 10px 12px;
  text-align: left;
}

.tp-tagline {
  margin: 0 0 12px;
  color: #4b5563;
  font-size: 0.9rem;
}

.tp-group {
  margin-bottom: 4px;
}

.tp-group-title {
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #6b7280;
  margin: 12px 0 6px;
}

.tp-group-count {
  font-weight: 400;
  color: #9ca3af;
  margin-left: 4px;
}

.tp-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: none;
}

.tp-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 4px;
  border-bottom: 1px solid #f3f4f6;
}

.tp-row:last-child {
  border-bottom: none;
}

.tp-row-main {
  flex: 1;
  min-width: 0;
}

.tp-row-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.92rem;
  font-weight: 500;
  color: #111827;
}

.tp-needs-data {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  background: #fef3c7;
  color: #92400e;
  padding: 1px 6px;
  border-radius: 3px;
}

.tp-row-description {
  margin: 4px 0 0;
  font-size: 0.82rem;
  color: #4b5563;
  line-height: 1.4;
}

.tp-group-sep {
  border: none;
  border-top: 1px solid #e5e7eb;
  margin: 12px 0 0;
}
</style>
