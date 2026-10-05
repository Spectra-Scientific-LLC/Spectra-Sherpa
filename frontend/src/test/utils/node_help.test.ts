import { describe, expect, it } from "vitest";

import { resolveNodeHelpUrl } from "@/utils/nodeHelp";

describe("resolveNodeHelpUrl", () => {
  it("projects a qualified node help reference onto the public documentation", () => {
    expect(resolveNodeHelpUrl("docs/nodes/selection-validation.md")).toBe(
      "https://docs.spectrascientific.ai/nodes/selection-validation/",
    );
    expect(resolveNodeHelpUrl("docs/nodes/data.md")).toBe(
      "https://docs.spectrascientific.ai/nodes/data/",
    );
  });

  it.each([
    null,
    "",
    "https://example.test/nodes/data.md",
    "docs/nodes/../security.md",
    "docs/onboarding/data.md",
    "docs/nodes/Data.md",
    "docs/nodes/data.html",
    "docs/nodes/data.md?next=https://example.test",
    "docs/nodes/data.md#fragment",
  ])("fails closed for an unqualified reference: %s", (reference) => {
    expect(resolveNodeHelpUrl(reference)).toBeNull();
  });
});
