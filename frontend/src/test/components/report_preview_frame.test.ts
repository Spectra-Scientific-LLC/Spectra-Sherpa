import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ReportPreviewFrame from "@/components/ReportPreviewFrame.vue";

describe("report preview isolation", () => {
  it("allows help tabs without enabling scripts, forms, top navigation or sandbox escape", async () => {
    const wrapper = mount(ReportPreviewFrame, { props: { html: "<p>Retained report</p>" } });
    const frame = wrapper.get("iframe");
    expect(frame.attributes("sandbox").split(/\s+/).sort()).toEqual([
      "allow-popups", "allow-same-origin",
    ]);
    expect(frame.attributes("title")).toBe("Report preview");
    expect(frame.attributes("srcdoc")).toBe("<p>Retained report</p>");
    await wrapper.setProps({ html: "<p>Next retained report</p>" });
    expect(frame.attributes("srcdoc")).toBe("<p>Next retained report</p>");
  });
});
