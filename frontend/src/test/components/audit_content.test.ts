import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AuditContent from "@/views/audit/AuditContent.vue";

const mocks = vi.hoisted(() => ({
  appConfig: {
    value: {
      audit: {
        localQuery: true,
        fullPipeline: true,
        reportPack: true,
        exportAudited: true,
      },
    },
  },
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  routeQuery: {} as Record<string, string>,
}));

vi.mock("@/api", () => ({
  api: mocks.api,
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appConfig: mocks.appConfig,
  }),
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({
    query: mocks.routeQuery,
  }),
}));

const eventResponse = {
  events: [
    {
      id: 42,
      tenant_id: "local",
      actor_id: 7,
      actor_kind: "user",
      action: "workflow.updated",
      target_type: "Workflow",
      target_id: "wf-1",
      before_state: { name: "Old" },
      after_state: { name: "New" },
      context: { project_id: "project-1" },
      request_id: "req-abcdef123456",
      ts_app_utc: "2026-05-13T12:00:00.000Z",
      ts_db_utc: "2026-05-13T12:00:00.000Z",
    },
  ],
  next_cursor: null,
  has_more: false,
};

const verifyResponse = {
  ok: true,
  rows_checked: 3,
  unchained_event_count: 0,
  orphan_chain_row_count: 0,
};

function resetCapabilities(overrides: Partial<typeof mocks.appConfig.value.audit> = {}) {
  mocks.appConfig.value = {
    audit: {
      localQuery: true,
      fullPipeline: true,
      reportPack: true,
      exportAudited: true,
      ...overrides,
    },
  };
}

function mountAuditContent() {
  return mount(AuditContent, {
    global: {
      stubs: {
        i: true,
      },
    },
  });
}

describe("AuditContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.routeQuery = {};
    resetCapabilities();
    mocks.api.get.mockImplementation(async (url: string) => {
      if (url === "/audit/verify") return { data: verifyResponse };
      return { data: eventResponse };
    });
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:test"),
      revokeObjectURL: vi.fn(),
    });
    HTMLAnchorElement.prototype.click = vi.fn();
  });

  it("loads and renders the audit timeline on mount", async () => {
    const wrapper = mountAuditContent();
    await flushPromises();

    expect(mocks.api.get).toHaveBeenCalledWith("/audit/events", {
      params: {
        limit: 50,
        target_type: "Workflow",
      },
    });
    expect(wrapper.get('[data-testid="audit-event-list"]').text()).toContain("workflow.updated");
    expect(wrapper.text()).toContain("Workflow wf-1");
    expect(wrapper.text()).toContain("Chain Health");
    expect(wrapper.text()).toContain("Verified");
  });

  it("prefills timeline filters from route query", async () => {
    mocks.routeQuery = {
      action: "model_artifact.deleted",
      target_type: "ModelArtifact",
      target_id: "model-9",
    };

    mountAuditContent();
    await flushPromises();

    expect(mocks.api.get).toHaveBeenCalledWith("/audit/events", {
      params: {
        action: "model_artifact.deleted",
        limit: 50,
        target_id: "model-9",
        target_type: "ModelArtifact",
      },
    });
  });

  it("generates a report pack and renders the manifest summary", async () => {
    mocks.api.post.mockResolvedValue({
      data: new Blob(["zip"]),
      headers: {
        "content-disposition": 'attachment; filename="audit-report-pack-test.zip"',
        "x-audit-report-pack-id": "pack-123456789",
        "x-audit-report-pack-row-count": "5",
        "x-audit-report-pack-file-count": "7",
        "x-audit-report-pack-sha256": "abcdef1234567890",
        "x-audit-report-pack-verified": "true",
      },
    });

    const wrapper = mountAuditContent();
    await flushPromises();
    await wrapper.get('[data-testid="generate-report-pack"]').trigger("click");
    await flushPromises();

    expect(mocks.api.post).toHaveBeenCalledWith(
      "/audit/report-pack",
      {
        format: "jsonl",
        include_pdf: true,
        scope_type: "Workflow",
        target_type: "Workflow",
      },
      { responseType: "blob" },
    );
    expect(wrapper.text()).toContain("Verified");
    expect(wrapper.text()).toContain("5");
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it("parses JSON detail from blob error responses", async () => {
    const errorBlob = new Blob([JSON.stringify({ detail: "Chain verification failed" })], {
      type: "application/json",
    });
    mocks.api.post.mockRejectedValue({
      isAxiosError: true,
      message: "Request failed with status code 409",
      response: {
        data: errorBlob,
      },
    });

    const wrapper = mountAuditContent();
    await flushPromises();
    await wrapper.get('[data-testid="generate-report-pack"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Chain verification failed");
  });

  it("downloads raw JSONL exports with the current filters", async () => {
    mocks.api.get.mockImplementation(async (url: string) => {
      if (url === "/audit/export") {
        return {
          data: new Blob(["{}"]),
          headers: {
            "content-disposition": 'attachment; filename="audit-export-test.jsonl"',
          },
        };
      }
      return { data: eventResponse };
    });

    const wrapper = mountAuditContent();
    await flushPromises();
    await wrapper.get('[data-testid="export-jsonl"]').trigger("click");
    await flushPromises();

    expect(mocks.api.get).toHaveBeenCalledWith("/audit/export", {
      params: {
        format: "jsonl",
        limit: 50,
        target_type: "Workflow",
      },
      responseType: "blob",
    });
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it("disables pack and export actions when entitlements are missing", async () => {
    resetCapabilities({
      reportPack: false,
      exportAudited: false,
    });

    const wrapper = mountAuditContent();
    await flushPromises();

    expect(wrapper.get('[data-testid="generate-report-pack"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="export-jsonl"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="export-csv"]').attributes("disabled")).toBeDefined();
  });
});
