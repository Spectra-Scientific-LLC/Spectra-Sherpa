import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import { splitFollowUps } from "@/utils/followUps";
import FollowUpChips from "@/components/FollowUpChips.vue";

describe("follow-up presentation", () => {
  it.each(["follow_up", "follow_ups"])("removes retained %s markers and keeps three clickable questions", (tag) => {
    const result = splitFollowUps(`Inspect residuals.\n<${tag}>\n- Why PCA?\n- Try PLS?\n- How many factors?\n- Fourth?\n</${tag}>`);
    expect(result.text).toBe("Inspect residuals.");
    expect(result.suggestions).toEqual(["Why PCA?", "Try PLS?", "How many factors?"]);
    const wrapper = mount(FollowUpChips, { props: { suggestions: result.suggestions } });
    expect(wrapper.findAll("button")).toHaveLength(3);
    expect(wrapper.find("[aria-hidden=true]").text()).toBe("👉");
    wrapper.find("button").trigger("click");
    expect(wrapper.emitted("select")?.[0]).toEqual(["Why PCA?"]);
    expect(wrapper.text()).not.toContain("<follow");
  });
});
