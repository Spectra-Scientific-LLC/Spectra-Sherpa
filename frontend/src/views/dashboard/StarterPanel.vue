<template>
  <div class="goal-starter">
    <section
      v-if="activePlan && activeProject"
      class="goal-starter__section"
      aria-labelledby="goal-starter-active-title"
      data-test="starter-active-goal"
    >
      <header class="goal-starter__header">
        <h2 id="goal-starter-active-title">Your goal</h2>
        <p class="goal-starter__goal">“{{ activeProject.goal || activePlan.goal }}”</p>
        <p class="goal-starter__meta">
          {{ activePlan.intent_label
          }}<template v-if="activeProject.name !== (activeProject.goal || activePlan.goal)"> · {{ activeProject.name }}</template>
        </p>
      </header>
      <ol class="goal-steps">
        <li
          v-for="step in activePlan.steps"
          :key="step.key"
          class="goal-step"
          :class="`goal-step--${activeStates[step.key] ?? 'todo'}`"
          :data-test="`starter-step-${step.key}`"
          :aria-current="activeStates[step.key] === 'current' ? 'step' : undefined"
        >
          <span class="goal-step__marker" aria-hidden="true">
            <i v-if="activeStates[step.key] === 'done'" class="pi pi-check"></i>
          </span>
          <div class="goal-step__body">
            <span class="goal-step__title">
              {{ step.title }}
              <span class="sr-only">({{ STATE_LABELS[activeStates[step.key] ?? "todo"] }})</span>
            </span>
            <p v-if="activeStates[step.key] === 'current'" class="goal-step__detail">{{ step.detail }}</p>
            <p
              v-if="step.key === 'run' && activeStates[step.key] === 'current' && runNeedsRecovery"
              class="goal-step__warning"
              role="status"
              data-test="starter-run-recovery"
            >
              Your last run did not finish ({{ progress?.last_run_status }}). Open it to see what went wrong, fix
              the step it names, then run again.
            </p>
            <p
              v-else-if="step.key === 'run' && activeStates[step.key] === 'current' && runInProgress"
              class="goal-step__detail"
              role="status"
            >
              A run is in progress. This step ticks once it completes.
            </p>
          </div>
          <div class="goal-step__actions">
            <Button
              v-if="step.key === 'run' && activeStates[step.key] === 'current' && runNeedsRecovery"
              label="See what went wrong"
              class="p-button-sm p-button-outlined"
              @click="guidanceStore.runAction('view_results')"
            />
            <Button
              v-if="step.action_id && activeStates[step.key] === 'current'"
              label="Go"
              class="p-button-sm"
              :aria-label="`Go to: ${step.title}`"
              @click="goToStep(step)"
            />
            <Button
              v-if="!step.completion && activeStates[step.key] === 'current'"
              label="Mark done"
              class="p-button-sm p-button-outlined"
              :loading="markingStep === step.key"
              :aria-label="`Mark done: ${step.title}`"
              :data-test="`starter-mark-${step.key}`"
              @click="setStepDone(step, true)"
            />
            <Button
              v-if="!step.completion && activeStates[step.key] === 'done' && markedSteps.has(step.key)"
              label="Undo"
              class="p-button-sm p-button-text"
              :loading="markingStep === step.key"
              :aria-label="`Mark not done: ${step.title}`"
              :data-test="`starter-undo-${step.key}`"
              @click="setStepDone(step, false)"
            />
          </div>
        </li>
      </ol>
      <p v-if="stepError" class="goal-starter__error" role="alert">{{ stepError }}</p>
      <p v-if="activeFinished" class="goal-starter__done" role="status">
        Every step is done. Describe a new goal below when you are ready for the next one.
      </p>
    </section>

    <section class="goal-starter__section" aria-labelledby="goal-starter-new-title">
      <header class="goal-starter__header">
        <h2 id="goal-starter-new-title">{{ activePlan ? "Start a new goal" : "What would you like to do?" }}</h2>
        <p class="goal-starter__hint">
          Mention your data if known, for example “predict moisture in corn NIR spectra”.
        </p>
      </header>
      <label for="goal-starter-text" class="sr-only">Your goal</label>
      <Textarea
        id="goal-starter-text"
        v-model="goalText"
        rows="3"
        auto-resize
        :maxlength="GOAL_MAX_LENGTH"
        class="goal-starter__input"
        data-test="starter-goal"
      />
      <div v-if="overview?.examples.length" class="goal-examples" aria-label="Example goals">
        <button
          v-for="example in overview.examples"
          :key="example.intent"
          type="button"
          class="goal-example"
          @click="useExample(example.goal)"
        >
          {{ example.label }}
        </button>
      </div>
      <div class="goal-starter__actions">
        <Button
          label="Plan my steps"
          icon="pi pi-list"
          :loading="planning"
          :disabled="!goalText.trim() || planning"
          data-test="starter-plan"
          @click="requestPlan"
        />
      </div>
      <p v-if="planError" class="goal-starter__error" role="alert">{{ planError }}</p>

      <div v-if="plan" class="goal-plan" data-test="starter-plan-result">
        <header class="goal-plan__header">
          <h3>{{ plan.intent_label }}</h3>
          <p>{{ plan.summary }}</p>
          <p class="goal-starter__meta">
            <template v-if="plan.template_name">Starter workflow: {{ plan.template_name }}</template>
            <template v-else>No matching starter workflow is available here; you will pick one from the gallery.</template>
            <template v-if="plan.source === 'model'"> · Suggested by the assistant</template>
          </p>
        </header>

        <div class="goal-plan__field">
          <label for="goal-starter-dataset">Start with</label>
          <Dropdown
            id="goal-starter-dataset"
            v-model="selectedDatasetKey"
            :options="datasetChoices"
            option-label="label"
            option-value="value"
            placeholder="Choose a dataset"
            class="goal-plan__control"
            aria-describedby="goal-starter-dataset-help"
            data-test="starter-dataset"
          />
          <small id="goal-starter-dataset-help" class="goal-starter__meta">
            <template v-if="selectedIsSuggested && plan.dataset">{{ plan.dataset.reason }}</template>
            <template v-else-if="selectedDatasetKey === OWN_FILES">
              {{ isLocalMode ? "You will import your files on the Data page." : "Choose a source on the Data page." }}
            </template>
            <template v-if="selectedOption?.availability === 'exact_user_acquisition_required'">
              It needs the provider's original file before it can run.
            </template>
          </small>
        </div>

        <ol class="goal-plan__steps" aria-label="Planned steps">
          <li v-for="(step, index) in plan.steps" :key="step.key" class="goal-plan__step">
            <button
              type="button"
              class="goal-plan__step-toggle"
              :aria-expanded="expandedStep === step.key"
              :aria-controls="`goal-plan-step-${step.key}`"
              @click="expandedStep = expandedStep === step.key ? null : step.key"
            >
              <span class="goal-plan__step-number">{{ index + 1 }}</span>
              <span>{{ step.title }}</span>
              <i class="pi" :class="expandedStep === step.key ? 'pi-chevron-up' : 'pi-chevron-down'" aria-hidden="true"></i>
            </button>
            <p v-show="expandedStep === step.key" :id="`goal-plan-step-${step.key}`" class="goal-step__detail">
              {{ step.detail }}
            </p>
          </li>
        </ol>

        <div class="goal-plan__field">
          <label for="goal-starter-name">Project name</label>
          <InputText id="goal-starter-name" v-model="projectName" class="goal-plan__control" maxlength="255" />
        </div>

        <div class="goal-starter__actions">
          <Button
            label="Ready to Start"
            icon="pi pi-arrow-right"
            icon-pos="right"
            :loading="starting"
            :disabled="!canStart"
            data-test="starter-ready"
            @click="start"
          />
          <small v-if="!selectedDatasetKey" class="goal-starter__meta">Choose a dataset to start.</small>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import { useGuidanceStore } from "@/stores/guidance";
