import type { LocationQuery, LocationQueryRaw } from "vue-router";

/** Keep a candidate deep link pointed at the sheet the scientist actually sees. */
export function activeWorkflowQuery(
  query: LocationQuery,
  projectId: number | null,
  workflowId: number | null,
): LocationQueryRaw | null {
  if (
    query.workflow_id === undefined ||
    projectId === null ||
    workflowId === null ||
    !Number.isSafeInteger(projectId) ||
    !Number.isSafeInteger(workflowId)
  ) {
    return null;
  }
  const project = String(projectId);
  const workflow = String(workflowId);
  if (query.project_id === project && query.workflow_id === workflow) return null;
  return { ...query, project_id: project, workflow_id: workflow };
}
