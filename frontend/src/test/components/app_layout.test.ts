/* eslint-disable vue/one-component-per-file */
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent } from "vue";

const mocks = vi.hoisted(() => ({
  routeMeta: { public: false as boolean },
}));

vi.mock("vue-router", async () => {
  const actual = await vi.importActual<typeof import("vue-router")>("vue-router");
  return {
    ...actual,
    useRoute: () => ({
      meta: mocks.routeMeta,
    }),
  };
});

vi.mock("@/layouts/MainLayout.vue", () => ({
  default: defineComponent({
    name: "MainLayoutStub",
    template: '<div data-test="main-layout">main layout</div>',
  }),
}));

import App from "@/App.vue";

describe("App layout selection", () => {
  beforeEach(() => {
    mocks.routeMeta.public = false;
  });

  it("renders the auth route directly for public routes", () => {
    mocks.routeMeta.public = true;

    const wrapper = mount(App, {
      global: {
        stubs: {
          RouterView: defineComponent({
            name: "RouterViewStub",
            template: '<div data-test="router-view">auth route</div>',
          }),
        },
      },
    });

    expect(wrapper.find('[data-test="router-view"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="main-layout"]').exists()).toBe(false);
  });

  it("renders the full workspace shell for non-public routes", () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          RouterView: defineComponent({
            name: "RouterViewStub",
            template: '<div data-test="router-view">auth route</div>',
          }),
        },
      },
    });

    expect(wrapper.find('[data-test="main-layout"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="router-view"]').exists()).toBe(false);
  });
});
