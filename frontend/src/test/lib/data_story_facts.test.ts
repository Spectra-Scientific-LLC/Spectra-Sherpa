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
  it("counts a label-only feature axis without inventing numeric coordinates", () => {
    const { facts } = buildDataStoryContext({ title: "Iris", n_samples: 150, n_features: 4,
      x_axis: { axis_class: "FeatureAxis", labels: ["sepal length (cm)", "sepal width (cm)",
        "petal length (cm)", "petal width (cm)"] } });
    expect(facts.x_axis).toMatchObject({ count: 4, numeric_coordinate_count: 0, min: null, max: null });
    expect(facts.synthesis).toBeNull();
  });

  it("uses declared alternate axis coordinates and refuses malformed axes", () => {
    expect(buildDataStoryContext({ x_axis: { primary_scale_name: "shift",
      alternate_scales: [{ name: "shift", values: [1800, 1200, 600], units: "cm^-1", source_set_index: 0 }] },
    }).facts.x_axis).toMatchObject({ count: 3, numeric_coordinate_count: 3, min: 600, max: 1800 });
    expect(buildDataStoryContext({ x_axis: { data: [1, 2], labels: ["only one"] } }).facts.x_axis)
      .toMatchObject({ count: null, min: null, max: null, validation_warning: expect.any(String) });
    expect(buildDataStoryContext({}).facts.x_axis).toMatchObject({ count: null, min: null, max: null });
  });

  it.each(["synthetic_reference", "eigenvector", "oes"])(
    "keeps catalog-only spectral bounds for %s",
    (catalog) => {
      const dataset = {
        source: catalog,
        n_features: 200,
        wavelength_min: 400,
        wavelength_max: 4000,
        metadata: { x_units: "cm^-1" },
      };
      const { facts } = buildDataStoryContext(dataset);
      expect(facts.x_axis).toMatchObject({
        count: null,
        numeric_coordinate_count: 0,
        min: 400,
        max: 4000,
        units: "cm^-1",
        range_source: "catalog_summary",
      });
      const localFacts = JSON.parse(
        localStoryMessage(dataset, "Range?").split("Dataset facts: ")[1],
      );
      expect(localFacts).toEqual(facts);
    },
  );

  it("summarizes finite coordinates without relaxing display alignment or altering labels", () => {
    const dataset = {
      x_axis: { data: [4000, null, NaN, 400], labels: [" first ", "b", "c", "last "] },
    };
    expect(buildDataStoryContext(dataset).facts.x_axis).toMatchObject({
      count: 4,
      numeric_coordinate_count: 2,
      omitted_coordinate_count: 2,
      min: 400,
      max: 4000,
      validation_warning: expect.any(String),
    });
    expect(dataset.x_axis.labels[0]).toBe(" first ");
    expect(
      buildDataStoryContext({ x_axis: { labels: [" first ", "second"] } }).facts.x_axis,
    ).toMatchObject({ count: 2, numeric_coordinate_count: 0, min: null, max: null });
  });

  it("keeps canonical synthetic origin and recipe when generic metadata is omitted", () => {
    const extra = { "synthetic.metadata": { source: "synthesis", synthesis_source: "nist_quant_ir" },
      recipe: { settings: { source: "nist_quant_ir", n_samples: 50, pathlength_cm: 10,
        noise_sigma_au: 0.001, resolution_cm1: 1, apodization: "Blackman-Harris", api_key: "never-forward" },
      components: [{ name: "Acetone", source: "nist_quant_ir", concentration_max_ppm: 100,
        spectrum_units: "molar absorption coefficient", control_points: [{ x: 0, y: 0.15 }],
        source_provenance: { credential: "never-forward" } }],
      wavenumber: { min: 575.169, max: 3975.077, n_points: 7053, units: "cm^-1" },
      raw_spectra: [[1234567]], path: "/private/not-for-llm" },
      "ground_truth.spectra": [[9876543]] };
    const parsed = { title: "An arbitrary editable title", extra,
      metadata: Object.fromEntries(Array.from({ length: 60 }, (_, i) => [`field${i}`, "x".repeat(400)])) };
    const context = buildDataStoryContext(parsed);
    expect(context.facts.metadata).toBeUndefined();
    expect(context.facts.synthesis).toMatchObject({ origin: "synthetic", source: "nist_quant_ir",
      component_count: 1, components: [{ name: "Acetone", concentration_max_ppm: 100 }],
      settings: { n_samples: 50, pathlength_cm: 10, noise_sigma_au: 0.001, resolution_cm1: 1 },
      wavenumber: { n_points: 7053, units: "cm^-1" } });
    const encoded = JSON.stringify(context);
    for (const secret of ["never-forward", "1234567", "9876543", "/private/not-for-llm", "control_points"]) {
      expect(encoded).not.toContain(secret);
    }
    const localFacts = JSON.parse(localStoryMessage(parsed, "How acquired?").split("Dataset facts: ")[1]);
    expect(localFacts).toEqual(context.facts);
    expect(encoded.length).toBeLessThan(12000);
  });

  it("rejects non-scalar recipe values, including mirrored raw recipe and ground truth", () => {
    const metadata = { "synthetic.metadata": { source: "synthesis", synthesis_source: "nist_quant_ir" },
      recipe: { settings: { n_samples: 50, pathlength_cm: [[987654321]], source: { data: "not text" },
        noise_sigma_au: NaN, seed: true, temperature_k: 296 },
      wavenumber: { min: [[11223344]], max: Infinity, n_points: 7053, units: ["not text"] } },
      ground_truth: { concentrations: [[55667788]] } };
    const { facts } = buildDataStoryContext({ metadata });
    expect(facts.synthesis).toMatchObject({ settings: { n_samples: 50, temperature_k: 296 },
      wavenumber: { n_points: 7053 } });
    expect((facts.synthesis as Record<string, unknown>).settings).toEqual({ n_samples: 50, temperature_k: 296 });
    expect((facts.synthesis as Record<string, unknown>).wavenumber).toEqual({ n_points: 7053 });
    for (const forbidden of ["987654321", "11223344", "55667788", "not text", '"recipe"', '"ground_truth"']) {
      expect(JSON.stringify(facts)).not.toContain(forbidden);
    }
  });

  it("supports the compatibility mirror, but never guesses synthetic origin from a title or recipe alone", () => {
    const mirrored = { metadata: { "synthetic.metadata": { source: "synthetic_reference", synthesis_source: "hitran" },
      recipe: { components: Array.from({ length: 20 }, (_, i) => ({ name: `Component ${i}` })) } } };
    expect(buildDataStoryContext(mirrored).facts.synthesis)
      .toMatchObject({ origin: "synthetic", source: "hitran", component_count: 20, omitted_components: 4 });
    for (const parsed of [{ title: "Synthetic NIST acetone" }, { extra: { recipe: { settings: { source: "nist_quant_ir" } } } }]) {
      expect(buildDataStoryContext(parsed).facts.synthesis).toBeNull();
    }
  });

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
