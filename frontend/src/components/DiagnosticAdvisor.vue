<template>
  <section aria-label="Ask Sherpa about diagnostics" class="diagnostic-advisor">
    <h3>Ask Sherpa</h3>
    <p>
      Run {{ review.run_id }} · {{ selected.length }} selected observations · Review
      {{ review.revision
      }}<span v-if="review.model_kind === 'pls'">
        · {{ review.target_names?.[responseIndex] }}</span
      >
    </p>
    <p v-if="!available">
      Diagnostic interpretation requires hosted Sherpa Advisor. Local tools remain available; Hybrid
      diagnostic disclosure is not yet supported.
    </p>
    <template v-else>
      <p>
        Explain the saved evidence and discuss your next check. Decisions to mark or exclude remain
        yours.
      </p>
      <div class="actions">
        <button type="button" :disabled="disabled" @click="ask('samples')">
          Explain these samples
        </button>
        <button
          type="button"
          :disabled="
            disabled || !variables.length || !focusedSample || !selected.includes(focusedSample)
          "
          @click="ask('variables')"
        >
          {{
            variableContext === "applicability"
              ? "Explain these applicability variables"
              : "Explain these variables"
          }}
        </button>
        <button type="button" :disabled="disabled" @click="ask('next')">
          What should I check next?
        </button>
        <button
          v-if="review.model_kind === 'pls' && review.pls_applicability"
          type="button"
          :disabled="disabled"
          @click="ask('applicability')"
        >
          Explain predictor-space novelty
        </button>
      </div>
      <p v-if="variables.length && focusedSample">
        {{
          variableContext === "applicability" ? "Applicability variables" : "Variable explanation"
        }}: {{ focusedSample
        }}<span v-if="review.model_kind === 'pls' && variableContext !== 'applicability'">
          · {{ review.target_names?.[variableResponseIndex ?? responseIndex] }}</span
        >
        · {{ variables.length }} selected variables.
      </p>
      <label
        >Baseline saved run for comparison <input v-model.number="baseline" type="number" min="1"
      /></label>
      <button
        type="button"
        :disabled="disabled || !Number.isInteger(baseline) || Number(baseline) <= 0"
        @click="ask('compare')"
      >
        What changed after exclusion?
      </button>
      <p v-if="stale">
        Rerun or open the intended saved result before starting a new diagnostic discussion.
      </p>
      <p v-if="error" role="alert">{{ error }}</p>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { useProjectStore } from "@/stores/project";
import { useSherpaStore } from "@/stores/sherpa";
import { requestAdvisorPrompt } from "@/lib/advisorPromptActions";
import { diagnosticReference } from "@/utils/diagnosticAdvisor";
import type { PcaReview } from "@/utils/sampleReview";
const props = defineProps<{
  review: PcaReview;
  workflowId: number | null;
  nodeId: string;
  selected: string[];
  variables: string[];
  responseIndex: number;
  variableResponseIndex?: number;
  focusedSample?: string;
  variableContext?: "prediction" | "applicability";
  stale: boolean;
}>();
const emit = defineEmits<{ opened: [] }>();
const { appConfig, appMode, isFeatureEnabled } = useAppConfig();
const project = useProjectStore();
const sherpa = useSherpaStore();
const baseline = ref<number | null>(props.review.state.test_baseline?.run_id ?? null);
const error = ref("");
watch(
  () => props.review.run_id,
  () => {
    baseline.value = props.review.state.test_baseline?.run_id ?? null;
    error.value = "";
  },
);
const available = computed(
  () =>
    appMode.value !== "local" &&
    appConfig.value?.advisorContextPolicy !== "receipt" &&
    (isFeatureEnabled("sherpaAdvisor") || appConfig.value?.siteProfile === "pro"),
);
const disabled = computed(
  () =>
    props.stale ||
    !props.selected.length ||
    !props.workflowId ||
    !project.currentProjectId ||
    sherpa.chatState === "chatting",
);
function ask(kind: "samples" | "variables" | "next" | "compare" | "applicability") {
  if (disabled.value || !available.value) return;
  try {
    error.value = "";
    const reference = diagnosticReference(
      props.review,
      props.workflowId!,
      props.nodeId,
      kind === "variables" ? [props.focusedSample!] : props.selected,
      kind === "variables"
        ? (props.variableResponseIndex ?? props.responseIndex)
        : props.responseIndex,
      kind === "variables" ? props.variables : [],
      kind === "compare" ? baseline.value : null,
    );
    const prompts = {
      samples: "Explain these selected diagnostic samples using their saved evidence.",
      variables:
        props.variableContext === "applicability"
          ? "Explain the selected variables' Q and signed T² applicability contributions in the saved PLS predictor space. Distinguish them from prediction contributions and response error; explain sparse remainders and the limits of global screening."
          : props.review.model_kind === "pls"
            ? "Explain these selected variables and their prediction contributions using the saved diagnostic evidence."
            : "Explain these selected variables and their Q and signed T² contributions using the saved PCA evidence.",
      applicability:
        "Explain these selected observations' saved PLS scores and T²/Q predictor-space novelty, using the correct calibration or application limits and retained reference population. Distinguish predictor novelty from response error and state unavailable evidence. Passing a global screen does not establish local support or prediction certainty.",
      next: "What should I inspect next to understand these selected diagnostic samples?",
      compare:
        "Explain what changed between these saved runs after sample review; distinguish comparable evidence from descriptive changes.",
    };
    requestAdvisorPrompt(prompts[kind], {
      diagnosticScope: {
        project_id: project.currentProjectId!,
        model_kind: props.review.model_kind,
        response_label:
          props.review.model_kind === "pls"
            ? props.review.target_names?.[reference.response_index]
            : null,
        reference,
      },
    });
    emit("opened");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "Diagnostic context is unavailable.";
  }
}
</script>
<style scoped>
.diagnostic-advisor {
  border: 1px solid var(--surface-border);
  padding: 1rem;
  margin: 1rem 0;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
input {
  width: 7rem;
  margin: 0 0.5rem;
}
</style>
