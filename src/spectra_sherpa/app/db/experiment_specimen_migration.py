"""Move the retained specimen catalog into its experiment-owned authority."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

_MIGRATION_NAMESPACE = uuid.UUID("772c6d35-2445-49cb-b708-70ab67ecbf97")


def migrated_specimen_uid(legacy_id: int) -> str:
    """Return the stable UUID assigned to a pre-authority specimen row."""

    return str(uuid.uuid5(_MIGRATION_NAMESPACE, f"legacy-sample:{legacy_id}"))


def _bounded_unique_key(value: object, legacy_id: int, used: set[str]) -> str:
    base = str(value or f"specimen-{legacy_id}").strip() or f"specimen-{legacy_id}"
    base = base[:100]
    candidate = base
    suffix = f"#legacy-{legacy_id}"
    if candidate in used:
        candidate = f"{base[: 100 - len(suffix)]}{suffix}"
    ordinal = 2
    while candidate in used:
        numbered_suffix = f"{suffix}-{ordinal}"
        candidate = f"{base[: 100 - len(numbered_suffix)]}{numbered_suffix}"
        ordinal += 1
    used.add(candidate)
    return candidate


def _json_document(value: object) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError("Acquisition plan document must be a JSON object")
    return dict(value)


def _migrate_plan_links(bind: sa.Connection, uid_by_legacy_id: dict[int, str]) -> None:
    if not sa.inspect(bind).has_table("acquisition_plan"):
        return
    plan = sa.Table("acquisition_plan", sa.MetaData(), autoload_with=bind, resolve_fks=False)
    for row in bind.execute(sa.select(plan.c.id, plan.c.document)).mappings():
        document = _json_document(row["document"])
        changed = False
        schema_version = document.get("schema_version")
        if schema_version == "spectrasherpa-acquisition-plan/2":
            document["schema_version"] = "spectrasherpa-acquisition-plan/3"
            changed = True
        elif schema_version != "spectrasherpa-acquisition-plan/3":
            raise RuntimeError(f"Acquisition plan {row['id']} has unsupported schema version {schema_version!r}")
        samples = document.get("samples", [])
        if not isinstance(samples, list):
            raise RuntimeError(f"Acquisition plan {row['id']} samples must be a list")
        migrated_samples: list[object] = []
        for item in samples:
            if not isinstance(item, dict):
                raise RuntimeError(f"Acquisition plan {row['id']} contains an invalid sample snapshot")
            migrated = dict(item)
            source_ref = migrated.pop("source_ref", None)
            if source_ref is not None:
                prefix = "legacy-sample:"
                if not isinstance(source_ref, str) or not source_ref.startswith(prefix):
                    raise RuntimeError(
                        f"Acquisition plan {row['id']} contains unsupported specimen reference {source_ref!r}"
                    )
                try:
                    legacy_id = int(source_ref.removeprefix(prefix))
                    migrated["source_specimen_uid"] = uid_by_legacy_id[legacy_id]
                except (ValueError, KeyError) as exc:
                    raise RuntimeError(
                        f"Acquisition plan {row['id']} references missing specimen {source_ref!r}"
                    ) from exc
                changed = True
            migrated_samples.append(migrated)
        if changed:
            document["samples"] = migrated_samples
            bind.execute(plan.update().where(plan.c.id == row["id"]).values(document=document))


def _downgrade_plan_links(bind: sa.Connection, legacy_id_by_uid: dict[str, int]) -> None:
    """Restore schema-v2 specimen references before the UID column disappears."""

    if not sa.inspect(bind).has_table("acquisition_plan"):
        return
    plan = sa.Table("acquisition_plan", sa.MetaData(), autoload_with=bind, resolve_fks=False)
    rewritten: list[tuple[int, dict[str, object]]] = []
    for row in bind.execute(sa.select(plan.c.id, plan.c.document)).mappings():
        document = _json_document(row["document"])
        schema_version = document.get("schema_version")
        if schema_version != "spectrasherpa-acquisition-plan/3":
            raise RuntimeError(f"Acquisition plan {row['id']} has unsupported schema version {schema_version!r}")
        samples = document.get("samples", [])
        if not isinstance(samples, list):
            raise RuntimeError(f"Acquisition plan {row['id']} samples must be a list")
        downgraded_samples: list[object] = []
        for item in samples:
            if not isinstance(item, dict):
                raise RuntimeError(f"Acquisition plan {row['id']} contains an invalid sample snapshot")
            downgraded = dict(item)
            specimen_uid = downgraded.pop("source_specimen_uid", None)
            if specimen_uid is not None:
                legacy_id = legacy_id_by_uid.get(str(specimen_uid))
                if legacy_id is None:
                    raise RuntimeError(
                        f"Cannot downgrade acquisition plan {row['id']}: specimen {specimen_uid!r} "
                        "has no legacy row; export specimens and plans first"
                    )
                downgraded["source_ref"] = f"legacy-sample:{legacy_id}"
            downgraded_samples.append(downgraded)
        document["schema_version"] = "spectrasherpa-acquisition-plan/2"
        document["samples"] = downgraded_samples
        rewritten.append((int(row["id"]), document))

    # Preflight every document before changing any row. A refused downgrade
    # therefore leaves both the plan documents and specimen authority intact.
    for plan_id, document in rewritten:
        bind.execute(plan.update().where(plan.c.id == plan_id).values(document=document))


def _plan_referenced_legacy_ids(bind: sa.Connection, legacy_id_by_uid: dict[str, int]) -> set[int]:
    """Return catalog rows whose legacy keys already anchor plan snapshots."""

    if not sa.inspect(bind).has_table("acquisition_plan"):
        return set()
    plan = sa.Table("acquisition_plan", sa.MetaData(), autoload_with=bind, resolve_fks=False)
    referenced: set[int] = set()
    for row in bind.execute(sa.select(plan.c.document)).mappings():
        document = _json_document(row["document"])
        samples = document.get("samples", [])
        if not isinstance(samples, list):
            continue
        for item in samples:
            if not isinstance(item, dict):
                continue
            source_ref = item.get("source_ref")
            if isinstance(source_ref, str) and source_ref.startswith("legacy-sample:"):
                try:
                    referenced.add(int(source_ref.removeprefix("legacy-sample:")))
                except ValueError:
                    continue
            specimen_uid = item.get("source_specimen_uid")
            if specimen_uid is not None:
                legacy_id = legacy_id_by_uid.get(str(specimen_uid))
                if legacy_id is not None:
                    referenced.add(legacy_id)
    return referenced


def migrate_experiment_specimen_authority(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if downgrade:
        if not inspector.has_table("experiment_specimen"):
            return
        specimen = sa.Table("experiment_specimen", sa.MetaData(), autoload_with=bind, resolve_fks=False)
        legacy_id_by_uid = {
            str(row.specimen_uid): int(row.id)
            for row in bind.execute(sa.select(specimen.c.id, specimen.c.specimen_uid))
        }
        _downgrade_plan_links(bind, legacy_id_by_uid)
        indexes = inspector.get_indexes("experiment_specimen")
        if any(index["name"] == "ix_experiment_specimen_experiment_id" for index in indexes):
            op.drop_index("ix_experiment_specimen_experiment_id", table_name="experiment_specimen")
        with op.batch_alter_table("experiment_specimen") as batch_op:
            batch_op.drop_constraint("uq_experiment_specimen_key", type_="unique")
            batch_op.drop_constraint("uq_experiment_specimen_uid", type_="unique")
            batch_op.drop_column("updated_at")
            batch_op.drop_column("specimen_uid")
            batch_op.alter_column("specimen_key", new_column_name="sample_id")
            batch_op.alter_column("specimen_type", new_column_name="type")
        op.rename_table("experiment_specimen", "sample")
        op.create_index("ix_sample_experiment_id", "sample", ["experiment_id"])
        return

    has_sample = inspector.has_table("sample")
    has_authority = inspector.has_table("experiment_specimen")
    if has_sample and has_authority:
        specimen = sa.Table("experiment_specimen", sa.MetaData(), autoload_with=bind, resolve_fks=False)
        if bind.execute(sa.select(sa.func.count()).select_from(specimen)).scalar_one():
            raise RuntimeError("Both sample and experiment_specimen contain authoritative rows")
        op.drop_table("experiment_specimen")
    if not has_sample:
        return
    op.rename_table("sample", "experiment_specimen")
    inspector = sa.inspect(bind)
    if any(index["name"] == "ix_sample_experiment_id" for index in inspector.get_indexes("experiment_specimen")):
        op.drop_index("ix_sample_experiment_id", table_name="experiment_specimen")
    with op.batch_alter_table("experiment_specimen") as batch_op:
        batch_op.alter_column("sample_id", new_column_name="specimen_key")
        batch_op.alter_column("type", new_column_name="specimen_type")
        batch_op.add_column(sa.Column("specimen_uid", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    specimen = sa.Table("experiment_specimen", sa.MetaData(), autoload_with=bind, resolve_fks=False)
    rows = list(bind.execute(sa.select(specimen).order_by(specimen.c.id)).mappings())
    used_by_experiment: dict[int, set[str]] = defaultdict(set)
    uid_by_legacy_id = {int(row["id"]): migrated_specimen_uid(int(row["id"])) for row in rows}
    legacy_id_by_uid = {uid: legacy_id for legacy_id, uid in uid_by_legacy_id.items()}
    referenced_legacy_ids = _plan_referenced_legacy_ids(bind, legacy_id_by_uid)
    now = datetime.now(timezone.utc)
    # t9 allocated plan-local keys over referenced rows only. Give those rows
    # the same first claim on a duplicate textual key, then uniquify catalog-
    # only rows. This keeps an untouched full upgrade/downgrade chain symmetric.
    for row in sorted(rows, key=lambda item: (int(item["id"]) not in referenced_legacy_ids, int(item["id"]))):
        legacy_id = int(row["id"])
        uid = uid_by_legacy_id[legacy_id]
        key = _bounded_unique_key(row["specimen_key"], legacy_id, used_by_experiment[int(row["experiment_id"])])
        bind.execute(
            specimen.update()
            .where(specimen.c.id == legacy_id)
            .values(
                specimen_uid=uid,
                specimen_key=key,
                active=bool(row["active"]) if row["active"] is not None else True,
                created_at=row["created_at"] or now,
                updated_at=row["created_at"] or now,
            )
        )

    _migrate_plan_links(bind, uid_by_legacy_id)
    with op.batch_alter_table("experiment_specimen") as batch_op:
        batch_op.alter_column("specimen_uid", existing_type=sa.String(length=36), nullable=False)
        batch_op.alter_column("active", existing_type=sa.Boolean(), nullable=False)
        batch_op.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
        batch_op.create_unique_constraint("uq_experiment_specimen_uid", ["specimen_uid"])
        batch_op.create_unique_constraint("uq_experiment_specimen_key", ["experiment_id", "specimen_key"])
    op.create_index(
        "ix_experiment_specimen_experiment_id",
        "experiment_specimen",
        ["experiment_id"],
    )
