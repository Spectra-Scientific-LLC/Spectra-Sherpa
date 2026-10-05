"""Move the unexposed DOE schema behind a lossless retired namespace."""

from __future__ import annotations

import logging
import re

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)

LEGACY_TABLES = (
    "doe_config",
    "mixture",
    "factor_definition",
    "plate_well",
    "run_level",
    "matched_acquisition",
    "mixture_component",
)
ACTIVE_WELL_TABLE = "acquisition_plan_well"


def _retired(name: str) -> str:
    return f"retired_doe_{name}"


def _normalize_well(value: object) -> str:
    match = re.fullmatch(r"([A-Ha-h])0*([1-9]|1[0-2])", str(value).strip())
    if match is None:
        raise RuntimeError(f"Cannot migrate invalid legacy 96-well position: {value!r}")
    return f"{match.group(1).upper()}{int(match.group(2)):02d}"


def _create_active_table() -> None:
    op.create_table(
        ACTIVE_WELL_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("well_position", sa.String(length=10), nullable=False),
        sa.Column("planned_sample_label", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", "well_position", name="uq_acquisition_plan_well_position"),
    )
    op.create_index(
        "ix_acquisition_plan_well_experiment_id",
        ACTIVE_WELL_TABLE,
        ["experiment_id"],
        unique=False,
    )


def _require_unique_normalized_wells(bind: sa.Connection, table_name: str) -> None:
    """Reject legacy aliases that would collapse onto one canonical well."""

    if not sa.inspect(bind).has_table(table_name):
        return
    table = sa.Table(table_name, sa.MetaData(), autoload_with=bind, resolve_fks=False)
    seen: set[tuple[int, str]] = set()
    for row in bind.execute(
        sa.select(table.c.id, table.c.experiment_id, table.c.well_position).order_by(table.c.id)
    ).mappings():
        key = (int(row["experiment_id"]), _normalize_well(row["well_position"]))
        if key in seen:
            raise RuntimeError(
                "Cannot migrate duplicate legacy plate wells after normalization: " f"experiment {key[0]} well {key[1]}"
            )
        seen.add(key)


def _retired_wells(bind: sa.Connection) -> list[dict[str, object]]:
    inspector = sa.inspect(bind)
    plate_name = _retired("plate_well")
    if not inspector.has_table(plate_name):
        return []
    metadata = sa.MetaData()
    plate = sa.Table(plate_name, metadata, autoload_with=bind)
    mixture_name = _retired("mixture")
    labels: dict[int, str] = {}
    if inspector.has_table(mixture_name):
        mixture = sa.Table(mixture_name, metadata, autoload_with=bind)
        labels = {
            int(row.id): str(row.mixture_id) for row in bind.execute(sa.select(mixture.c.id, mixture.c.mixture_id))
        }
    rows: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    for row in bind.execute(sa.select(plate).order_by(plate.c.id)).mappings():
        well = _normalize_well(row["well_position"])
        key = (int(row["experiment_id"]), well)
        if key in seen:
            raise RuntimeError(
                "Cannot migrate duplicate legacy plate wells after normalization: " f"experiment {key[0]} well {key[1]}"
            )
        seen.add(key)
        mixture_id = row.get("mixture_id")
        rows.append(
            {
                "experiment_id": key[0],
                "well_position": well,
                "planned_sample_label": labels.get(int(mixture_id)) if mixture_id is not None else None,
            }
        )
    return rows


def migrate_retired_doe_storage(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if downgrade:
        if inspector.has_table(ACTIVE_WELL_TABLE) and inspector.has_table(_retired("plate_well")):
            metadata = sa.MetaData()
            active = sa.Table(ACTIVE_WELL_TABLE, metadata, autoload_with=bind)
            active_rows = {
                (int(row.experiment_id), str(row.well_position), row.planned_sample_label)
                for row in bind.execute(
                    sa.select(active.c.experiment_id, active.c.well_position, active.c.planned_sample_label)
                )
            }
            retired_rows = {
                (int(row["experiment_id"]), str(row["well_position"]), row["planned_sample_label"])
                for row in _retired_wells(bind)
            }
            if active_rows != retired_rows:
                raise RuntimeError(
                    "Cannot downgrade after acquisition plans changed; export measured samples and plans first"
                )
        if inspector.has_table(ACTIVE_WELL_TABLE):
            op.drop_table(ACTIVE_WELL_TABLE)
        for name in reversed(LEGACY_TABLES):
            inspector = sa.inspect(bind)
            if inspector.has_table(_retired(name)) and not inspector.has_table(name):
                op.rename_table(_retired(name), name)
        return

    # Preflight before any DDL so a rejected legacy state leaves the original
    # namespace and Alembic revision untouched even on SQLite.
    if inspector.has_table("plate_well") and not inspector.has_table(_retired("plate_well")):
        _require_unique_normalized_wells(bind, "plate_well")

    for name in LEGACY_TABLES:
        inspector = sa.inspect(bind)
        if inspector.has_table(name) and not inspector.has_table(_retired(name)):
            op.rename_table(name, _retired(name))

    rows = _retired_wells(bind)
    inspector = sa.inspect(bind)
    if not inspector.has_table(ACTIVE_WELL_TABLE):
        _create_active_table()
    elif rows:
        metadata = sa.MetaData()
        active = sa.Table(ACTIVE_WELL_TABLE, metadata, autoload_with=bind)
        active_rows = {
            (int(row.experiment_id), str(row.well_position), row.planned_sample_label)
            for row in bind.execute(
                sa.select(active.c.experiment_id, active.c.well_position, active.c.planned_sample_label)
            )
        }
        if active_rows:
            expected = {
                (int(row["experiment_id"]), str(row["well_position"]), row["planned_sample_label"]) for row in rows
            }
            if active_rows != expected:
                raise RuntimeError(
                    "Cannot retire legacy DOE storage because the active acquisition plan already differs"
                )
            return
    if rows:
        metadata = sa.MetaData()
        active = sa.Table(ACTIVE_WELL_TABLE, metadata, autoload_with=bind)
        bind.execute(active.insert(), rows)
    logger.info("Migrated %d intended wells; legacy DOE rows remain in retired_doe_* tables", len(rows))
