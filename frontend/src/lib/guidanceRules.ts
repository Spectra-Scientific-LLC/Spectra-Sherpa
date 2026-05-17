// Keep these labels aligned with the starter rule IDs in
// the guidance rules starter module.
// Each label is the user-facing chip rendered in the notification
// drawer.  Pure function — no internal identifiers should ever leak
// to the UI; any rule_id missing from this map falls through to
// the generic "Guidance" string in the function below.
const GUIDANCE_RULE_LABELS: Record<string, string> = {
  empty_project_import: "Project setup",
  imported_no_preprocess: "Data preparation",
  workflow_saved_never_run: "Workflow run",
  correction_caveat_ignored: "Data caveat",
  idle_on_results: "Results review",
  // PR5 — deploy + report rules.
  deploy_runs_no_automation: "Automation",
  report_idle_with_runs: "Reporting",
};

export function guidanceRuleLabel(ruleId?: string | null): string {
  if (!ruleId) return "Guidance";
  if (ruleId.startsWith("llm_")) return "Guidance insight";
  return GUIDANCE_RULE_LABELS[ruleId] ?? "Guidance";
}
