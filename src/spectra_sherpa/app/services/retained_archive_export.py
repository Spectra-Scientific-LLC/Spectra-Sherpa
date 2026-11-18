"""Select immutable, caller-owned run records before archive byte collection."""

from fastapi import HTTPException
from sqlalchemy import JSON, LargeBinary, String, Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.schemas.execution_runs import ExecutionRunOut
from spectra_sherpa.app.services.retained_archive_results import MAX_ARCHIVE_RUNS, MAX_INDEX_BYTES


async def selected_archive_runs(
    session: AsyncSession, user_id: int, project_id: int, run_ids: list[int] | None
) -> tuple[ExecutionRunOut, ...]:
    if not run_ids:
        return ()
    if (
        len(run_ids) > MAX_ARCHIVE_RUNS
        or len(set(run_ids)) != len(run_ids)
        or any(type(value) is not int or value <= 0 for value in run_ids)
    ):
        raise HTTPException(422, "Select distinct retained run identities within the archive limit")
    predicates = (ExecutionRun.id.in_(run_ids), ExecutionRun.user_id == user_id, ExecutionRun.project_id == project_id)
    # Bound actual serialized bytes before the driver decodes any row. SQLite
    # text length stops at NUL, so count BLOB bytes instead. The same aggregate
    # guard is part of materialization to refuse concurrent growth.
    sqlite = session.get_bind().dialect.name == "sqlite"

    def byte_length(column):
        text_value = cast(column, Text)
        return func.length(cast(text_value, LargeBinary)) if sqlite else func.octet_length(text_value)

    retained_bytes = sum(
        func.coalesce(byte_length(column), 0)
        for column in ExecutionRun.__table__.columns
        if isinstance(column.type, (String, JSON))
    )
    count, size = (
        await session.execute(select(func.count(), func.coalesce(func.sum(retained_bytes), 0)).where(*predicates))
    ).one()
    if count != len(run_ids):
        raise HTTPException(404, "Selected retained runs are unavailable in this project")
    if size > MAX_INDEX_BYTES:
        raise HTTPException(409, "Selected retained run records exceed the archive metadata limit")
    total_size = select(func.coalesce(func.sum(retained_bytes), 0)).where(*predicates).correlate(None).scalar_subquery()
    rows = list(
        (
            await session.scalars(
                select(ExecutionRun)
                .where(*predicates, total_size <= MAX_INDEX_BYTES)
                .order_by(ExecutionRun.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(rows) != len(run_ids):
        raise HTTPException(404, "Selected retained runs are unavailable in this project")
    if any(row.status in {"pending", "running"} for row in rows):
        raise HTTPException(409, "Wait for the selected runs to finish before exporting their evidence")
    return tuple(ExecutionRunOut.model_validate(row) for row in rows)
