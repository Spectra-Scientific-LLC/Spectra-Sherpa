<script setup lang="ts">
import { computed, ref } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import type { DatasetAnalysisReadiness, SherpaDatasetDict } from "@/types";

const props = defineProps<{
  readiness: DatasetAnalysisReadiness;
  binding?: SherpaDatasetDict["analysis_binding"];
  unbinding?: boolean;
  targetOptions?: Array<{
    label: string;
    value: string;
    type: "categorical" | "continuous" | null;
    detail: string;
    disabled?: boolean;
  }>;
  groupOptions?: Array<{ label: string; value: string; detail: string; disabled?: boolean }>;
  selectedTarget?: string;
  selectedGroup?: string;
  loading?: boolean;
  previewError?: string | null;
  isTargetPreview?: boolean;
  selectionStatus?: "loading" | "idle" | "saving" | "saved" | "error";
}>();
const emit = defineEmits<{
  unbind: [];
  "update:selectedTarget": [value: string];
  "update:selectedGroup": [value: string];
}>();
const expandedGroup = ref<string | null>(null);
const groupsHelpVisible = ref(false);

const groups = computed(() => [
  {
    key: "compatible" as const,
    label: "Available",
    value: props.readiness.counts.compatible,
    title: namesFor("compatible"),
  },
  {
    key: "needs_target" as const,
    label: "Needs target / labels",
    value: props.readiness.counts.needs_target,
    title: detailsFor("needs_target"),
  },
  {
    key: "needs_source" as const,
    label: "Needs another source",
    value: props.readiness.counts.needs_source,
    title: detailsFor("needs_source"),
  },
  {
    key: "incompatible" as const,
    label: "Not compatible",
    value: props.readiness.counts.incompatible,
    title: detailsFor("incompatible"),
  },
  {
    key: "pending" as const,
    label: "Under scientific qualification",
    value: props.readiness.counts.pending,
    title: detailsFor("pending"),
  },
  {
    key: "unavailable" as const,
    label: "Unavailable",
    value: props.readiness.counts.unavailable ?? 0,
    title: diagnosticDetails.value,
  },
]);

const diagnosticDetails = computed(() =>
  props.readiness.diagnostics?.length
    ? props.readiness.diagnostics.map((item) => `${item.message} ${item.detail}`).join("\n")
    : "None",
);

function namesFor(status: string): string {
  const names = props.readiness.decisions
    .filter((decision) => decision.display_status === status)
    .map((decision) => decision.template_name);
  return names.length ? names.join("\n") : "None";
}

function detailsFor(status: string): string {
  const lines = props.readiness.decisions
    .filter((decision) => decision.display_status === status)
    .map((decision) => {
      const reasons = decision.reasons.map((reason) => reason.message).filter(Boolean);
      return reasons.length
        ? `${decision.template_name}: ${reasons.join(" ")}`
        : decision.template_name;
    });
  return lines.length ? lines.join("\n") : "None";
}

const targetValue = computed(() => {
  const profile = props.readiness.profile;
  if (!profile) return "Needs metadata review";
  if (!profile.target_type) return "None";
  return `${profile.target_type} · ${profile.target_fields.join(", ")}`;
});

const groupValue = computed(() => props.readiness.profile?.group_fields.join(", ") || "None");

function toggleDetails(key: string): void {
  expandedGroup.value = expandedGroup.value === key ? null : key;
}

const expandedDetails = computed(() => {
  const key = expandedGroup.value;
  if (!key) return [];
  return props.readiness.decisions
    .filter((decision) => decision.display_status === key)
    .map((decision) => ({
      name: decision.template_name,
      detail:
        decision.reasons
          .map((reason) => reason.message)
          .filter(Boolean)
          .join(" ") || "Structurally available for this dataset.",
    }));
});
</script>

