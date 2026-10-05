import { describe, expect, it } from "vitest";
import { summarizeNodePlots } from "@/utils/plotStateSummary";
import type { ExecutedPresentationRecord } from "@/stores/workflow-types";
import oof from "../fixtures/oof-scientific-surface.json";
const execution = (kind: string): ExecutedPresentationRecord =>
  ({
    schema_version: "spectrasherpa-executed-presentation/1",
    contract_digest: "a".repeat(64),
    presentations: [
      {
        presentation_id: "saved",
        label: "Saved result",
        kind,
        source_ports: ["result"],
        modes: ["plot"],
        description: "",
        content_categories: [],
      },
    ],
    contract: {
      schema_version: "spectrasherpa-node-presentation/1",
      default_presentation: "saved",
      presentations: [
        {
          presentation_id: "saved",
          label: "Saved result",
          kind,
          source_ports: ["result"],
          modes: ["plot"],
          description: "",
        },
      ],
    },
  }) as ExecutedPresentationRecord;
const spectral = {
  type: "SherpaDataset",
  data: Array.from({ length: 60 }, (_, i) => [i, i + 1]),
  x_axis: { title: "Wavenumber", units: "cm^-1", data: [4000, 3900] },
  sample_axis: {
    labels: Array.from({ length: 60 }, (_, i) => `private-sample-${i}`),
    include_mask: Array.from({ length: 60 }, (_, i) => i !== 0),
  },
  metadata: {
    is_spectra: true,
    x_title: "Wavenumber",
    x_units: "cm^-1",
    wavenumbers: [4000, 3900],
  },
};
describe("advisor consumes retained typed projections", () => {
  it("discloses spectral masks and first-50 scope without sending labels or rows", () => {
    const summaries = summarizeNodePlots({ result: spectral }, execution("spectral_dataset"));
    const overlay = summaries.find((s) => s.population);
    expect(overlay?.population).toEqual({ shown: 50, total: 59, available: 60, excluded: 1 });
    expect(overlay?.note).toContain('"excluded":1');
    expect(overlay?.x_axis?.title).toContain("Wavenumber");
    expect(JSON.stringify(summaries)).not.toContain("private-sample");
    expect(
      summaries.every((s) => s.traces === null && s.note.includes("not the current open plot")),
    ).toBe(true);
  });
  it("keeps supervised held-out evidence scope through JSON reopen", () => {
    const summary = summarizeNodePlots(
      JSON.parse(JSON.stringify({ result: oof })),
      execution("out_of_fold_evidence"),
    )[0];
    expect(summary.claim_scope).toBe("out_of_fold");
    expect(summary.refusal_reason).toBeNull();
    expect(summary.contract_digest).toBe("a".repeat(64));
    expect(summary.source_ports).toEqual(["result"]);
    expect(JSON.stringify(summary)).not.toContain("fold_assignments");
  });
  it("projects non-spectral categories without treating -1 as universal noise or exporting labels", () => {
    const summary = summarizeNodePlots(
      { result: ["private-class", -1, -1] },
      execution("categorical_labels"),
    )[0];
    expect(summary.kind).toBe("bar");
    expect(summary.refusal_reason).toBeNull();
    expect(summary.x_axis?.units ?? null).toBeNull();
    expect(JSON.stringify(summary)).not.toContain("private-class");
  });
  it("preserves explicit refusal when every spectral observation is excluded", () => {
    const value = {
      ...spectral,
      sample_axis: { ...spectral.sample_axis, include_mask: Array(60).fill(false) },
    };
    expect(
      summarizeNodePlots({ result: value }, execution("spectral_dataset"))[0].refusal_reason,
    ).toMatch(/projection refused/);
  });
  it("refuses missing classification responses rather than inventing a plot", () => {
    const summary = summarizeNodePlots(
      { result: [[null]] },
      execution("classification_responses"),
    )[0];
    expect(summary.refusal_reason).toMatch(/projection refused/);
    expect(summary.kind).toBe("unavailable");
  });
  it("does not infer legacy PCA plots from names, shapes or metadata", () => {
    const summary = summarizeNodePlots({ data: [[1, 2]], metadata: { isPCA: true } })[0];
    expect(summary.refusal_reason).toMatch(/no presentation contract/);
    expect(summary.x_axis).toBeNull();
  });
  it("refuses unavailable retained ports", () => {
    expect(summarizeNodePlots({}, execution("pca_scores"))[0].refusal_reason).toMatch(
      /no available/,
    );
  });
  it.each(["empty", "port", "kind", "mode", "digest"])(
    "refuses invalid materialization %s",
    (mutation) => {
      const saved = execution("spectral_dataset");
      if (mutation === "empty") saved.presentations = [];
      if (mutation === "port") saved.presentations[0].source_ports = ["other"];
      if (mutation === "kind") saved.presentations[0].kind = "pca_scores";
      if (mutation === "mode") saved.presentations[0].modes = ["table"];
      if (mutation === "digest") saved.contract_digest = "invalid";
      expect(summarizeNodePlots({ result: spectral }, saved)[0].refusal_reason).toBeTruthy();
    },
  );

  it("redacts producer refusal text before any advisor egress", () => {
    const summary = summarizeNodePlots(
      {
        result: {
          data: [],
          layout: { meta: { refusal_reason: "/private/sample-X " + "secret".repeat(1000) } },
        },
      },
      execution("visualization"),
    );
    expect(JSON.stringify(summary)).not.toContain("/private/");
    expect(JSON.stringify(summary)).not.toContain("secret");
    expect(summary[0].refusal_reason).toBeTruthy();
  });

  it("does not let declared Plotly metadata authorize held-out or population claims", () => {
    const summary = summarizeNodePlots(
      {
        result: {
          data: [{ type: "bar", x: [1], y: [1] }],
          layout: {
            meta: {
              claim_scope: "held_out_test",
              display_population: { shown: 100, total: 10, available: 5, excluded: 0 },
            },
          },
        },
      },
      execution("visualization"),
    )[0];
    expect(summary.population).toBeNull();
    expect(summary.claim_scope).toBeNull();
  });
});
