import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CollectionDefinitionPanel, {
  type CollectionDefinitionReceipt,
} from "@/views/data/CollectionDefinitionPanel.vue";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/api/client", () => ({ default: mocks }));

vi.mock("primevue/button", () => ({
  default: defineComponent({
    name: "PrimeButtonStub",
    props: { label: { type: String, default: "" }, disabled: Boolean, loading: Boolean },
    emits: ["click"],
    template: "<button :disabled='disabled' @click='$emit(\"click\")'>{{ label }}</button>",
  }),
}));

vi.mock("primevue/progressspinner", () => ({
  default: defineComponent({ name: "ProgressSpinner", template: "<span>loading</span>" }),
}));

vi.mock("primevue/tag", () => ({
  default: defineComponent({
    name: "Tag",
    props: { value: { type: String, default: "" } },
    template: "<span>{{ value }}</span>",
  }),
}));

function receipt(
  status: CollectionDefinitionReceipt["status"],
  experimentId = 12,
): CollectionDefinitionReceipt {
  const bound = status !== "absent";
  const current = status === "attached" || status === "preview";
  return {
    schema_version: "spectrasherpa-collection-definition-receipt/1",
    status,
    experiment_id: experimentId,
    definition_sha256: bound ? "a".repeat(64) : null,
    source_manifest_sha256: current ? "b".repeat(64) : null,
    scientific_collection_sha256: current ? "c".repeat(64) : null,
    file_count: current ? 33 : 0,
    row_count: bound ? 33 : 0,
    column_count: bound ? 14 : 0,
    columns: bound ? ["sample_id", "specimen_id", "block"] : [],
    shape: current ? [33, 1868] : null,
    dataset_id: bound ? "verified-collection/1" : null,
    title: bound ? "Verified collection" : null,
    target_present: false,
    sample_classes_present: false,
    message:
      status === "stale"
        ? "The saved definition no longer matches the current files or parsed assets."
        : `${status} definition`,
  };
}

