"""Losslessly project every retained DOE concept into acquisition-plan storage."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from alembic import op

from spectra_sherpa.app.schemas.acquisition_plans import AcquisitionPlanDocument

PLAN_TABLE = "acquisition_plan"
PRESET_TABLE = "acquisition_plan_preset"
PREFERENCES_TABLE = "user_workbench_preferences"
WELL_TABLE = "acquisition_plan_well"
IDENTIFIER_MAX_LENGTH = 100
_VALIDATION_SPECIMEN_UID = "00000000-0000-4000-8000-000000000000"


def _json_value(value: object, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _normalize_well(value: object) -> str:
    match = re.fullmatch(r"([A-Ha-h])0*([1-9]|1[0-2])", str(value).strip())
    if match is None:
        raise RuntimeError(f"Cannot migrate invalid legacy 96-well position: {value!r}")
    return f"{match.group(1).upper()}{int(match.group(2)):02d}"


def _table(bind: sa.Connection, name: str, metadata: sa.MetaData) -> sa.Table | None:
    if not sa.inspect(bind).has_table(name):
        return None
    return sa.Table(name, metadata, autoload_with=bind, resolve_fks=False)


def _rows(bind: sa.Connection, table: sa.Table | None) -> list[dict[str, Any]]:
    if table is None:
        return []
    return [dict(row) for row in bind.execute(sa.select(table).order_by(table.c.id)).mappings()]


def _unique_legacy_identifier(value: object, row_id: int, used: set[str]) -> str:
    """Preserve a legacy ID when possible, otherwise append a bounded stable key."""

    base = str(value)
    if base not in used:
        used.add(base)
        return base
    attempt = 1
    while True:
        suffix = f"#legacy-{row_id}" if attempt == 1 else f"#legacy-{row_id}-{attempt}"
        candidate = f"{base[: IDENTIFIER_MAX_LENGTH - len(suffix)]}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        attempt += 1


def _legacy_documents(bind: sa.Connection) -> dict[int, dict[str, object]]:
    metadata = sa.MetaData()
    experiments = _rows(bind, _table(bind, "experiment", metadata))
    users_by_experiment = {int(row["id"]): int(row["user_id"]) for row in experiments}
    samples = _rows(bind, _table(bind, "sample", metadata))
    mixtures = _rows(bind, _table(bind, "retired_doe_mixture", metadata))
    components = _rows(bind, _table(bind, "retired_doe_mixture_component", metadata))
    factors = _rows(bind, _table(bind, "retired_doe_factor_definition", metadata))
    run_levels = _rows(bind, _table(bind, "retired_doe_run_level", metadata))
    retired_wells = _rows(bind, _table(bind, "retired_doe_plate_well", metadata))
    active_wells = _rows(bind, _table(bind, WELL_TABLE, metadata))
    matches = _rows(bind, _table(bind, "retired_doe_matched_acquisition", metadata))

    samples_by_pk = {int(row["id"]): row for row in samples}
    mixtures_by_pk = {int(row["id"]): row for row in mixtures}
    referenced_sample_pks: set[int] = set()
    for row in components:
        mixture = mixtures_by_pk.get(int(row["mixture_id"]))
        if mixture is None:
            raise RuntimeError(f"Cannot migrate mixture component {row['id']}: mixture {row['mixture_id']} is missing")
        sample = samples_by_pk.get(int(row["sample_id"]))
        if sample is None:
            raise RuntimeError(f"Cannot migrate mixture component {row['id']}: sample {row['sample_id']} is missing")
        if int(sample["experiment_id"]) != int(mixture["experiment_id"]):
            raise RuntimeError(
                f"Cannot migrate mixture component {row['id']}: sample {row['sample_id']} belongs to another experiment"
            )
        referenced_sample_pks.add(int(row["sample_id"]))

    # The experiment specimen catalog is a distinct metadata authority.
    # Acquisition plans keep only immutable identity snapshots for specimens
    # actually used by a retained mixture; unreferenced rows and catalog-only
    # fields remain solely in the catalog that the next migration rehomes.
    sample_by_pk: dict[int, str] = {}
    used_sample_ids: dict[int, set[str]] = defaultdict(set)
    samples_by_experiment: dict[int, list[dict[str, object]]] = defaultdict(list)
    for sample_pk in sorted(referenced_sample_pks):
        row = samples_by_pk[sample_pk]
        experiment_id = int(row["experiment_id"])
        sample_key = _unique_legacy_identifier(row["sample_id"], sample_pk, used_sample_ids[experiment_id])
        sample_by_pk[sample_pk] = sample_key
        samples_by_experiment[experiment_id].append(
            {
                "sample_id": sample_key,
                "source_ref": f"legacy-sample:{sample_pk}",
                "name": str(row.get("name") or ""),
                "sample_type": row.get("type"),
                "notes": row.get("notes"),
            }
        )

    components_by_mixture: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in components:
        sample_id = sample_by_pk.get(int(row["sample_id"]))
        if sample_id is None:
            raise RuntimeError(f"Cannot migrate mixture component {row['id']}: sample {row['sample_id']} is missing")
        components_by_mixture[int(row["mixture_id"])].append(
            {"sample_id": sample_id, "amount": row["amount"], "unit": str(row["unit"])}
        )

    mixture_key_by_pk: dict[int, str] = {}
    used_mixture_ids: dict[int, set[str]] = defaultdict(set)
    mixtures_by_experiment: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in mixtures:
        experiment_id = int(row["experiment_id"])
        mixture_key = _unique_legacy_identifier(row["mixture_id"], int(row["id"]), used_mixture_ids[experiment_id])
        mixture_key_by_pk[int(row["id"])] = mixture_key
        mixtures_by_experiment[experiment_id].append(
            {
                "mixture_id": mixture_key,
                "name": row.get("name"),
                "basis": str(row.get("basis") or "volume"),
                "notes": row.get("notes"),
                "components": components_by_mixture[int(row["id"])],
            }
        )
    factor_key_by_pk: dict[int, str] = {}
    factors_by_experiment: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in factors:
        factor_key = f"legacy-{row['id']}"
        factor_key_by_pk[int(row["id"])] = factor_key
        factors_by_experiment[int(row["experiment_id"])].append(
            {
                "factor_id": factor_key,
                "name": str(row["name"]),
                "scope": str(row["scope"]),
                "factor_type": str(row["type"]),
                "unit": row.get("unit"),
                "levels": _json_value(row.get("levels"), []),
            }
        )

    order_by_experiment: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in run_levels:
        factor_key = factor_key_by_pk.get(int(row["factor_definition_id"]))
        if factor_key is None:
            raise RuntimeError(f"Cannot migrate run level {row['id']}: factor {row['factor_definition_id']} is missing")
        order_by_experiment[int(row["experiment_id"])].append(
            {
                "sequence_order": int(row.get("sequence_order") or 0),
                "factor_id": factor_key,
                "level_value": str(row["level_value"]),
                "path": row.get("path"),
                "batch": row.get("batch"),
                "file_count": row.get("file_count"),
            }
        )

    active_by_experiment: dict[int, dict[str, dict[str, object]]] = defaultdict(dict)
    active_well_keys: set[tuple[int, str]] = set()
    for row in active_wells:
        experiment_id = int(row["experiment_id"])
        well = _normalize_well(row["well_position"])
        active_key = (experiment_id, well)
        if active_key in active_well_keys:
            raise RuntimeError(
                "Cannot migrate duplicate active plate wells after normalization: "
                f"experiment {experiment_id} well {well}"
            )
        active_well_keys.add(active_key)
        active_by_experiment[experiment_id][well] = {
            "well_position": well,
            "planned_sample_label": row.get("planned_sample_label"),
            "sample_id": None,
            "mixture_id": None,
            "factor_values": {},
        }
    retired_well_keys: set[tuple[int, str]] = set()
    for row in retired_wells:
        experiment_id = int(row["experiment_id"])
        well = _normalize_well(row["well_position"])
        retired_key = (experiment_id, well)
        if retired_key in retired_well_keys:
            raise RuntimeError(
                "Cannot migrate duplicate retained plate wells after normalization: "
                f"experiment {experiment_id} well {well}"
            )
        retired_well_keys.add(retired_key)
        current = active_by_experiment[experiment_id].setdefault(
            well,
            {
                "well_position": well,
                "planned_sample_label": None,
                "sample_id": None,
                "mixture_id": None,
                "factor_values": {},
            },
        )
        mixture_pk = row.get("mixture_id")
        if mixture_pk is not None:
            mixture_key = mixture_key_by_pk.get(int(mixture_pk))
            if mixture_key is None:
                raise RuntimeError(f"Cannot migrate well {well}: mixture {mixture_pk} is missing")
            current["mixture_id"] = mixture_key
            current["planned_sample_label"] = current["planned_sample_label"] or mixture_key

    matches_by_experiment: dict[int, list[dict[str, object]]] = defaultdict(list)
    for ordinal, row in enumerate(matches):
        cell = row.get("cell")
        matches_by_experiment[int(row["experiment_id"])].append(
            {
                "sequence_order": int(row["seq"]) if row.get("seq") is not None else ordinal,
                "filename": row.get("filename"),
                "folder": row.get("folder"),
                "timestamp": row.get("timestamp"),
                "date": row.get("date"),
                "batch": row.get("batch"),
                "sample_id": row.get("sample_id"),
                "well_position": _normalize_well(cell) if cell else None,
                "special": row.get("special"),
                "factor_values": _json_value(row.get("factor_values"), {}),
            }
        )

    relevant_ids = (
        set(samples_by_experiment)
        | set(mixtures_by_experiment)
        | set(factors_by_experiment)
        | set(order_by_experiment)
        | set(active_by_experiment)
        | set(matches_by_experiment)
    )
    unknown = relevant_ids - set(users_by_experiment)
    if unknown:
        raise RuntimeError(f"Cannot migrate DOE rows for missing experiments: {sorted(unknown)}")
    documents = {
        experiment_id: {
            "schema_version": "spectrasherpa-acquisition-plan/2",
            "plate_format_id": "plate-96",
            "samples": samples_by_experiment[experiment_id],
            "mixtures": mixtures_by_experiment[experiment_id],
            "factors": factors_by_experiment[experiment_id],
            "wells": list(active_by_experiment[experiment_id].values()),
            "acquisition_order": order_by_experiment[experiment_id],
            "matching": {"rules": {}, "matches": matches_by_experiment[experiment_id]},
        }
        for experiment_id in relevant_ids
    }
    # Migration output must satisfy the same contract used on every API read.
    # This runs before _create_tables(), so an unrepresentable legacy value
    # aborts without partially creating the canonical namespace.
    validated: dict[int, dict[str, object]] = {}
    for experiment_id, document in documents.items():
        # Validate the historical v2 payload against the current scientific
        # shape without allowing this older revision to emit the newer UID
        # contract. Revision u0 exclusively owns that transition.
        current = dict(document)
        current["schema_version"] = "spectrasherpa-acquisition-plan/3"
        current["samples"] = [
            {
                **{key: value for key, value in item.items() if key != "source_ref"},
                "source_specimen_uid": _VALIDATION_SPECIMEN_UID,
            }
            for item in document["samples"]
        ]
        AcquisitionPlanDocument.model_validate(current)
        validated[experiment_id] = document
    return validated


def _legacy_presets(bind: sa.Connection) -> list[dict[str, object]]:
    metadata = sa.MetaData()
    rows = _rows(bind, _table(bind, "retired_doe_doe_config", metadata))
    return [
        {
            "user_id": int(row["user_id"]),
            "preset_key": f"legacy-{row['id']}",
            "name": str(row["name"]),
            "description": row.get("description"),
            "is_default": bool(row.get("is_default")),
            "settings": {
                "folder_batch_rules": _json_value(row.get("folder_batch_rules"), {}),
                "filename_patterns": _json_value(row.get("filename_patterns"), {}),
                "scan_defaults": _json_value(row.get("scan_defaults"), {}),
                "run_sequence_template": _json_value(row.get("run_sequence_template"), {}),
                "match_settings": _json_value(row.get("match_settings"), {}),
            },
        }
        for row in rows
    ]


def _create_tables(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(PLAN_TABLE):
        op.create_table(
            PLAN_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=False),
            sa.Column("document", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("experiment_id"),
        )
        op.create_index("ix_acquisition_plan_experiment_id", PLAN_TABLE, ["experiment_id"], unique=True)
    inspector = sa.inspect(bind)
    if not inspector.has_table(PRESET_TABLE):
        op.create_table(
            PRESET_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("preset_key", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("settings", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "preset_key", name="uq_acquisition_plan_preset_key"),
        )
        op.create_index("ix_acquisition_plan_preset_user_id", PRESET_TABLE, ["user_id"], unique=False)
    inspector = sa.inspect(bind)
    if not inspector.has_table(PREFERENCES_TABLE):
        op.create_table(
            PREFERENCES_TABLE,
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("default_plate_format_id", sa.String(length=100), server_default="plate-96", nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
        op.create_index("ix_user_workbench_preferences_user_id", PREFERENCES_TABLE, ["user_id"], unique=True)


def migrate_complete_acquisition_plans(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    if downgrade:
        documents = _legacy_documents(bind)
        plan = _table(bind, PLAN_TABLE, metadata)
        if plan is not None:
            current = {int(row["experiment_id"]): row["document"] for row in bind.execute(sa.select(plan)).mappings()}
            if current != documents:
                raise RuntimeError("Cannot downgrade after complete acquisition plans changed; export plans first")
        if not sa.inspect(bind).has_table(WELL_TABLE):
            op.create_table(
                WELL_TABLE,
                sa.Column("id", sa.Integer(), nullable=False),
                sa.Column("experiment_id", sa.Integer(), nullable=False),
                sa.Column("well_position", sa.String(length=10), nullable=False),
                sa.Column("planned_sample_label", sa.String(length=100), nullable=True),
                sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"], ondelete="CASCADE"),
                sa.PrimaryKeyConstraint("id"),
                sa.UniqueConstraint("experiment_id", "well_position", name="uq_acquisition_plan_well_position"),
            )
            op.create_index("ix_acquisition_plan_well_experiment_id", WELL_TABLE, ["experiment_id"])
        well = sa.Table(WELL_TABLE, sa.MetaData(), autoload_with=bind, resolve_fks=False)
        projected = [
            {
                "experiment_id": experiment_id,
                "well_position": item["well_position"],
                "planned_sample_label": item.get("planned_sample_label"),
            }
            for experiment_id, document in documents.items()
            for item in document["wells"]
        ]
        if projected:
            bind.execute(well.insert(), projected)
        for name in (PREFERENCES_TABLE, PRESET_TABLE, PLAN_TABLE):
            if sa.inspect(bind).has_table(name):
                op.drop_table(name)
        return

    documents = _legacy_documents(bind)
    presets = _legacy_presets(bind)
    _create_tables(bind)
    metadata = sa.MetaData()
    plan = sa.Table(PLAN_TABLE, metadata, autoload_with=bind, resolve_fks=False)
    existing = {int(row["experiment_id"]): row["document"] for row in bind.execute(sa.select(plan)).mappings()}
    for experiment_id, document in documents.items():
        if experiment_id in existing and existing[experiment_id] != document:
            raise RuntimeError(f"Cannot migrate legacy DOE data: acquisition plan {experiment_id} already differs")
        if experiment_id not in existing:
            bind.execute(plan.insert().values(experiment_id=experiment_id, document=document))
    preset = sa.Table(PRESET_TABLE, metadata, autoload_with=bind, resolve_fks=False)
    existing_presets = {
        (int(row["user_id"]), str(row["preset_key"])): dict(row) for row in bind.execute(sa.select(preset)).mappings()
    }
    for value in presets:
        key = (int(value["user_id"]), str(value["preset_key"]))
        if key not in existing_presets:
            bind.execute(preset.insert().values(**value))
    if sa.inspect(bind).has_table(WELL_TABLE):
        op.drop_table(WELL_TABLE)