import { useProjectStore } from "@/stores/project";
import {
  fetchStarterOverview,
  fetchStarterProgress,
  initialGoalText,
  IN_PROGRESS_RUN_STATUSES,
  planStarterGoal,
  setStarterStepDone,
  starterStepStates,
  UNSUCCESSFUL_RUN_STATUSES,
  type StarterOverview,
  type StarterProgress,
  type StarterStartRequest,
  type StarterStepState,
} from "@/lib/starterAdapter";
import type { ProjectSummary, StarterDatasetOption, StarterPlan, StarterStep } from "@/types";
import { getErrorMessage } from "@/utils/errors";

const props = defineProps<{
  activeProject: ProjectSummary | null;
  isLocalMode: boolean;
  starting: boolean;
}>();

const emit = defineEmits<{
  start: [request: StarterStartRequest];
  overview: [overview: StarterOverview];
}>();

const GOAL_MAX_LENGTH = 500;
const OWN_FILES = "__own_files__";
const STATE_LABELS: Record<StarterStepState, string> = { done: "done", current: "next step", todo: "to do" };

const guidanceStore = useGuidanceStore();
const projectStore = useProjectStore();
const overview = ref<StarterOverview | null>(null);
const goalText = ref("");
const plan = ref<StarterPlan | null>(null);
const planning = ref(false);
const planError = ref<string | null>(null);
const expandedStep = ref<string | null>(null);
const selectedDatasetKey = ref<string | null>(null);
const projectName = ref("");
const progress = ref<StarterProgress | null>(null);
const markingStep = ref<string | null>(null);
const stepError = ref<string | null>(null);