<template>
  <details
    class="analysis-readiness"
    aria-label="Analysis readiness"
    :aria-busy="loading || undefined"
    :open="Boolean(targetOptions?.length)"
  >
    <summary class="analysis-readiness__heading">
      <div>
        <h3>Analysis readiness</h3>
        <span
          title="Checks declared data shape, target, source, and technique metadata. Scientific sufficiency is checked when the workflow runs."
        >
          {{
            isTargetPreview && loading
              ? "Recomputing target-choice preview"
              : isTargetPreview && previewError
                ? "Target-choice preview unavailable"
                : isTargetPreview
                  ? "Target-choice preview"
                  : "Structural profile"
          }}
        </span>
      </div>
    </summary>

    <Button
      v-if="binding"
      label="Remove target binding"
      icon="pi pi-times"
      class="p-button-sm p-button-text analysis-readiness__unbind"
      :loading="unbinding"
      @click="emit('unbind')"
    />

    <p v-if="loading" class="analysis-readiness__diagnostic" role="status">
      Recomputing analyses for this target…
    </p>

    <p
      v-else-if="previewError"
      class="analysis-readiness__diagnostic analysis-readiness__diagnostic--error"
      role="alert"
    >
      {{ previewError }} No compatibility decision will be carried to Workflow.
    </p>

    <p
      v-else-if="readiness.status && readiness.status !== 'ready'"
      class="analysis-readiness__diagnostic"
      role="status"
    >
      {{ readiness.diagnostics?.[0]?.message }}
    </p>

    <dl v-if="readiness.profile" class="analysis-readiness__profile">
      <div
        title="The admitted scientific role and dimensional modality used for matching analyses."
        tabindex="0"
        :aria-label="`Data role ${readiness.profile.primary_role}; modality ${readiness.profile.modality}`"
      >
        <dt>Data</dt>
        <dd>{{ readiness.profile.primary_role }} · {{ readiness.profile.modality }}</dd>
      </div>
      <div
        title="Technique is an advisory recommendation. A mismatch does not block an otherwise structurally compatible analysis."
        tabindex="0"
        :aria-label="`Technique ${readiness.profile.technique}. Technique is advisory and does not block structural compatibility.`"
      >
        <dt>Technique</dt>
        <dd>{{ readiness.profile.technique }}</dd>
      </div>
      <div title="Choose the sample annotation to use as the target in the next analysis.">
        <dt>Target</dt>
        <dd v-if="targetOptions?.length">
          <Dropdown
            :model-value="selectedTarget ?? ''"
            :options="targetOptions"
            option-label="label"
            option-value="value"
            option-disabled="disabled"
            class="analysis-readiness__dropdown"
            aria-label="Target for the next analysis"
            :disabled="loading || selectionStatus === 'loading' || selectionStatus === 'saving'"
            @update:model-value="emit('update:selectedTarget', $event)"
          >
            <template #option="slotProps">
              <div class="analysis-readiness__option">
                <span>{{ slotProps.option.label }}</span>
                <small>{{ slotProps.option.detail }}</small>
              </div>
            </template>
          </Dropdown>
        </dd>
        <dd v-else>{{ targetValue }}</dd>
      </div>
      <div
        :title="groupOptions?.length ? 'Choose a non-constant grouping field for grouped validation.' : undefined"
      >
        <dt>
          Groups
          <button
            type="button"
            class="field-help"
            aria-label="Explain groups"
            :aria-expanded="groupsHelpVisible"
            title="What are groups?"
            @click.stop="groupsHelpVisible = !groupsHelpVisible"
          >?</button>
        </dt>
        <dd v-if="groupOptions?.length">
          <Dropdown
            :model-value="selectedGroup ?? ''"
            :options="groupOptions"
            option-label="label"
            option-value="value"
            option-disabled="disabled"
            :disabled="
              !selectedTarget ||
              loading ||
              selectionStatus === 'loading' ||
              selectionStatus === 'saving'
            "
            class="analysis-readiness__dropdown"
            aria-label="Grouping field for the next analysis"
            @update:model-value="emit('update:selectedGroup', $event)"
          />
        </dd>
        <dd v-else>{{ groupValue }}</dd>
        <p v-if="groupsHelpVisible" class="field-help-text" role="status">
          Groups identify repeated acquisition blocks, instruments, or replicates. Grouped
          validation keeps all rows from one group in the same split so the test result does not
          leak information from a related sample.
        </p>
      </div>
    </dl>

    <p
      v-if="
        selectionStatus === 'saving' || selectionStatus === 'saved' || selectionStatus === 'error'
      "
      class="analysis-readiness__persistence"
      :class="{ 'analysis-readiness__persistence--error': selectionStatus === 'error' }"
      role="status"
    >
      {{
        selectionStatus === "saving"
          ? "Saving selection…"
          : selectionStatus === "saved"
            ? "Saved with this dataset."
            : "Selection is not saved."
      }}
    </p>

    <div v-if="!loading && !previewError" class="analysis-readiness__counts">
      <button
        v-for="group in groups"
        :key="group.key"
        type="button"
        class="analysis-readiness__count"
        :title="group.title"
        :aria-label="`${group.value} ${group.label}. ${group.title}`"
        :aria-expanded="expandedGroup === group.key"
        :disabled="loading"
        @click="toggleDetails(group.key)"
      >
        <strong>{{ group.value }}</strong>
        <span>{{ group.label }}</span>
      </button>
    </div>
    <div v-if="expandedGroup" class="analysis-readiness__details" role="status">
      <strong>{{ groups.find((group) => group.key === expandedGroup)?.label }}</strong>
      <ul v-if="expandedDetails.length">
        <li v-for="item in expandedDetails" :key="item.name">
          <b>{{ item.name }}</b> — {{ item.detail }}
        </li>
      </ul>
      <p v-else>No analyses in this category.</p>
    </div>
  </details>
