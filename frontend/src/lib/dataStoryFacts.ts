import { datasetAxisDisplayState, projectDatasetAxisDisplay } from "@/utils/datasetAxisSets";

type StoryFacts = Record<string, unknown>;
const MAX_FACTS_CHARS = 12_000;
const OMIT_FIELD = /^(data|target|recipe|synthetic\.metadata|ground_truth(?:[._].*)?|raw.*|.*(?:_path|Path)|path|.*(?:api_?key|secret|token|password|credential|authorization)|.*_matrix|.*_spectra)$/i;
const USER_CHOICE_FIELD = /^(?:selection|selected(?:_|$)|active(?:_|$)|current(?:_|$)|preview(?:_|$)|include(?:_|$)|included(?:_|$)|exclude(?:_|$)|excluded(?:_|$)|inclusion(?:_|$)|exclusion(?:_|$)|sample_(?:mask|inclusion|exclusion)(?:_|$)|dataset_view(?:_|$)|data_portfolio(?:_|$)|curation(?:_|$)|user_filter(?:_|$))/i;
const isSourceFact = (key: string): boolean => !OMIT_FIELD.test(key) && !USER_CHOICE_FIELD.test(key);

const shortText = (value: unknown, limit = 240): string | null =>
  typeof value === "string" && value.trim() ? value.trim().slice(0, limit) : null;

const shortNames = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.map((item) => shortText(item, 80)).filter((item): item is string => item !== null).slice(0, 16)
    : [];

const object = (value: unknown): StoryFacts =>
  value && typeof value === "object" && !Array.isArray(value) ? value as StoryFacts : {};

/** Keep parsed scientific context without forwarding a raw matrix, local paths, or secrets. */
function bounded(value: unknown, depth = 0): unknown {
  if (depth > 4 || value == null) return null;
  if (typeof value === "string") return shortText(value, 320);
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "boolean") return value;
  if (Array.isArray(value)) {
    const examples = value.slice(0, 24).map((item) => bounded(item, depth + 1));
    return value.length > 24 ? { count: value.length, examples } : examples;
  }
  if (typeof value === "object") {
    return Object.fromEntries(Object.entries(value as StoryFacts)
      .filter(([key]) => isSourceFact(key))
      .slice(0, 60)
      .map(([key, item]) => [key, bounded(item, depth + 1)]));
  }
  return null;
}

function signalSummary(data: unknown): StoryFacts | null {
  if (!Array.isArray(data)) return null;
  let min = Infinity;
  let max = -Infinity;
  let finite = 0;
  let missing = 0;
  for (const row of data) {
    if (!Array.isArray(row)) continue;
    for (const value of row) {
      if (typeof value === "number" && Number.isFinite(value)) {
        min = Math.min(min, value);
        max = Math.max(max, value);
        finite++;
      } else {
        missing++;
      }
    }
  }
  return {
    total_rows: data.length,
    finite_values: finite,
    missing_values: missing,
    signal_min: finite ? min : null,
    signal_max: finite ? max : null,
  };
}

