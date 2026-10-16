"""Retain model-bound native analytical qualification history."""

import sqlalchemy as sa
from alembic import op

revision = "m2n4o6p8q660"
down_revision = "l1m3n5o7p659"
branch_labels = None
depends_on = None


_TABLE = "saved_model_qualification_record"
_COLUMNS = {
    "id": sa.Integer,
    "user_id": sa.Integer,
    "project_id": sa.Integer,
    "artifact_uid": sa.String,
    "record_digest": sa.String,
    "kind": sa.String,
    "parent_digest": sa.String,
    "model_integrity_hash": sa.String,
    "manifest_digest": sa.String,
    "application_plan_digest": sa.String,
    "validation_view_id": sa.Integer,
    "validation_view_digest": sa.String,
    "payload": sa.JSON,
    "created_at": sa.DateTime,
}
_NULLABLE = {"parent_digest"}
_INDEXES = {
    "ix_saved_model_qualification_record_user_id": ["user_id"],
    "ix_saved_model_qualification_record_project_id": ["project_id"],
    "ix_saved_model_qualification_record_artifact_uid": ["artifact_uid"],
}


def _validate_existing_table(inspector):
    """Accept only the current metadata bootstrap shape, never a partial table."""
    columns = {column["name"]: column for column in inspector.get_columns(_TABLE)}
    if set(columns) != set(_COLUMNS):
        raise RuntimeError(f"Incompatible existing {_TABLE}: column set")
    for name, expected_type in _COLUMNS.items():
        column = columns[name]
        if not isinstance(column["type"], expected_type):
            raise RuntimeError(f"Incompatible existing {_TABLE}: {name} type")
        if isinstance(column["type"], sa.String):
            length = {
                "artifact_uid": 36,
                "record_digest": 64,
                "kind": 32,
                "parent_digest": 64,
                "model_integrity_hash": 64,
                "manifest_digest": 64,
                "application_plan_digest": 64,
                "validation_view_digest": 64,
            }[name]
            if column["type"].length != length:
                raise RuntimeError(f"Incompatible existing {_TABLE}: {name} length")
        if name != "id" and bool(column["nullable"]) != (name in _NULLABLE):
            raise RuntimeError(f"Incompatible existing {_TABLE}: {name} nullability")
    if not columns["created_at"].get("default"):
        raise RuntimeError(f"Incompatible existing {_TABLE}: created_at server default")
    if inspector.bind.dialect.name == "postgresql" and not (
        columns["id"].get("identity") or columns["id"].get("default")
    ):
        raise RuntimeError(f"Incompatible existing {_TABLE}: id generator")
    if inspector.get_pk_constraint(_TABLE)["constrained_columns"] != ["id"]:
        raise RuntimeError(f"Incompatible existing {_TABLE}: primary key")
    unique = {item["name"]: item["column_names"] for item in inspector.get_unique_constraints(_TABLE)}
    if unique.get("uq_saved_model_qualification_digest") != ["user_id", "artifact_uid", "record_digest"]:
        raise RuntimeError(f"Incompatible existing {_TABLE}: unique constraint")
    foreign_keys = {
        (tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"])): item
        for item in inspector.get_foreign_keys(_TABLE)
    }
    for column, referred_table in (("user_id", "user"), ("project_id", "project")):
        key = ((column,), referred_table, ("id",))
        if key not in foreign_keys or foreign_keys[key].get("options", {}).get("ondelete", "").upper() != "CASCADE":
            raise RuntimeError(f"Incompatible existing {_TABLE}: {column} foreign key")
    indexes = {item["name"]: item for item in inspector.get_indexes(_TABLE)}
    for name, column_names in _INDEXES.items():
        item = indexes.get(name)
        if item is None or item["column_names"] != column_names or item["unique"]:
            raise RuntimeError(f"Incompatible existing {_TABLE}: {name} index")


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE):
        _validate_existing_table(inspector)
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_uid", sa.String(36), nullable=False),
        sa.Column("record_digest", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("parent_digest", sa.String(64), nullable=True),
        sa.Column("model_integrity_hash", sa.String(64), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("application_plan_digest", sa.String(64), nullable=False),
        sa.Column("validation_view_id", sa.Integer(), nullable=False),
        sa.Column("validation_view_digest", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "artifact_uid", "record_digest", name="uq_saved_model_qualification_digest"),
    )
    op.create_index("ix_saved_model_qualification_record_user_id", "saved_model_qualification_record", ["user_id"])
    op.create_index(
        "ix_saved_model_qualification_record_project_id", "saved_model_qualification_record", ["project_id"]
    )
    op.create_index(
        "ix_saved_model_qualification_record_artifact_uid", "saved_model_qualification_record", ["artifact_uid"]
    )


def downgrade():
    op.drop_index("ix_saved_model_qualification_record_artifact_uid", table_name="saved_model_qualification_record")
    op.drop_index("ix_saved_model_qualification_record_project_id", table_name="saved_model_qualification_record")
    op.drop_index("ix_saved_model_qualification_record_user_id", table_name="saved_model_qualification_record")
    op.drop_table("saved_model_qualification_record")