const activePlan = computed(() => props.activeProject?.goal_plan ?? null);
const activeStates = computed(() => starterStepStates(activePlan.value, progress.value));
const markedSteps = computed(() => new Set(activePlan.value?.completed_steps ?? []));
const runNeedsRecovery = computed(() => UNSUCCESSFUL_RUN_STATUSES.has(progress.value?.last_run_status ?? ""));
const runInProgress = computed(() => IN_PROGRESS_RUN_STATUSES.has(progress.value?.last_run_status ?? ""));
const activeFinished = computed(
  () => !!activePlan.value?.steps.length && Object.values(activeStates.value).every((state) => state === "done"),
);

function kindSuffix(option: StarterDatasetOption): string {
  if (option.kind === "experiment") return " · Your dataset";
  if (option.availability === "exact_user_acquisition_required") return " · Needs file import";
  return option.technique ? ` · ${option.technique}` : "";
}

const datasetChoices = computed(() => {
  const choices = (plan.value?.dataset_options ?? []).map((option) => ({
    label: `${option.label}${kindSuffix(option)}`,
    value: option.key,
  }));
  choices.push({ label: props.isLocalMode ? "I'll import my own files" : "Choose data later", value: OWN_FILES });
  return choices;
});
const selectedOption = computed(
  () => plan.value?.dataset_options?.find((option) => option.key === selectedDatasetKey.value) ?? null,
);
const selectedIsSuggested = computed(() => !!plan.value?.dataset && plan.value.dataset.key === selectedDatasetKey.value);
const canStart = computed(
  () => !!plan.value && !!selectedDatasetKey.value && !!projectName.value.trim() && !props.starting,
);

function defaultProjectName(goal: string): string {
  const trimmed = goal.trim();
  return trimmed.length > 60 ? `${trimmed.slice(0, 57).trimEnd()}…` : trimmed;
}

function useExample(goal: string): void {
  goalText.value = goal;
  plan.value = null;
}

async function requestPlan(): Promise<void> {
  const goal = goalText.value.trim();
  if (!goal) return;
  planning.value = true;
  planError.value = null;
  try {
    const result = await planStarterGoal(goal);
    plan.value = result;
    expandedStep.value = result.steps[0]?.key ?? null;
    selectedDatasetKey.value = result.dataset?.key ?? OWN_FILES;
    projectName.value = defaultProjectName(result.goal);
  } catch (error: unknown) {
    plan.value = null;
    planError.value = getErrorMessage(error) || "Could not plan this goal.";
  } finally {
    planning.value = false;
  }
}

function start(): void {
  if (!plan.value || !canStart.value) return;
  emit("start", {
    plan: plan.value,
    name: projectName.value.trim(),
    dataset: selectedDatasetKey.value === OWN_FILES ? null : selectedOption.value,
  });
}

async function goToStep(step: StarterStep): Promise<void> {
  // Going to a step never completes it: a step without a progress signal is
  // finished only by Mark done.
  if (step.action_id) await guidanceStore.runAction(step.action_id);
}

async function setStepDone(step: StarterStep, done: boolean): Promise<void> {
  const projectId = props.activeProject?.id;
  if (projectId == null) return;
  markingStep.value = step.key;
  stepError.value = null;
  try {
    progress.value = await setStarterStepDone(projectId, step.key, done);
    // The plan records manual completion, so reload the project that holds it.
    await projectStore.fetchProject(projectId);
  } catch (error: unknown) {
    stepError.value = getErrorMessage(error) || "Could not update this step.";
  } finally {
    markingStep.value = null;
  }
}

