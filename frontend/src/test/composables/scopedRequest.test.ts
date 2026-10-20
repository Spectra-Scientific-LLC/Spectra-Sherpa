import { describe, expect, it, vi } from "vitest";
import { effectScope, ref } from "vue";
import { useScopedRequest } from "@/composables/useScopedRequest";

describe("scoped request ownership", () => {
  it("does not reset evidence when an unrelated route field changes", () => {
    const route = ref({ runId: "42", view: "Results" });
    const reset = vi.fn();
    const scope = useScopedRequest(() => [route.value.runId], reset);
    const pending = scope.begin();
    route.value = { runId: "42", view: "Summary" };
    expect(pending.isCurrent()).toBe(true);
    expect(reset).not.toHaveBeenCalled();
    scope.dispose();
  });
  it.each(["user", "project", "dataset", "sheet", "run"])(
    "invalidates a %s A → B → A transition synchronously",
    () => {
      const identity = ref(1);
      const invalidate = vi.fn();
      const scope = useScopedRequest(() => [identity.value], invalidate);
      const old = scope.begin();
      identity.value = 2;
      identity.value = 1;
      expect(old.signal.aborted).toBe(true);
      expect(old.isCurrent()).toBe(false);
      expect(invalidate).toHaveBeenCalledTimes(2);
      expect(scope.begin().isCurrent()).toBe(true);
      scope.dispose();
    },
  );

  it("replaces only its own request lane", () => {
    const identity = ref(1);
    const list = useScopedRequest(() => [identity.value]);
    const detail = useScopedRequest(() => [identity.value]);
    const first = list.begin();
    const other = detail.begin();
    const second = list.begin();
    expect(first.isCurrent()).toBe(false);
    expect(first.signal.aborted).toBe(true);
    expect(second.isCurrent()).toBe(true);
    expect(other.isCurrent()).toBe(true);
    list.dispose();
    detail.dispose();
  });

  it.each(["resolve", "reject"])(
    "ignores late %s and finally effects even when the transport ignores abort",
    async (outcome) => {
      const project = ref(1);
      const scope = useScopedRequest(() => [project.value]);
      let resolve!: (value: string) => void;
      let reject!: (error: Error) => void;
      const response = new Promise<string>((yes, no) => {
        resolve = yes;
        reject = no;
      });
      const state = { value: "", error: "", loading: true };
      const old = scope.begin();
      const pending = (async () => {
        try {
          const value = await response;
          if (old.isCurrent()) state.value = value;
        } catch (error) {
          if (old.isCurrent()) state.error = String(error);
        } finally {
          if (old.isCurrent()) state.loading = false;
        }
      })();
      project.value = 2;
      scope.begin();
      state.value = "new workspace";
      if (outcome === "resolve") resolve("old workspace");
      else reject(new Error("old refusal"));
      await pending;
      expect(state).toEqual({ value: "new workspace", error: "", loading: true });
      scope.dispose();
    },
  );

  it("rejects disposed completions and aborts on component/store disposal", () => {
    const owner = effectScope();
    const scope = owner.run(() => useScopedRequest(() => [1, 2]))!;
    const ticket = scope.begin();
    owner.stop();
    expect(ticket.isCurrent()).toBe(false);
    expect(ticket.signal.aborted).toBe(true);
    expect(() => scope.begin()).toThrow("disposed");
    scope.dispose();
  });

  it("checks captured identity even for nonreactive callers", () => {
    let project = 1;
    const scope = useScopedRequest(() => [project]);
    const ticket = scope.begin();
    project = 2;
    expect(ticket.isCurrent()).toBe(false);
    scope.dispose();
  });

  it("supports explicit invalidation without changing object identity", () => {
    const reset = vi.fn();
    const scope = useScopedRequest(() => ["user", 1, "run"], reset);
    const old = scope.begin();
    scope.invalidate();
    expect(reset).toHaveBeenCalledOnce();
    expect(old.isCurrent()).toBe(false);
    expect(scope.begin().isCurrent()).toBe(true);
    scope.dispose();
  });
});
