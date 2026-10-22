import { describe, expect, it } from "vitest";
import { buildDataStoryContext } from "@/lib/dataStoryFacts";
import { localStoryMessage } from "@/lib/localDataStory";

const source = {
  title: "Lavender", is_spectra: true, n_samples: 3, n_features: 3,
  domain: { technique: "IR", instrument: "Thermo Nicolet OMNIC" },
  x_axis: { title: "Wavenumber", units: "cm^-1", data: [4000, 2000, 400] },
  metadata: {
    "omnic.acquisition": { scan_count: 16 },
    source_member_metadata: [
      { metadata: { "omnic.acquisition": { scan_count: 16, background_scan_count: 16 } } },
      { metadata: { "omnic.acquisition": { scan_count: 32, background_scan_count: 16 } } },
      { metadata: {} },
    ],
  },
};

describe("provider-independent parsed Data Story facts", () => {
  it("summarizes all acquisition timestamps before truncating displayed examples", () => {
    const metadata = { source_member_metadata: Array.from({ length: 33 }, (_, i) => ({
      metadata: { "omnic.acquisition": { acquired_at: new Date(Date.UTC(2026, 7, 23, 23, 0, i * 150)).toISOString() } },
    })) };
    const acquisition = buildDataStoryContext({ metadata }).facts.acquisition as {
      fields: { acquired_at: { values: unknown[]; omitted_distinct_values: number; timestamp_range: Record<string, unknown> } };
    };
    expect(acquisition.fields.acquired_at.values).toHaveLength(12);
    expect(acquisition.fields.acquired_at.omitted_distinct_values).toBe(21);
    expect(acquisition.fields.acquired_at.timestamp_range).toMatchObject({
      first: "2026-08-23T23:00:00.000Z", last: "2026-08-24T00:20:00.000Z",
      elapsed_seconds: 4800, observed_timestamps: 33,
    });
    const message = localStoryMessage({ metadata }, "");
    expect(message).toContain("Never infer the full acquisition duration from truncated timestamp examples");
    expect(message).toContain("Signal magnitude alone does not establish signal quality");
  });

  it("does not invent a range for zone-less or malformed acquisition dates", () => {
    for (const acquired_at of [["2026-08-23T23:00:00"], ["unknown", "2026-08-23T23:00:00Z"]]) {
      const facts = buildDataStoryContext({ metadata: { "omnic.acquisition": { acquired_at } } }).facts;
      expect(JSON.stringify(facts.acquisition)).not.toContain("timestamp_range");
    }
  });
  it("sends identical scientific facts to local and hosted narration", () => {
    const context = buildDataStoryContext(source);
    const localFacts = JSON.parse(localStoryMessage(source, "How acquired?").split("Dataset facts: ")[1]);
    expect(localFacts).toEqual(context.facts);
    expect(context.schema_version).toBe("spectrasherpa-data-story/1");
    expect(context.facts.x_axis).toMatchObject({ min: 400, max: 4000, units: "cm^-1" });
    expect(context.facts.domain).toMatchObject({ instrument: "Thermo Nicolet OMNIC" });
  });

  it("reports member variation and missing acquisition records without double counting", () => {
    expect(buildDataStoryContext(source).facts.acquisition).toEqual({
      source_records: 3, records_with_acquisition: 2, omitted_fields: 0,
      fields: {
        scan_count: { distinct_values: 2, values: [{ value: 16, count: 1 }, { value: 32, count: 1 }], omitted_distinct_values: 0 },
        background_scan_count: { distinct_values: 1, values: [{ value: 16, count: 2 }], omitted_distinct_values: 0 },
      },
    });
  });

  it("retains acquisition facts when bulky raw metadata is omitted for the prompt limit", () => {
    const context = buildDataStoryContext({ ...source, metadata: {
      ...source.metadata,
      ...Object.fromEntries(Array.from({ length: 60 }, (_, i) => [`field${i}`, "x".repeat(400)])),
    } });
    expect(context.facts.acquisition).toEqual(buildDataStoryContext(source).facts.acquisition);
    expect(JSON.stringify(context.facts).length).toBeLessThanOrEqual(12000);
  });

  it("does not invent acquisition settings when they are absent", () => {
    expect(buildDataStoryContext({ title: "Iris" }).facts.acquisition).toBeNull();
  });

  it("includes the omission note in the shared 12000-character transport budget", () => {
    const metadata = Object.fromEntries(Array.from({ length: 35 }, (_, i) => [`field${i}`, "x".repeat(312)]));
    const { facts } = buildDataStoryContext({ title: "Spectrum", metadata });
    expect(JSON.stringify(facts).length).toBeLessThanOrEqual(12000);
    expect(facts.omitted_for_input_limit).toBeDefined();
  });
});