async function refreshProgress(): Promise<void> {
  const projectId = props.activeProject?.id;
  if (projectId == null || !activePlan.value) {
    progress.value = null;
    return;
  }
  try {
    const result = await fetchStarterProgress(projectId);
    if (props.activeProject?.id === projectId) progress.value = result;
  } catch {
    // The checklist keeps its last known state; the next refresh retries.
  }
}

function onVisibilityChange(): void {
  if (document.visibilityState === "visible") void refreshProgress();
}

watch(
  () => [props.activeProject?.id, activePlan.value?.goal] as const,
  () => {
    progress.value = null;
    void refreshProgress();
  },
  { immediate: true },
);

onMounted(async () => {
  document.addEventListener("visibilitychange", onVisibilityChange);
  try {
    overview.value = await fetchStarterOverview();
    if (!goalText.value) goalText.value = initialGoalText(overview.value);
    emit("overview", overview.value);
  } catch {
    // Starter still works without the overview: the user types a goal.
  }
});

onBeforeUnmount(() => document.removeEventListener("visibilitychange", onVisibilityChange));
</script>

<style scoped>
.goal-starter {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  max-width: 52rem;
  padding: 1.5rem 0 2rem;
}

.goal-starter__section {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.goal-starter__section + .goal-starter__section {
  border-top: 1px solid var(--surface-border);
  padding-top: 1.75rem;
}

.goal-starter__header h2,
.goal-plan__header h3 {
  margin: 0 0 0.35rem;
  font-size: 1.125rem;
  font-weight: 500;
}

.goal-plan__header h3 {
  font-size: 1rem;
}

.goal-starter__header p,
.goal-plan__header p {
  margin: 0;
}

.goal-starter__goal {
  font-size: 1rem;
}

.goal-starter__hint,
.goal-starter__meta {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.goal-starter__input,
.goal-plan__control {
  width: 100%;
}

.goal-examples {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.goal-example {
  border: 1px solid var(--surface-border);
  border-radius: 999px;
  background: var(--surface-card);
  color: var(--text-color);
  font: inherit;
  font-size: 0.8125rem;
  padding: 0.3rem 0.8rem;
  cursor: pointer;
}

.goal-example:hover,
.goal-example:focus-visible {
  border-color: var(--primary-color);
}

.goal-starter__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}

.goal-starter__error {
  margin: 0;
  color: var(--red-600, var(--ss-danger));
}

.goal-starter__done {
  margin: 0;
  color: var(--text-color-secondary);
}

.goal-plan {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: var(--surface-card);
  padding: 1rem 1.1rem;
}

.goal-plan__field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.goal-plan__field label {
  font-size: 0.875rem;
  font-weight: 500;
}

.goal-plan__steps,
.goal-steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.goal-plan__step + .goal-plan__step {
  border-top: 1px solid var(--surface-border);
}

.goal-plan__step-toggle {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  width: 100%;
  border: 0;
  background: none;
  color: var(--text-color);
  font: inherit;
  text-align: left;
  padding: 0.6rem 0;
  cursor: pointer;
}

.goal-plan__step-toggle > span:nth-child(2) {
  flex: 1;
}

.goal-plan__step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 50%;
  border: 1px solid var(--surface-border);
  font-size: 0.75rem;
  flex-shrink: 0;
}

.goal-step {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.6rem 0;
}

.goal-step + .goal-step {
  border-top: 1px solid var(--surface-border);
}

.goal-step__marker {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.25rem;
  height: 1.25rem;
  margin-top: 0.15rem;
  border-radius: 50%;
  border: 1px solid var(--surface-border);
  flex-shrink: 0;
  font-size: 0.7rem;
}

.goal-step--done .goal-step__marker {
  border-color: var(--primary-color);
  background: var(--primary-color);
  color: var(--primary-color-text, var(--ss-on-action));
}

.goal-step--current .goal-step__marker {
  border: 2px solid var(--primary-color);
}

.goal-step--done .goal-step__title {
  color: var(--text-color-secondary);
}

.goal-step__body {
  flex: 1;
  min-width: 0;
}

.goal-step__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.4rem;
}

.goal-step__warning {
  margin: 0.4rem 0 0;
  color: var(--orange-700, var(--ss-warning));
  font-size: 0.875rem;
}

.goal-step--current .goal-step__title {
  font-weight: 500;
}

.goal-step__detail {
  margin: 0.3rem 0 0;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.goal-plan__step .goal-step__detail {
  margin: 0 0 0.7rem 2.15rem;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
