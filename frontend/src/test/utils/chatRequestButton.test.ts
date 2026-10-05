import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import PrimeVue from "primevue/config";
import ChatRequestButton from "@/components/ChatRequestButton.vue";

describe("chat send/stop control", () => {
  it("turns the same button red and enabled during work, then restores send", async () => {
    const wrapper = mount(ChatRequestButton, { props: { busy: false, disabled: true }, global: { plugins: [PrimeVue] } });
    expect(wrapper.get("button").attributes("aria-label")).toBe("Send message");
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
    await wrapper.setProps({ busy: true });
    expect(wrapper.get("button").attributes("aria-label")).toBe("Stop analysis");
    expect(wrapper.get("button").classes()).toContain("p-button-danger");
    expect(wrapper.get("button").attributes("disabled")).toBeUndefined();
    await wrapper.get("button").trigger("click");
    expect(wrapper.emitted("stop")).toHaveLength(1);
    expect(wrapper.emitted("send")).toBeUndefined();
    await wrapper.setProps({ busy: false, disabled: false });
    expect(wrapper.get("button").find('[data-state="send"]').exists()).toBe(true);
    expect(wrapper.get("button").classes()).not.toContain("p-button-danger");
    await wrapper.get("button").trigger("click");
    expect(wrapper.emitted("send")).toHaveLength(1);
  });
});