function button(wrapper: ReturnType<typeof mount>, label: string) {
  return wrapper.findAll("button").find((candidate) => candidate.text() === label);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("CollectionDefinitionPanel", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
    mocks.put.mockReset();
    mocks.delete.mockReset();
  });

  it("loads only on expansion and invalidates a closed panel when its source changes", async () => {
    mocks.get.mockResolvedValue({ data: receipt("attached") });
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "initial" },
    });
    await flushPromises();
    expect(mocks.get).not.toHaveBeenCalled();
    const details = wrapper.get("details");
    (details.element as HTMLDetailsElement).open = true;
    await details.trigger("toggle");
    await flushPromises();
    expect(mocks.get).toHaveBeenCalledTimes(1);
    (details.element as HTMLDetailsElement).open = false;
    await details.trigger("toggle");
    (details.element as HTMLDetailsElement).open = true;
    await details.trigger("toggle");
    expect(mocks.get).toHaveBeenCalledTimes(1);
    (details.element as HTMLDetailsElement).open = false;
    await details.trigger("toggle");
    await wrapper.setProps({ refreshKey: "modified-files" });
    expect(mocks.get).toHaveBeenCalledTimes(1);
    (details.element as HTMLDetailsElement).open = true;
    await details.trigger("toggle");
    await flushPromises();
    expect(mocks.get).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("explains catalog custody without offering JSON replacement for governed references", async () => {
    mocks.get.mockResolvedValue({ data: receipt("absent") });
    const wrapper = mount(CollectionDefinitionPanel, {
      props: {
        experimentId: 12,
        refreshKey: "governed",
        allowDefinitionImport: false,
        governedSource: true,
      },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();

    expect(wrapper.find("input[type='file']").exists()).toBe(false);
    expect(button(wrapper, "Choose JSON")).toBeUndefined();
    expect(wrapper.text()).toContain("Catalog governed");
    expect(wrapper.text()).toContain("No separate collection-definition upload is needed");
  });

  it("keeps every collection-definition mutation hidden for an attached governed source", async () => {
    mocks.get.mockResolvedValue({ data: receipt("attached") });
    const wrapper = mount(CollectionDefinitionPanel, {
      props: {
        experimentId: 12,
        refreshKey: "governed-attached",
        allowDefinitionImport: false,
        governedSource: true,
      },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();

    expect(wrapper.find("input[type='file']").exists()).toBe(false);
    expect(button(wrapper, "Replace JSON")).toBeUndefined();
    expect(button(wrapper, "Remove")).toBeUndefined();
    expect(wrapper.text()).toContain("Attached and current");
  });

  it("prioritizes scientific metadata and keeps explained identities on hover", async () => {
    mocks.get.mockResolvedValue({ data: receipt("attached") });
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "1:raw:100", fileTypes: ["spa"] },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();

    expect(mocks.get).toHaveBeenCalledWith("/experiments/12/collection-definition");
    expect(wrapper.text()).toContain("Source collection metadata");
    expect(wrapper.text()).toContain("Attached and current");
    expect(wrapper.text()).toContain("33 SPA files");
    expect(wrapper.text()).toContain("33 rows × 14 columns");
    expect(wrapper.text()).toContain("33 × 1868");
    expect(wrapper.text()).toContain("14 fields");
    expect(wrapper.text()).not.toContain("a".repeat(64));
    expect(wrapper.text()).not.toContain("b".repeat(64));
    expect(wrapper.text()).not.toContain("c".repeat(64));
    expect(wrapper.get(".receipt-info").attributes("title")).toContain(
      "sample_id, specimen_id, block",
    );
    expect(wrapper.find(".metadata-fields-detail").exists()).toBe(false);
    await wrapper.get(".receipt-info").trigger("click");
    expect(wrapper.get(".metadata-fields-detail").text()).toContain(
      "sample_id, specimen_id, block",
    );
    const identityHelp = wrapper
      .findAll(".verification-chip")
      .map((item) => item.attributes("title"));
    expect(identityHelp).toEqual([
      expect.stringContaining(
        `Definition identity — binds sample rows and annotations. SHA-256: ${"a".repeat(64)}`,
      ),
      expect.stringContaining(
        `Source-file identity — detects any source membership or byte change. SHA-256: ${"b".repeat(64)}`,
      ),
      expect.stringContaining(
        `Scientific identity — binds the parsed matrix to its sources and definition. SHA-256: ${"c".repeat(64)}`,
      ),
    ]);
    await wrapper.findAll(".verification-chip")[0].trigger("click");
    expect(wrapper.get(".verification-detail").text()).toContain(`SHA-256: ${"a".repeat(64)}`);
    expect(wrapper.text()).toContain("Targets");
    expect(wrapper.text()).toContain("Absent");
  });

  it("previews without mutation, then attaches the exact selected file", async () => {
    mocks.get.mockResolvedValue({ data: receipt("absent") });
    mocks.post.mockResolvedValue({ data: receipt("preview") });
    mocks.put.mockResolvedValue({ data: receipt("attached") });
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "files" },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();

    const input = wrapper.get("input[type='file']");
    const selected = new File(["{}"], "verified.json", { type: "application/json" });
    Object.defineProperty(input.element, "files", { value: [selected], configurable: true });
    await input.trigger("change");
    await flushPromises();

    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.put).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("Verified preview");
    expect(wrapper.text()).toContain("Previewing does not change the dataset");

    await button(wrapper, "Attach verified definition")?.trigger("click");
    await flushPromises();
    expect(mocks.put).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("Attached and current");
    expect(wrapper.emitted("changed")?.[0]?.[0]).toEqual(receipt("attached"));
  });

  it("shows a stale receipt when sources change during attachment", async () => {
    mocks.get.mockResolvedValue({ data: receipt("absent") });
    mocks.post.mockResolvedValue({ data: receipt("preview") });
    mocks.put.mockResolvedValue({ data: receipt("stale") });
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "files" },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();

    const input = wrapper.get("input[type='file']");
    Object.defineProperty(input.element, "files", {
      value: [new File(["{}"], "verified.json", { type: "application/json" })],
      configurable: true,
    });
    await input.trigger("change");
    await flushPromises();
    await button(wrapper, "Attach verified definition")?.trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("Stale — modeling blocked");
    expect(wrapper.find("[role='alert']").exists()).toBe(true);
    expect(wrapper.emitted("changed")?.[0]?.[0]).toEqual(receipt("stale"));
  });

  it("visibly blocks stale definitions after the source inventory changes", async () => {
    mocks.get
      .mockResolvedValueOnce({ data: receipt("attached") })
      .mockResolvedValueOnce({ data: receipt("stale") });
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "before" },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();
    expect(wrapper.text()).toContain("Attached and current");

    await wrapper.setProps({ refreshKey: "after-delete" });
    await flushPromises();
    expect(wrapper.text()).toContain("Stale — modeling blocked");
    expect(wrapper.text()).toContain("no longer matches the current files");
    expect(wrapper.find("[role='alert']").exists()).toBe(true);
  });

  it("removes only the definition and reports the resulting absent state", async () => {
    mocks.get.mockResolvedValue({ data: receipt("attached") });
    mocks.delete.mockResolvedValue({ data: receipt("absent") });
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "files" },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();
    await button(wrapper, "Remove")?.trigger("click");
    await flushPromises();

    expect(mocks.delete).toHaveBeenCalledWith("/experiments/12/collection-definition");
    expect(wrapper.text()).toContain("Not attached");
    expect(wrapper.emitted("changed")?.[0]?.[0]).toEqual(receipt("absent"));
  });

  it("shows server refusal instead of preserving a misleading preview", async () => {
    mocks.get.mockResolvedValue({ data: receipt("absent") });
    mocks.post.mockRejectedValue(new Error("source digest does not match"));
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "files" },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();

    const input = wrapper.get("input[type='file']");
    Object.defineProperty(input.element, "files", {
      value: [new File(["{}"], "wrong.json", { type: "application/json" })],
      configurable: true,
    });
    await input.trigger("change");
    await flushPromises();
    expect(wrapper.text()).toContain("source digest does not match");
    expect(wrapper.find("[role='alert']").exists()).toBe(true);
    expect(button(wrapper, "Attach verified definition")).toBeUndefined();
  });

  it("discards a preview response after switching datasets", async () => {
    const slowPreview = deferred<{ data: CollectionDefinitionReceipt }>();
    mocks.get
      .mockResolvedValueOnce({ data: receipt("absent", 12) })
      .mockResolvedValue({ data: receipt("absent", 13) });
    mocks.post.mockReturnValue(slowPreview.promise);
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "dataset-a" },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();

    const input = wrapper.get("input[type='file']");
    Object.defineProperty(input.element, "files", {
      value: [new File(["{}"], "dataset-a.json", { type: "application/json" })],
      configurable: true,
    });
    await input.trigger("change");
    await wrapper.setProps({ experimentId: 13, refreshKey: "dataset-b" });
    await flushPromises();
    slowPreview.resolve({ data: receipt("preview") });
    await flushPromises();

    expect(wrapper.text()).toContain("Not attached");
    expect(button(wrapper, "Attach verified definition")).toBeUndefined();
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("does not let an older GET overwrite a newer verified preview", async () => {
    const slowGet = deferred<{ data: CollectionDefinitionReceipt }>();
    mocks.get.mockReturnValue(slowGet.promise);
    mocks.post.mockResolvedValue({ data: receipt("preview") });
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "dataset-a" },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();

    const input = wrapper.get("input[type='file']");
    Object.defineProperty(input.element, "files", {
      value: [new File(["{}"], "dataset-a.json", { type: "application/json" })],
      configurable: true,
    });
    await input.trigger("change");
    await flushPromises();
    slowGet.resolve({ data: receipt("absent") });
    await flushPromises();

    expect(wrapper.text()).toContain("Verified preview");
    expect(button(wrapper, "Attach verified definition")).toBeDefined();
  });

  it("does not apply or emit a slow attach response after switching datasets", async () => {
    const slowAttach = deferred<{ data: CollectionDefinitionReceipt }>();
    mocks.get
      .mockResolvedValueOnce({ data: receipt("absent", 12) })
      .mockResolvedValue({ data: receipt("absent", 13) });
    mocks.post.mockResolvedValue({ data: receipt("preview") });
    mocks.put.mockReturnValue(slowAttach.promise);
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "dataset-a" },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();

    const input = wrapper.get("input[type='file']");
    Object.defineProperty(input.element, "files", {
      value: [new File(["{}"], "dataset-a.json", { type: "application/json" })],
      configurable: true,
    });
    await input.trigger("change");
    await flushPromises();
    await button(wrapper, "Attach verified definition")?.trigger("click");
    await wrapper.setProps({ experimentId: 13, refreshKey: "dataset-b" });
    await flushPromises();
    slowAttach.resolve({ data: receipt("attached") });
    await flushPromises();

    expect(wrapper.text()).toContain("Not attached");
    expect(wrapper.emitted("changed")).toBeUndefined();
  });

  it("does not apply or emit a slow remove response after switching datasets", async () => {
    const slowRemove = deferred<{ data: CollectionDefinitionReceipt }>();
    mocks.get
      .mockResolvedValueOnce({ data: receipt("attached", 12) })
      .mockResolvedValue({ data: receipt("attached", 13) });
    mocks.delete.mockReturnValue(slowRemove.promise);
    const wrapper = mount(CollectionDefinitionPanel, {
      props: { experimentId: 12, refreshKey: "dataset-a" },
    });
    (wrapper.get("details").element as HTMLDetailsElement).open = true;
    await wrapper.get("details").trigger("toggle");
    await flushPromises();

    await button(wrapper, "Remove")?.trigger("click");
    await wrapper.setProps({ experimentId: 13, refreshKey: "dataset-b" });
    await flushPromises();
    slowRemove.resolve({ data: receipt("absent") });
    await flushPromises();

    expect(wrapper.text()).toContain("Attached and current");
    expect(wrapper.emitted("changed")).toBeUndefined();
  });
});
