"""Admission for existing retained-run facts, without private interpretation."""

from sqlalchemy import func, select

from spectra_sherpa.app.models.data_egress import DataType
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.inspection_readers import authorize_policy
from spectra_sherpa.app.services.tools.builtin.runs import RunArguments, RunListArguments, get_run, list_runs


async def authorize_run_reader(session, identity, arguments, result=None):
    from spectra_sherpa.app.services.inspection_bridge import InspectionRefused

    if not identity.retained_results:
        raise InspectionRefused("retained_result_consent_required")
    user = await authorize_policy(session, identity, [DataType.METADATA, DataType.WORKFLOWS, DataType.MODELS])
    ids = [arguments.run_id] if isinstance(arguments, RunArguments) else []
    if isinstance(arguments, RunListArguments) and result is not None:
        ids = [run["id"] for run in result["runs"]]
    if ids:
        current_runs = dict(
            (
                await session.execute(
                    select(ExecutionRun.id, ExecutionRun.workflow_id).where(
                        ExecutionRun.id.in_(ids),
                        ExecutionRun.user_id == identity.actor_id,
                        ExecutionRun.project_id == identity.project_id,
                    )
                )
            ).all()
        )
        if len(current_runs) != len(set(ids)):
            raise InspectionRefused("object_unavailable")
        if result is not None:
            rows = result["runs"] if isinstance(arguments, RunListArguments) else [result]
            if any(current_runs[row["id"]] != row["workflow_id"] for row in rows):
                raise InspectionRefused("object_unavailable")
            workflow_ids = {row["workflow_id"] for row in rows if row["workflow_name"] is not None}
            if workflow_ids:
                current_names = await session.scalar(
                    select(func.count())
                    .select_from(Workflow)
                    .where(
                        Workflow.id.in_(workflow_ids),
                        Workflow.user_id == identity.actor_id,
                        Workflow.project_id == identity.project_id,
                    )
                )
                if current_names != len(workflow_ids):
                    raise InspectionRefused("object_unavailable")
    return user


async def read_run_facts(sessions, identity, arguments):
    async with sessions() as session:
        user = await authorize_run_reader(session, identity, arguments)
        context = dict(session=session, user=user, project_id=identity.project_id)
        if isinstance(arguments, RunArguments):
            return await get_run(arguments.run_id, **context)
        return await list_runs(arguments.offset, arguments.limit, **context)
