import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, effectScope, h } from "vue";

import ConfirmActionDialog from "@/components/ConfirmActionDialog.vue";
import {
  confirmAction,
  pendingConfirmation,
  settleConfirmation,
  useConfirmAction,
} from "@/composables/useConfirmAction";
import { useAuthStore } from "@/stores/auth";

const options = {
  title: "Delete API key",
  message: "Delete the API key for OpenAI? Features that use it stop working until a new key is saved.",
  acceptLabel: "Delete key",
  destructive: true,
};

const dialogs: VueWrapper[] = [];
function mountDialog() {
  // Real transitions: PrimeVue binds Escape and moves focus in its enter hooks.
  const wrapper = mount(ConfirmActionDialog, { attachTo: document.body, global: { plugins: [PrimeVue], stubs: { transition: false } } });
  dialogs.push(wrapper);
  return wrapper;
}

function button(label: string): HTMLButtonElement {
  const match = Array.from(document.body.querySelectorAll("button")).find((b) => b.textContent?.trim() === label);
  if (!match) throw new Error(`No button "${label}"`);
  return match;
}

describe("confirmation dialog", () => {
  beforeEach(() => setActivePinia(createPinia()));

  afterEach(async () => {
    settleConfirmation(false);
    await flushPromises();
    for (const wrapper of dialogs.splice(0)) {
      if (wrapper.exists()) wrapper.unmount();
    }
    await flushPromises();
    document.body.innerHTML = "";
  });

  it("shows the request and resolves true only from the action button", async () => {
    const wrapper = mountDialog();
    const answer = confirmAction(options);
    await flushPromises();
    expect(document.body.textContent).toContain("Delete API key");
    expect(document.body.textContent).toContain(options.message);
    const accept = button("Delete key");
    expect(accept.classList.contains("p-button-danger")).toBe(true);
    accept.click();
    await expect(answer).resolves.toBe(true);
    expect(pendingConfirmation.value).toBeNull();
    wrapper.unmount();
  });

  it("resolves false from Cancel, which holds the initial focus", async () => {
    const wrapper = mountDialog();
    const answer = confirmAction({ ...options, destructive: false });
    await vi.waitFor(() => expect(document.activeElement).toBe(button("Cancel")));
    const cancel = button("Cancel");
    expect(document.activeElement).toBe(cancel);
    expect(button("Delete key").classList.contains("p-button-danger")).toBe(false);
    cancel.click();
    await expect(answer).resolves.toBe(false);
    wrapper.unmount();
  });

  it("resolves false when Escape closes it", async () => {
    const wrapper = mountDialog();
    const answer = confirmAction(options);
    await flushPromises();
    await vi.waitFor(() => expect(document.activeElement).toBe(button("Cancel")));
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
    await expect(answer).resolves.toBe(false);
    wrapper.unmount();
  });

  it("refuses a second request while one is open, and settles each request once", async () => {
    const first = confirmAction(options);
    await expect(confirmAction({ ...options, title: "Another" })).resolves.toBe(false);
    expect(pendingConfirmation.value?.options.title).toBe("Delete API key");
    settleConfirmation(true);
    settleConfirmation(false);
    await expect(first).resolves.toBe(true);
  });

  it("closes as declined when the signed-in user changes", async () => {
    const auth = useAuthStore();
    auth.user = { id: 1, username: "ana" } as typeof auth.user;
    const wrapper = mountDialog();
    const answer = confirmAction(options);
    await flushPromises();
    auth.user = { id: 2, username: "ben" } as typeof auth.user;
    await expect(answer).resolves.toBe(false);
    expect(pendingConfirmation.value).toBeNull();
    wrapper.unmount();
  });
});

describe("owner-scoped confirmations", () => {
  it("closes as declined when the owning component unmounts, and refuses later requests", async () => {
    let ask!: ReturnType<typeof useConfirmAction>;
    const Owner = defineComponent({
      setup() {
        ask = useConfirmAction();
        return () => h("div");
      },
    });
    const wrapper = mount(Owner);
    const answer = ask(options);
    expect(pendingConfirmation.value?.options).toEqual(options);
    wrapper.unmount();
    expect(pendingConfirmation.value).toBeNull();
    await expect(answer).resolves.toBe(false);
    await expect(ask(options)).resolves.toBe(false);
    expect(pendingConfirmation.value).toBeNull();
  });

  it("keeps ownership of the first request when the same component asks twice", async () => {
    let ask!: ReturnType<typeof useConfirmAction>;
    const Owner = defineComponent({
      setup() {
        ask = useConfirmAction();
        return () => h("div");
      },
    });
    const wrapper = mount(Owner);
    const first = ask(options);

    await expect(ask({ ...options, title: "Another" })).resolves.toBe(false);
    expect(pendingConfirmation.value?.options).toEqual(options);

    wrapper.unmount();
    expect(pendingConfirmation.value).toBeNull();
    await expect(first).resolves.toBe(false);
  });

  it("leaves another owner's open confirmation alone", async () => {
    const first = effectScope();
    const second = effectScope();
    const askFirst = first.run(() => useConfirmAction())!;
    second.run(() => useConfirmAction());
    const answer = askFirst(options);
    second.stop();
    expect(pendingConfirmation.value?.options).toEqual(options);
    settleConfirmation(true);
    await expect(answer).resolves.toBe(true);
    first.stop();
  });

  it("resolves false at once for an already-aborted signal", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(confirmAction(options, { signal: controller.signal })).resolves.toBe(false);
    expect(pendingConfirmation.value).toBeNull();
  });
});