function oneTargetSummary(values: unknown[], totalRows: number): StoryFacts {
  const numeric = values.filter((item): item is number => typeof item === "number" && Number.isFinite(item));
  if (numeric.length && numeric.length === values.filter((item) => item != null).length) {
    let min = Infinity;
    let max = -Infinity;
    let sum = 0;
    for (const value of numeric) {
      min = Math.min(min, value);
      max = Math.max(max, value);
      sum += value;
    }
    return { total_rows: totalRows, examined_rows: values.length,
      observed: numeric.length, min, max, mean: sum / numeric.length };
  }
  const counts = new Map<string, number>();
  for (const value of values) {
    if (typeof value !== "string" && typeof value !== "number") continue;
    const label = String(value).slice(0, 80);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return { total_rows: totalRows, examined_rows: values.length,
    class_counts: Object.fromEntries([...counts.entries()].slice(0, 20)) };
}

function targetSummary(target: unknown, names: unknown): StoryFacts | null {
  if (!Array.isArray(target)) return null;
  const rows = target;
  const columns = Array.isArray(rows[0]) ? Math.min(rows[0].length, 8) : 1;
  const labels = shortNames(names);
  return {
    total_rows: target.length,
    columns: Array.from({ length: columns }, (_, index) => ({
      name: labels[index] ?? `Target ${index + 1}`,
      ...oneTargetSummary(rows.map((row) => Array.isArray(row) ? row[index] : row), target.length),
    })),
  };
}

function sampleTableSummary(axis: StoryFacts): StoryFacts | null {
  const table = object(axis.sample_table);
  const fields = Object.entries(table).filter(([key, values]) => isSourceFact(key) && Array.isArray(values));
  if (!fields.length) return null;
  return {
    field_count: fields.length,
    fields: fields.slice(0, 36).map(([name, values]) => {
      const column = values as unknown[];
      const present = column.filter((value) => value != null && value !== "");
      const numeric = present.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
      if (numeric.length && numeric.length === present.length) {
        let min = Infinity;
        let max = -Infinity;
        let sum = 0;
        for (const value of numeric) {
          min = Math.min(min, value);
          max = Math.max(max, value);
          sum += value;
        }
        return { name: name.slice(0, 80), rows: column.length, present: present.length,
          kind: "numeric", min, max, mean: sum / numeric.length };
      }
      const counts = new Map<string, number>();
      for (const value of present) {
        if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean") continue;
        const label = String(value).slice(0, 80);
        counts.set(label, (counts.get(label) ?? 0) + 1);
      }
      return { name: name.slice(0, 80), rows: column.length, present: present.length,
        kind: "categorical", distinct: counts.size,
        ...(counts.size <= 12 && counts.size < present.length
          ? { counts: Object.fromEntries(counts) } : {}) };
    }),
  };
}

/** Aggregate acquisition facts across source members without exposing their identifiers. */
function acquisitionSummary(metadata: StoryFacts): StoryFacts | null {
  const members = Array.isArray(metadata.source_member_metadata)
    ? metadata.source_member_metadata.map((member) => object(object(member).metadata))
    : [];
  // The aggregate's top-level metadata may repeat the first member: never
  // count that copied header as another acquisition.
  const sources = members.length ? members : [metadata];
  const records = sources.map((source) => object(source["omnic.acquisition"]));
  const fields = [...new Set(records.flatMap((record) => Object.keys(record)))]
    .filter(isSourceFact);
  if (!fields.length) return null;
  return {
    source_records: records.length,
    records_with_acquisition: records.filter((record) => Object.keys(record).length).length,
    fields: Object.fromEntries(fields.slice(0, 24).map((name) => {
      const values = records.flatMap((record) =>
        Array.isArray(record[name]) ? record[name] as unknown[] : [record[name]],
      ).filter((value) => value != null);
      const counts = new Map<string, { value: unknown; count: number }>();
      for (const value of values) {
        if (!["string", "number", "boolean"].includes(typeof value)) continue;
        const cleaned = bounded(value);
        if (cleaned == null) continue;
        const key = JSON.stringify(cleaned);
        const item = counts.get(key);
        if (item) item.count++;
        else counts.set(key, { value: cleaned, count: 1 });
      }
      // Summarize the full parsed timestamp column before bounding examples.
      // Do not interpret zone-less dates in the browser's local timezone.
      const timestamps = name === "acquired_at" ? values.flatMap(value => {
        if (typeof value !== "string" || !/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return [];
        const instant = Date.parse(value);
        return Number.isFinite(instant) ? [instant] : [];
      }) : [];
      const chronological = timestamps.sort((a, b) => a - b);
      const timestampRange = chronological.length && chronological.length === values.length ? {
        timestamp_range: {
          first: new Date(chronological[0]).toISOString(),
          last: new Date(chronological[chronological.length - 1]).toISOString(),
          elapsed_seconds: (chronological[chronological.length - 1] - chronological[0]) / 1000,
          observed_timestamps: chronological.length,
          scope: "All recorded timestamps in the supplied source records; not an instrument scan duration.",
        },
      } : {};
      return [name, { distinct_values: counts.size,
        values: [...counts.values()].slice(0, 12),
        omitted_distinct_values: Math.max(0, counts.size - 12), ...timestampRange }];
    })),
    omitted_fields: Math.max(0, fields.length - 24),
  };
}

/** Shared parsed facts for BYOK and hosted narration; transport adds no projection. */
export function buildDataStoryFacts(dataset: StoryFacts): StoryFacts {
  const axis = object(dataset.x_axis);
  const axisState = datasetAxisDisplayState(dataset.x_axis);
  const axisDisplay = projectDatasetAxisDisplay(axisState,
    !Array.isArray(axis.data) && typeof axis.primary_scale_name === "string"
      ? `scale:${axis.primary_scale_name}` : undefined);
  const axisData = axisDisplay?.values ?? [];
  let axisMin = Infinity;
  let axisMax = -Infinity;
  for (const value of axisData) {
    axisMin = Math.min(axisMin, value);
    axisMax = Math.max(axisMax, value);
  }
  const metadata = object(dataset.metadata);
  const extra = object(dataset.extra);
  const domain = object(dataset.domain);
  const sampleAxis = object(dataset.sample_axis);
  const yAxis = object(dataset.y_axis);
  const axisWithTable = Object.keys(object(sampleAxis.sample_table)).length ? sampleAxis : yAxis;
  const { sample_table: _sampleTable, ...sampleAxisWithoutRows } = sampleAxis;
  const { sample_table: _ySampleTable, ...yAxisWithoutRows } = yAxis;
  const facts: StoryFacts = {
    dataset: shortText(dataset.label ?? dataset.title),
    source: shortText(dataset.source),
    description: shortText(dataset.description, 800),
    task_type: shortText(dataset.task_type),
    data_type: shortText(dataset.type ?? metadata.data_type),
    technique: shortText(dataset.technique ?? domain.technique ?? metadata.spectral_technique),
    is_spectra: dataset.is_spectra ?? dataset.is_spectroscopic ?? metadata.is_spectra ?? null,
    is_time_series: dataset.is_time_series ?? metadata.is_time_series ?? null,
    shape: bounded(dataset.shape ?? [dataset.n_samples, dataset.n_features]),
    n_samples: dataset.n_samples ?? null,
    n_features: dataset.n_features ?? null,
    ndim: dataset.ndim ?? null,
    units: shortText(dataset.units),
    data_role: shortText(dataset.data_role),
    signal: signalSummary(dataset.data),
    x_axis: { ...object(bounded(axis)), count: axisState.kind === "valid" ? axisState.length : null,
      numeric_coordinate_count: axisData.length,
      min: axisData.length ? axisMin : null,
      max: axisData.length ? axisMax : null,
      ...(axisState.kind === "invalid" ? { unavailable_reason: axisState.message } : {}) },
    y_axis: bounded(yAxisWithoutRows),
    sample_axis: bounded(sampleAxisWithoutRows),
    sample_metadata_columns: sampleTableSummary(axisWithTable),
    inner_axes: bounded(dataset.inner_axes),
    domain: bounded(domain),
    acquisition: acquisitionSummary(metadata),
    synthesis: synthesisSummary(extra, metadata),
    target_context: bounded(dataset.target_context),
    target_distribution: targetSummary(dataset.target, object(dataset.target_context).target_names ?? dataset.target_names),
    targets: shortNames(dataset.target_names),
    property_stats: bounded(dataset.property_stats),
    feature_names: shortNames(dataset.feature_names),
    warnings: bounded(dataset.warnings ?? dataset.warning),
    metadata: bounded(metadata),
    metadata_summary: bounded(dataset.metadata_summary),
    descriptive: bounded(dataset.descriptive),
    file_metadata: bounded(dataset.file_metadata),
    layout: bounded(dataset.layout),
    source_identity: bounded(dataset.source_identity),
  };
  const omitted: string[] = [];
  // Account for the omission note itself while enforcing the transport budget.
  facts.omitted_for_input_limit = omitted;
  for (const key of ["source_identity", "layout", "file_metadata", "descriptive", "feature_names", "sample_axis",
    "metadata_summary", "metadata", "property_stats", "inner_axes", "y_axis", "sample_metadata_columns", "target_distribution",
    "target_context", "domain", "signal", "description"]) {
    if (JSON.stringify(facts).length <= MAX_FACTS_CHARS) break;
    delete facts[key];
    omitted.push(key);
  }
  if (JSON.stringify(facts).length > MAX_FACTS_CHARS) {
    throw new Error("The parsed dataset summary is too large for Data Story. Narrow the selected data.");
  }
  if (!omitted.length) delete facts.omitted_for_input_limit;
  return facts;
}

/** Narrate the saved recipe, never infer synthetic origin from a title or target. */
function synthesisSummary(extra: StoryFacts, metadata: StoryFacts): StoryFacts | null {
  // The NumPy ingestion authority retains these in extra; API compatibility
  // metadata may mirror them. Do not depend on that optional mirror.
  const embedded = object(extra["synthetic.metadata"] ?? metadata["synthetic.metadata"]);
  const origin = embedded.source ?? metadata.source;
  if (origin !== "synthesis" && origin !== "synthetic_reference") return null;
  const recipe = object(extra.recipe ?? metadata.recipe);
  const settings = object(recipe.settings);
  const components = Array.isArray(recipe.components) ? recipe.components : [];
  const scalarFields = (record: StoryFacts, numeric: string[], text: string[]): StoryFacts =>
    Object.fromEntries([
      ...numeric.filter(key => typeof record[key] === "number" && Number.isFinite(record[key]))
        .map(key => [key, record[key]]),
      ...text.filter(key => shortText(record[key], 80) !== null)
        .map(key => [key, shortText(record[key], 80)]),
    ]);
  return {
    origin: "synthetic",
    source: shortText(embedded.synthesis_source ?? metadata.synthesis_source),
    settings: scalarFields(settings, ["n_samples", "pathlength_cm", "temperature_k", "pressure_atm",
      "noise_sigma_au", "snap_tolerance_cm1", "seed", "resolution_cm1"], ["source", "range_mode", "apodization"]),
    component_count: components.length,
    components: components.slice(0, 16).map(value => {
      const component = object(value);
      return {
        name: shortText(component.name, 80), source: shortText(component.source, 80),
        spectrum_units: shortText(component.spectrum_units, 80),
        concentration_max_ppm: typeof component.concentration_max_ppm === "number" &&
          Number.isFinite(component.concentration_max_ppm) ? component.concentration_max_ppm : null,
      };
    }),
    omitted_components: Math.max(0, components.length - 16),
    wavenumber: scalarFields(object(recipe.wavenumber), ["min", "max", "n_points"], ["units"]),
  };
}

export function buildDataStoryContext(dataset: StoryFacts) {
  return { schema_version: "spectrasherpa-data-story/1" as const, facts: buildDataStoryFacts(dataset) };
}
