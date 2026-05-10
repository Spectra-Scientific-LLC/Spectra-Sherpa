/**
 * Focused tests for the Guidance tab inside NotificationCenterDrawer.
 *
 * What we're protecting:
 * - The drawer surfaces friendly rule labels (PR3) instead of raw
 *   ``rule_id`` strings to end users.  Regressing this would leak
 *   internal identifiers like ``deploy_runs_no_automation`` into a
 *   user-visible chip.
 * - PR5's two new rules (``deploy_runs_no_automation``,
 *   ``report_idle_with_runs``) have labels in ``guidanceRules.ts``
 *   so they don't fall through to the generic "Guidance" fallback.
 * - The friendly-label fallback for ``llm_*`` rules ("Guidance
 *   insight") still works.
 *
 * The drawer is a heavy PrimeVue component.  Rather than mount the
 * full template (which requires stubbing Sidebar + Button + hooking
 * up two stores), we test the user-facing label behaviour through
 * the pure ``guidanceRuleLabel`` function — that's exactly what the
 * drawer template binds to per-row.  Behaviour is contract-level;
 * full-template render tests can land in PR8+ if the drawer grows
 * more interaction surface.
 */
import { describe, expect, it } from "vitest";
import { guidanceRuleLabel } from "@/lib/guidanceRules";

describe("guidance notification labels (drawer chip)", () => {
  it("PR1 starter rules have friendly labels", () => {
    expect(guidanceRuleLabel("empty_project_import")).toBe("Project setup");
    expect(guidanceRuleLabel("imported_no_preprocess")).toBe("Data preparation");
    expect(guidanceRuleLabel("workflow_saved_never_run")).toBe("Workflow run");
    expect(guidanceRuleLabel("correction_caveat_ignored")).toBe("Data caveat");
    expect(guidanceRuleLabel("idle_on_results")).toBe("Results review");
  });

  it("PR5 rules have friendly labels", () => {
    expect(guidanceRuleLabel("deploy_runs_no_automation")).toBe("Automation");
    expect(guidanceRuleLabel("report_idle_with_runs")).toBe("Reporting");
  });

  it('LLM-sourced rule ids fall through to "Guidance insight"', () => {
    expect(guidanceRuleLabel("llm_run_workflow")).toBe("Guidance insight");
    expect(guidanceRuleLabel("llm_create_folder_watch")).toBe("Guidance insight");
    expect(guidanceRuleLabel("llm_anything_else")).toBe("Guidance insight");
  });

  it('unknown rule ids fall through to the safe "Guidance" generic', () => {
    expect(guidanceRuleLabel("totally_made_up_rule")).toBe("Guidance");
    expect(guidanceRuleLabel(null)).toBe("Guidance");
    expect(guidanceRuleLabel(undefined)).toBe("Guidance");
    expect(guidanceRuleLabel("")).toBe("Guidance");
  });

  it("never returns a raw rule_id (would leak internal identifier)", () => {
    // Defensive: future drift would catch us if someone removed the
    // fallback behaviour.  None of the labels for known rules should
    // contain the underscore-style id.
    const knownIds = [
      "empty_project_import",
      "imported_no_preprocess",
      "workflow_saved_never_run",
      "correction_caveat_ignored",
      "idle_on_results",
      "deploy_runs_no_automation",
      "report_idle_with_runs",
    ];
    for (const id of knownIds) {
      expect(guidanceRuleLabel(id)).not.toContain("_");
    }
  });
});
