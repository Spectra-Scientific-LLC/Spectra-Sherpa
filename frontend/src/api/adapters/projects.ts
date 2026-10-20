import type { components } from "@/types/api/v1";
import type { AdvisorChannel, ProjectDataSource, ProjectDetail, ProjectSummary } from "@/types";

type Schemas = components["schemas"];

export function projectSummary(value: Schemas["ProjectSummary"]): ProjectSummary {
  return {
    ...value,
    description: value.description ?? null,
    parent_id: value.parent_id ?? null,
    technique: value.technique ?? null,
    sample_type: value.sample_type ?? null,
    experiment_count: value.experiment_count ?? 0,
    workflow_count: value.workflow_count ?? 0,
    script_count: value.script_count ?? 0,
    model_count: value.model_count ?? 0,
    children_count: value.children_count ?? 0,
    version_count: value.version_count ?? 0,
  };
}

export function advisorChannel(value: Schemas["AdvisorChannelOut"]): AdvisorChannel {
  return {
    ...value, workflow_id: value.workflow_id ?? null, color: value.color ?? null,
    conversation_id: value.conversation_id ?? null,
  };
}

export function projectDataSource(value: Schemas["ProjectDataSourceOut"]): ProjectDataSource {
  return {
    ...value, source_ref: value.source_ref ?? null, fingerprint: value.fingerprint ?? null,
    metadata: value.metadata ?? {}, sort_order: value.sort_order ?? 0,
  };
}

export function projectDetail(value: Schemas["ProjectDetail"]): ProjectDetail {
  return {
    ...value, ...projectSummary(value),
    metadata: value.metadata ?? {},
    experiments: value.experiments ?? [],
    workflows: value.workflows ?? [],
    scripts: value.scripts ?? [],
    models: value.models ?? [],
    data_sources: (value.data_sources ?? []).map(projectDataSource),
    advisor_channels: (value.advisor_channels ?? []).map(advisorChannel),
    children: (value.children ?? []).map(projectSummary),
  };
}
