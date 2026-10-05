import { describe, expect, it } from "vitest";
import { activeWorkflowQuery } from "@/utils/workflowDeepLink";

describe("activeWorkflowQuery", () => {
  it("replaces a stale candidate ID while retaining unrelated query state", () => {
    expect(activeWorkflowQuery(
      { project_id: "104", workflow_id: "257", source: "campaign" }, 104, 255,
    )).toEqual({ project_id: "104", workflow_id: "255", source: "campaign" });
  });

  it("does not rewrite a matching deep link or create one on ordinary workflow navigation", () => {
    expect(activeWorkflowQuery({ project_id: "104", workflow_id: "255" }, 104, 255)).toBeNull();
    expect(activeWorkflowQuery({ project_id: "104" }, 104, 255)).toBeNull();
  });

  it("does not advertise an unknown or invalid sheet", () => {
    expect(activeWorkflowQuery({ workflow_id: "257" }, 104, null)).toBeNull();
    expect(activeWorkflowQuery({ workflow_id: "257" }, null, 255)).toBeNull();
    expect(activeWorkflowQuery({ workflow_id: "257" }, 104, NaN)).toBeNull();
  });
});