</template>

<style scoped>
.analysis-readiness {
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  margin: 0 0 1rem;
  padding: 0;
  background: var(--surface-card);
}

.analysis-readiness__heading {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 0.7rem;
  cursor: pointer;
  padding: 0.85rem 1rem;
}

.analysis-readiness__heading > div {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.18rem;
}

.analysis-readiness[open] > .analysis-readiness__heading {
  border-bottom: 1px solid var(--surface-border);
}

.analysis-readiness__heading h3 {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.25;
}

.analysis-readiness__heading span {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  line-height: 1.35;
  cursor: help;
}

.analysis-readiness__profile,
.analysis-readiness__counts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 0.5rem;
  margin: 0.75rem 1rem 0;
}

.analysis-readiness__persistence {
  margin: 0.65rem 1rem 0;
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

.analysis-readiness__persistence--error {
  color: var(--red-600);
}

.analysis-readiness__profile > div,
.analysis-readiness__count {
  min-width: 0;
  padding: 0.55rem 0.65rem;
  border-radius: 7px;
  background: var(--surface-ground);
  cursor: help;
  border: 0;
  color: inherit;
  text-align: left;
}

.analysis-readiness__diagnostic {
  margin: 0.7rem 1rem 0;
  color: var(--orange-700);
  font-size: 0.82rem;
}

.analysis-readiness__diagnostic--error {
  color: var(--red-600);
}

.analysis-readiness__unbind {
  margin: 0.55rem 1rem 0;
}

.analysis-readiness__profile dt,
.analysis-readiness__count span {
  color: var(--text-color-secondary);
  font-size: 0.72rem;
}

.analysis-readiness__profile dd {
  margin: 0.2rem 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.82rem;
  font-weight: 600;
}

.field-help {
  width: 1.15rem;
  height: 1.15rem;
  margin-left: 0.25rem;
  padding: 0;
  border: 1px solid currentColor;
  border-radius: 50%;
  background: transparent;
  color: var(--text-color-secondary);
  font-size: 0.7rem;
  line-height: 1;
  cursor: help;
}

.field-help-text {
  grid-column: 1 / -1;
  margin: 0.35rem 0 0;
  color: var(--text-color-secondary);
  font-size: 0.76rem;
  line-height: 1.35;
}

.analysis-readiness__dropdown {
  width: 100%;
  font-weight: 400;
}

.analysis-readiness__option {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  max-width: 30rem;
}

.analysis-readiness__option small {
  color: var(--text-color-secondary);
  line-height: 1.25;
  white-space: normal;
}

.analysis-readiness__details {
  margin: 0.65rem 1rem 1rem;
  padding: 0.7rem;
  border-radius: 7px;
  background: var(--surface-ground);
  font-size: 0.8rem;
}

.analysis-readiness__counts {
  margin-bottom: 1rem;
}

.analysis-readiness__counts:has(+ .analysis-readiness__details) {
  margin-bottom: 0;
}

.analysis-readiness__details ul {
  margin: 0.45rem 0 0;
  padding-left: 1.1rem;
}

.analysis-readiness__count {
  display: flex;
  align-items: baseline;
  gap: 0.45rem;
}

.analysis-readiness__count strong {
  font-size: 1.05rem;
}
</style>
