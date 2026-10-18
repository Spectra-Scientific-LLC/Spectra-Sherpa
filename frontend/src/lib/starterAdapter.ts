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
  next_step: string | null;
};

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
 * without one is done once any later step is, or once the user has opened it
 * from the checklist (``visited``). The first step not done is current.
 */
export function starterStepStates(
  plan: StarterPlan | null | undefined,
  progress: Partial<Record<StarterProgressSignal, boolean>> | null | undefined,
  visited: ReadonlySet<string> = new Set(),
): Record<string, StarterStepState> {
  const steps = plan?.steps ?? [];
  const observed = steps.map((step) =>
    step.completion ? Boolean(progress?.[step.completion]) : visited.has(step.key),
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

const VISITED_PREFIX = "sherpa:starter-visited:";

/** Steps without a progress signal the user has opened; a per-viewer convenience. */
export function readVisitedSteps(projectId: number): Set<string> {
  try {
    const raw = window.localStorage.getItem(`${VISITED_PREFIX}${projectId}`);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((key): key is string => typeof key === "string") : []);
  } catch {
    return new Set();
  }
}

export function writeVisitedSteps(projectId: number, visited: ReadonlySet<string>): void {
  try {
    window.localStorage.setItem(`${VISITED_PREFIX}${projectId}`, JSON.stringify([...visited]));
  } catch {
    // Storage is optional; the checklist still follows server progress.
  }
}
