import { describe, expect, it } from "vitest";

import { SHERPA_WS_ACTION, SHERPA_WS_EVENT, getSherpaChatAction } from "@/lib/sherpaWs";

describe("sherpaWs contract", () => {
  it("uses the tool-enabled action when requested", () => {
    expect(getSherpaChatAction(false)).toBe(SHERPA_WS_ACTION.chat);
    expect(getSherpaChatAction(true)).toBe(SHERPA_WS_ACTION.chatWithTools);
  });

  it("keeps the canonical Sherpa event names stable", () => {
    expect(SHERPA_WS_EVENT.subscriptionRequired).toBe("sherpa_subscription_required");
    expect(SHERPA_WS_EVENT.dataStoryResult).toBe("sherpa_data_story_result");
  });
});
