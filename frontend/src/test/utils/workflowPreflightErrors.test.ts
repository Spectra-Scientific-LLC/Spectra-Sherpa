import { describe, expect, it } from "vitest";
import { getErrorMessage } from "@/utils/errors";

describe("workflow preflight error explanation", () => {
  it("retains actionable node and port issues instead of only the generic summary", () => {
    expect(getErrorMessage({
      isAxiosError: true,
      response: { data: { detail: {
        code: "workflow_preflight_failed",
        message: "Inspect validation for details",
        issues: [
          { node_id: "peaks", port: "default", message: "Required input is not connected" },
          { node_id: "split", message: "Target labels are required" },
          null,
        ],
      } } },
    })).toBe("peaks / default: Required input is not connected; split: Target labels are required");
  });

  it("keeps other structured errors and redacts credentials", () => {
    expect(getErrorMessage({
      isAxiosError: true,
      response: { data: { detail: { message: "api_key=secret" } } },
    })).toBe("api_key=[redacted]");
  });
});
