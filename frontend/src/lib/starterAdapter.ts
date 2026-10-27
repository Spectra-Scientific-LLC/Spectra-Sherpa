import api from "@/api/client";
import type { StarterDatasetOption, StarterPlan, StarterProgressSignal } from "@/types";

export interface StarterExample {
  intent: string;
  label: string;
  goal: string;
}

export interface StarterOverview {
  is_first_run: boolean;
  suggested_goal: string;
  last_goal: string | null;
  examples: StarterExample[];
  model_planning_available: boolean;
}

export type StarterProgress = Record<StarterProgressSignal, boolean> & {
  project_id: number;
  /** Status of the newest run; a failed or cancelled run offers recovery. */
  last_run_status: string | null;
  next_step: string | null;
};

/** Run statuses that leave the Run step current, mirroring the backend. */
export const UNSUCCESSFUL_RUN_STATUSES: ReadonlySet<string> = new Set(["partial", "error", "failed", "cancelled"]);
export const IN_PROGRESS_RUN_STATUSES: ReadonlySet<string> = new Set(["pending", "running"]);

export type StarterStepState = "done" | "current" | "todo";

/** What the Starter panel hands the Dashboard when the user clicks Ready to Start. */
export interface StarterStartRequest {
  plan: StarterPlan;
  name: string;
  dataset: StarterDatasetOption | null;
}

/** Editable display name, not a scientific revision or an LLM-generated goal. */
export function starterProjectName(
  plan: StarterPlan,
  dataset: StarterDatasetOption | null,
  existingNames: readonly string[] = [],
): string {
  const words = (value: string, limit: number) => value
    .replace(/\([^)]*\)/g, " ")
    .replace(/\bv\d+(?:\.\d+)*\b/gi, " ")
    .replace(/[—–:;|]/g, " ")
    .trim().split(/\s+/).filter(Boolean).slice(0, limit).join(" ");
  const subject = Array.from(words(dataset?.label ?? "", 4)).slice(0, 64).join("").trim();
  // Display-name vocabulary only: model identity/execution still belongs to
  // the selected template. Keep its leading acronym rather than inferring a
  // model from the user's free-text goal. Non-model starters omit this part.
  const model = (plan.template_name?.match(/^([A-Z][A-Z0-9]+(?:-[A-Z0-9]+)*)(?=\s|$)/)?.[1] ?? "").slice(0, 32);
  const purpose = ({
    explore: "Exploration", calibrate: "Regression", classify: "Classification",
    preprocess: "Preprocessing", peaks: "Peak analysis", cluster: "Clustering", resolve: "Decomposition",
  } as Record<string, string>)[plan.intent] ?? "Analysis";
  const base = [subject, model, purpose].filter(Boolean).join(" — ");
  const names = new Set(existingNames.map(name => name.trim().toLocaleLowerCase()));
  let version = 1;
  while (names.has(`${base} — v${version}`.toLocaleLowerCase())) version += 1;
  return `${base} — v${version}`;
}

export async function fetchStarterOverview(): Promise<StarterOverview> {
  const { data } = await api.get<StarterOverview>("/starter");
  return data;
}

export async function planStarterGoal(goal: string): Promise<StarterPlan> {
  const { data } = await api.post<StarterPlan>("/starter/plan", { goal });
  return data;
}

export async function fetchStarterProgress(projectId: number): Promise<StarterProgress> {
  const { data } = await api.get<StarterProgress>(`/starter/projects/${projectId}/progress`);
  return data;
}

/** Mark, or with ``done = false`` reopen, a step the app cannot observe. */
export async function setStarterStepDone(projectId: number, stepKey: string, done: boolean): Promise<StarterProgress> {
  const key = encodeURIComponent(stepKey);
  const { data } = done
    ? await api.post<StarterProgress>(`/starter/projects/${projectId}/steps/${key}/complete`)
    : await api.delete<StarterProgress>(`/starter/projects/${projectId}/steps/${key}/complete`);
  return data;
}

/**
 * The goal box starts from the user's last goal; on first run it starts from
 * the suggested beginner goal. Mirrors the backend's ``StarterOverview``.
 */
export function initialGoalText(overview: StarterOverview | null): string {
  if (!overview) return "";
  if (overview.last_goal) return overview.last_goal;
  return overview.is_first_run ? overview.suggested_goal : "";
}

/**
 * Per-step state, mirroring ``step_states`` in ``app/lib/starter_goal.py``.
 *
 * A step with a progress signal is done once the signal is observed. A step
 * without one is done once the user marks it done (``completed_steps``) or
 * once any later step is. The first step not done is current.
 */
export function starterStepStates(
  plan: StarterPlan | null | undefined,
  progress: Partial<Record<StarterProgressSignal, boolean>> | null | undefined,
): Record<string, StarterStepState> {
  const steps = plan?.steps ?? [];
  const marked = new Set(plan?.completed_steps ?? []);
  const observed = steps.map((step) =>
    step.completion ? Boolean(progress?.[step.completion]) : marked.has(step.key),
  );
  const states: Record<string, StarterStepState> = {};
  let currentAssigned = false;
  steps.forEach((step, index) => {
    const done = observed[index] || (!step.completion && observed.slice(index + 1).some(Boolean));
    if (done) {
      states[step.key] = "done";
    } else if (!currentAssigned) {
      states[step.key] = "current";
      currentAssigned = true;
    } else {
      states[step.key] = "todo";
    }
  });
  return states;
}
