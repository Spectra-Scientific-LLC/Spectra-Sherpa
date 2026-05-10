import { describe, expect, it } from "vitest";

import { SHERPA_WS_ACTION, SHERPA_WS_EVENT, getSherpaChatAction } from "@/lib/sherpaWs";

describe("sherpaWs contract", () => {
  it("uses the tool-enabled action when requested", () => {
    expect(getSherpaChatAction(false)).toBe(SHERPA_WS_ACTION.chat);
    expect(getSherpaChatAction(true)).toBe(SHERPA_WS_ACTION.chatWithTools);
  });

  it("exports the full canonical Sherpa action set", () => {
    expect(SHERPA_WS_ACTION.decide).toBe("sherpa_decide");
    expect(SHERPA_WS_ACTION.identifyPeaks).toBe("sherpa_identify_peaks");
    expect(SHERPA_WS_ACTION.generateCode).toBe("sherpa_generate_code");
  });

  it("keeps the canonical Sherpa event names stable", () => {
    expect(SHERPA_WS_EVENT.decisionAck).toBe("sherpa_decision_ack");
    expect(SHERPA_WS_EVENT.chatFollowUps).toBe("sherpa_chat_follow_ups");
    expect(SHERPA_WS_EVENT.subscriptionRequired).toBe("sherpa_subscription_required");
    expect(SHERPA_WS_EVENT.dataStoryResult).toBe("sherpa_data_story_result");
  });
});
