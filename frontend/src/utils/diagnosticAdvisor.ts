import type { PcaReview } from "./sampleReview";
export interface DiagnosticReference {
  workflow_id: number;
  run_id: number;
  node_id: string;
  graph_digest: string;
  source_digest: string;
  review_revision: number;
  selected_ids: string[];
  select_all: boolean;
  response_index: number;
  variable_ids: string[];
  baseline_run_id: number | null;
}
export interface SavedPlsdaDiagnosticReference {
  kind: "saved_plsda";
  artifact_uid: string;
  workflow_id: number;
  run_id: number;
  node_id: string;
  receipt_sha256: string;
  selected_ids: string[];
  select_all: boolean;
  variable_ids: string[];
}
export interface SavedApplicationDiagnosticReference {
  kind: "saved_application";
  artifact_uid: string;
  workflow_id: number;
  run_id: number;
  output_sha256: string;
  sample_index: number;
}
export interface SavedRunApplicationDiagnosticReference {
  kind: "saved_run_application";
  workflow_id: number;
  run_id: number;
  node_id: string;
  output_sha256: string;
  sample_index: number;
}
export interface SavedModelQualificationReference {
  kind: "saved_model_qualification";
  artifact_uid: string;
  workflow_id: number;
  run_id: number;
  dossier_digest: string;
  validation_view_digest: string;
  decision_digest: string | null;
  response_index: number;
}
export interface DiagnosticScope {
  project_id: number;
  model_kind?: "pca" | "pls" | "plsda" | "application" | "run_application" | "qualification";
  response_label?: string | null;
  reference: DiagnosticReference | SavedPlsdaDiagnosticReference | SavedApplicationDiagnosticReference | SavedRunApplicationDiagnosticReference | SavedModelQualificationReference;
  digest?: string;
  facts?: Record<
    string,
    { value: string | number | boolean | null; meaning?: string; units?: string | null }
  >;
  sample_aliases?: Record<string, string>;
  samples?: Array<{ alias: string; role: string }>;
}
export function diagnosticReference(
  review: PcaReview,
  workflowId: number,
  nodeId: string,
  selected: string[],
  responseIndex: number,
  variableIds: string[],
  baselineRunId: number | null,
): DiagnosticReference {
  const allowed = new Set(review.rows.map((row) => row.id));
  if (
    !selected.length ||
    selected.some((id) => !allowed.has(id)) ||
    new Set(selected).size !== selected.length
  )
    throw new Error("Select observations from this saved run first.");
  const all = selected.length === allowed.size;
  if (
    !all &&
    (selected.length > 1024 ||
      selected.reduce((n, id) => n + new TextEncoder().encode(id).length, 0) > 4096)
  )
    throw new Error("Narrow the selection or select the whole retained cohort for a summary.");
  return {
    workflow_id: workflowId,
    run_id: review.run_id,
    node_id: nodeId,
    graph_digest: review.graph_digest,
    source_digest: review.source_digest,
    review_revision: review.revision,
    selected_ids: all ? [] : [...selected],
    select_all: all,
    response_index: responseIndex,
    variable_ids: [...variableIds],
    baseline_run_id: baselineRunId,
  };
}

/** Snapshot reactive values without retaining references to live chart selection. */
export function copyDiagnosticScope(
  scope: DiagnosticScope | null | undefined,
): DiagnosticScope | null {
  return scope ? (JSON.parse(JSON.stringify(scope)) as DiagnosticScope) : null;
}

/** Only the most recent turn controls follow-up scope; an ordinary turn ends it. */
export function restoredDiagnosticScope(
  messages: Array<{ role: string; diagnostic_scope?: DiagnosticScope }>,
  projectId: number | null,
): DiagnosticScope | null {
  const latest = [...messages]
    .reverse()
    .find((message) => message.role === "user" || message.role === "assistant");
  const scope = latest?.diagnostic_scope;
  return scope?.project_id === projectId ? copyDiagnosticScope(scope) : null;
}

export function diagnosticCitation(
  href: string,
  scopes: Array<DiagnosticScope | undefined>,
): { title: string; detail: string } | null {
  const match = /^#diagnostic-([a-f0-9]{64})-(.+)$/.exec(href);
  if (!match) return null;
  let key: string;
  try {
    key = decodeURIComponent(match[2]);
  } catch {
    return null;
  }
  const scope = scopes.find(
    (item) =>
      item?.digest === match[1] && Object.prototype.hasOwnProperty.call(item.facts ?? {}, key),
  );
  if (!scope?.facts || !Object.prototype.hasOwnProperty.call(scope.facts, key))
    return {
      title: "Evidence unavailable",
      detail: "Reopen this saved run to revalidate its diagnostic evidence.",
    };
  const fact = scope.facts[key];
  const alias = key.split(".")[0];
  const sample = scope.sample_aliases?.[alias];
  const reference = scope.reference;
  const evidenceIdentity =
    "kind" in reference
      ? reference.kind === "saved_model_qualification"
        ? `Artifact ${reference.artifact_uid} · Dossier ${reference.dossier_digest.slice(0, 12)}`
        : reference.kind === "saved_run_application"
        ? `Run ${reference.run_id} · Node ${reference.node_id}`
        : `Artifact ${reference.artifact_uid} · Run ${reference.run_id}`
      : `Run ${reference.run_id} · Review ${reference.review_revision}`;
  return {
    title: fact.meaning || key,
    detail: `${sample ? `${alias}: ${sample} · ` : ""}${fact.value ?? "Unavailable"} ${fact.units || ""} · ${evidenceIdentity} · ${key}`,
  };
}
