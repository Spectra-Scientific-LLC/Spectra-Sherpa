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
