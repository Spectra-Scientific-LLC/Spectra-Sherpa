const GUIDANCE_RULE_LABELS: Record<string, string> = {
  empty_project_import: "Project setup",
  imported_no_preprocess: "Data preparation",
  workflow_saved_never_run: "Workflow run",
  correction_caveat_ignored: "Data caveat",
  idle_on_results: "Results review",
};

export function guidanceRuleLabel(ruleId?: string | null): string {
  if (!ruleId) return "Guidance";
  return GUIDANCE_RULE_LABELS[ruleId] ?? "Guidance";
}
