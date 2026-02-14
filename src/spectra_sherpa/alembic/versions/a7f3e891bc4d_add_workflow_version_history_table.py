"""Add workflow version history table

Revision ID: a7f3e891bc4d
Revises:
Create Date: 2026-01-15 10:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7f3e891bc4d'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def _ensure_user_table() -> None:
    if _table_exists("user"):
        return

    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("api_key_hash", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    if not _index_exists("user", "ix_user_username"):
        op.create_index("ix_user_username", "user", ["username"], unique=False)


def _ensure_workflow_table() -> None:
    if _table_exists("workflow"):
        return

    op.create_table(
        "workflow",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("canvas_state", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("last_executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("workflow", "ix_workflow_user_id"):
        op.create_index("ix_workflow_user_id", "workflow", ["user_id"], unique=False)
    if not _index_exists("workflow", "ix_workflow_status"):
        op.create_index("ix_workflow_status", "workflow", ["status"], unique=False)
    if not _index_exists("workflow", "ix_workflow_created_at"):
        op.create_index("ix_workflow_created_at", "workflow", ["created_at"], unique=False)


def _ensure_workflow_node_table() -> None:
    if _table_exists("workflow_node"):
        return

    op.create_table(
        "workflow_node",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("node_type", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("position_x", sa.Float(), nullable=True),
        sa.Column("position_y", sa.Float(), nullable=True),
        sa.Column("execution_order", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("workflow_node", "ix_workflow_node_workflow_id"):
        op.create_index(
            "ix_workflow_node_workflow_id", "workflow_node", ["workflow_id"], unique=False
        )
    if not _index_exists("workflow_node", "ix_workflow_node_node_type"):
        op.create_index(
            "ix_workflow_node_node_type", "workflow_node", ["node_type"], unique=False
        )


def _ensure_workflow_edge_table() -> None:
    if _table_exists("workflow_edge"):
        return
    op.create_table(
        "workflow_edge",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("from_node_id", sa.String(length=255), nullable=False),
        sa.Column("to_node_id", sa.String(length=255), nullable=False),
        sa.Column("from_output", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column("to_input", sa.String(length=100), nullable=False, server_default="default"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("workflow_edge", "ix_workflow_edge_workflow_id"):
        op.create_index("ix_workflow_edge_workflow_id", "workflow_edge", ["workflow_id"])


def _ensure_experiment_table() -> None:
    if _table_exists("experiment"):
        return
    op.create_table(
        "experiment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_path", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("experiment", "ix_experiment_user_id"):
        op.create_index("ix_experiment_user_id", "experiment", ["user_id"])
    if not _index_exists("experiment", "ix_experiment_created_at"):
        op.create_index("ix_experiment_created_at", "experiment", ["created_at"])


def _ensure_experiment_file_table() -> None:
    if _table_exists("experiment_file"):
        return
    op.create_table(
        "experiment_file",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=True),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("experiment_file", "ix_experiment_file_experiment_id"):
        op.create_index("ix_experiment_file_experiment_id", "experiment_file", ["experiment_id"])
    if not _index_exists("experiment_file", "ix_experiment_file_stage"):
        op.create_index("ix_experiment_file_stage", "experiment_file", ["stage"])


def _ensure_exp_version_table() -> None:
    if _table_exists("exp_version"):
        return
    op.create_table(
        "exp_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("version_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("manifest_path", sa.String(length=500), nullable=False),
        sa.Column("parent_version_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"]),
        sa.ForeignKeyConstraint(["parent_version_id"], ["exp_version.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", "version_name"),
    )
    if not _index_exists("exp_version", "ix_exp_version_experiment_id"):
        op.create_index("ix_exp_version_experiment_id", "exp_version", ["experiment_id"])
    if not _index_exists("exp_version", "ix_exp_version_created_at"):
        op.create_index("ix_exp_version_created_at", "exp_version", ["created_at"])


def _ensure_calibration_table() -> None:
    if _table_exists("calibration"):
        return
    op.create_table(
        "calibration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("compound_name", sa.String(length=100), nullable=False),
        sa.Column("concentration_mode", sa.String(length=50), nullable=False),
        sa.Column("x_unit", sa.String(length=50), nullable=False),
        sa.Column("pathlength_m", sa.Float(), nullable=True),
        sa.Column("metadata_path", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("calibration", "ix_calibration_user_id"):
        op.create_index("ix_calibration_user_id", "calibration", ["user_id"])
    if not _index_exists("calibration", "ix_calibration_compound_name"):
        op.create_index("ix_calibration_compound_name", "calibration", ["compound_name"])


def _ensure_calibration_file_table() -> None:
    if _table_exists("calibration_file"):
        return
    op.create_table(
        "calibration_file",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calibration_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("concentration", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(["calibration_id"], ["calibration.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("calibration_file", "ix_calibration_file_calibration_id"):
        op.create_index("ix_calibration_file_calibration_id", "calibration_file", ["calibration_id"])


def _ensure_cal_model_table() -> None:
    if _table_exists("cal_model"):
        return
    op.create_table(
        "cal_model",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("calibration_id", sa.Integer(), nullable=False),
        sa.Column("version_name", sa.String(length=100), nullable=False),
        sa.Column("model_type", sa.String(length=50), nullable=False),
        sa.Column("model_path", sa.String(length=500), nullable=False),
        sa.Column("r_squared", sa.Float(), nullable=True),
        sa.Column("rmse", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(["calibration_id"], ["calibration.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("calibration_id", "version_name"),
    )
    if not _index_exists("cal_model", "ix_cal_model_calibration_id"):
        op.create_index("ix_cal_model_calibration_id", "cal_model", ["calibration_id"])


def _ensure_nist_library_table() -> None:
    if _table_exists("nist_library"):
        return
    op.create_table(
        "nist_library",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cas_number", sa.String(length=50), nullable=False),
        sa.Column("compound_name", sa.String(length=255), nullable=False),
        sa.Column("resolution", sa.String(length=20), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column(
            "downloaded_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cas_number", "resolution"),
    )
    if not _index_exists("nist_library", "ix_nist_library_cas_number"):
        op.create_index("ix_nist_library_cas_number", "nist_library", ["cas_number"])
    if not _index_exists("nist_library", "ix_nist_library_compound_name"):
        op.create_index("ix_nist_library_compound_name", "nist_library", ["compound_name"])


def _ensure_background_job_table() -> None:
    if _table_exists("background_job"):
        return
    op.create_table(
        "background_job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("result_path", sa.String(length=500), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("compute_location", sa.String(length=20), server_default="local", nullable=False),
        sa.Column("compute_node", sa.String(length=100), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("background_job", "ix_background_job_user_id"):
        op.create_index("ix_background_job_user_id", "background_job", ["user_id"])
    if not _index_exists("background_job", "ix_background_job_status"):
        op.create_index("ix_background_job_status", "background_job", ["status"])
    if not _index_exists("background_job", "ix_background_job_compute_location"):
        op.create_index("ix_background_job_compute_location", "background_job", ["compute_location"])
    if not _index_exists("background_job", "ix_background_job_last_heartbeat"):
        op.create_index("ix_background_job_last_heartbeat", "background_job", ["last_heartbeat"])
    if not _index_exists("background_job", "ix_background_job_created_at"):
        op.create_index("ix_background_job_created_at", "background_job", ["created_at"])


def _ensure_sample_table() -> None:
    if _table_exists("sample"):
        return
    op.create_table(
        "sample",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("sample_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=True),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("cas_number", sa.String(length=50), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="1"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("sample", "ix_sample_experiment_id"):
        op.create_index("ix_sample_experiment_id", "sample", ["experiment_id"])


def _ensure_mixture_table() -> None:
    if _table_exists("mixture"):
        return
    op.create_table(
        "mixture",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("mixture_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("basis", sa.String(length=20), server_default="volume"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("mixture", "ix_mixture_experiment_id"):
        op.create_index("ix_mixture_experiment_id", "mixture", ["experiment_id"])


def _ensure_mixture_component_table() -> None:
    if _table_exists("mixture_component"):
        return
    op.create_table(
        "mixture_component",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mixture_id", sa.Integer(), nullable=False),
        sa.Column("sample_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["mixture_id"], ["mixture.id"]),
        sa.ForeignKeyConstraint(["sample_id"], ["sample.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("mixture_component", "ix_mixture_component_mixture_id"):
        op.create_index("ix_mixture_component_mixture_id", "mixture_component", ["mixture_id"])
    if not _index_exists("mixture_component", "ix_mixture_component_sample_id"):
        op.create_index("ix_mixture_component_sample_id", "mixture_component", ["sample_id"])


def _ensure_factor_definition_table() -> None:
    if _table_exists("factor_definition"):
        return
    op.create_table(
        "factor_definition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("levels", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("factor_definition", "ix_factor_definition_experiment_id"):
        op.create_index("ix_factor_definition_experiment_id", "factor_definition", ["experiment_id"])


def _ensure_plate_well_table() -> None:
    if _table_exists("plate_well"):
        return
    op.create_table(
        "plate_well",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("well_position", sa.String(length=10), nullable=False),
        sa.Column("mixture_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"]),
        sa.ForeignKeyConstraint(["mixture_id"], ["mixture.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("plate_well", "ix_plate_well_experiment_id"):
        op.create_index("ix_plate_well_experiment_id", "plate_well", ["experiment_id"])


def _ensure_run_level_table() -> None:
    if _table_exists("run_level"):
        return
    op.create_table(
        "run_level",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=False),
        sa.Column("factor_definition_id", sa.Integer(), nullable=False),
        sa.Column("level_value", sa.String(length=100), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=True),
        sa.Column("batch", sa.Integer(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=True),
        sa.Column("sequence_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiment.id"]),
        sa.ForeignKeyConstraint(["factor_definition_id"], ["factor_definition.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("run_level", "ix_run_level_experiment_id"):
        op.create_index("ix_run_level_experiment_id", "run_level", ["experiment_id"])
    if not _index_exists("run_level", "ix_run_level_factor_definition_id"):
        op.create_index("ix_run_level_factor_definition_id", "run_level", ["factor_definition_id"])


def _ensure_llm_config_table() -> None:
    if _table_exists("llm_config"):
        return
    op.create_table(
        "llm_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="deepseek"),
        sa.Column("base_url", sa.String(length=255), nullable=False, server_default="https://api.deepseek.com"),
        sa.Column("model", sa.String(length=100), nullable=False, server_default="deepseek-chat"),
        sa.Column("verbose", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    if not _index_exists("llm_config", "ix_llm_config_user_id"):
        op.create_index("ix_llm_config_user_id", "llm_config", ["user_id"])


def _ensure_api_key_table() -> None:
    if _table_exists("api_key"):
        return
    op.create_table(
        "api_key",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("service_name", sa.String(length=100), nullable=False),
        sa.Column("key_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "service_name"),
    )
    if not _index_exists("api_key", "ix_api_key_user_id"):
        op.create_index("ix_api_key_user_id", "api_key", ["user_id"])


def upgrade() -> None:
    # Bootstraps core tables when migrating a fresh database with no prior schema.
    # All _ensure_* functions are idempotent (skip if table exists).
    _ensure_user_table()
    _ensure_workflow_table()
    _ensure_workflow_node_table()
    _ensure_workflow_edge_table()
    _ensure_experiment_table()
    _ensure_experiment_file_table()
    _ensure_exp_version_table()
    _ensure_calibration_table()
    _ensure_calibration_file_table()
    _ensure_cal_model_table()
    _ensure_nist_library_table()
    _ensure_background_job_table()
    _ensure_sample_table()
    _ensure_mixture_table()
    _ensure_mixture_component_table()
    _ensure_factor_definition_table()
    _ensure_plate_well_table()
    _ensure_run_level_table()
    _ensure_llm_config_table()
    _ensure_api_key_table()

    if not _table_exists("workflow_version"):
        op.create_table(
            "workflow_version",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workflow_id", sa.Integer(), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("change_description", sa.Text(), nullable=True),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _index_exists("workflow_version", op.f("ix_workflow_version_created_at")):
        op.create_index(
            op.f("ix_workflow_version_created_at"),
            "workflow_version",
            ["created_at"],
            unique=False,
        )
    if not _index_exists("workflow_version", op.f("ix_workflow_version_created_by")):
        op.create_index(
            op.f("ix_workflow_version_created_by"),
            "workflow_version",
            ["created_by"],
            unique=False,
        )
    if not _index_exists("workflow_version", op.f("ix_workflow_version_workflow_id")):
        op.create_index(
            op.f("ix_workflow_version_workflow_id"),
            "workflow_version",
            ["workflow_id"],
            unique=False,
        )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_workflow_version_workflow_id'), table_name='workflow_version')
    op.drop_index(op.f('ix_workflow_version_created_by'), table_name='workflow_version')
    op.drop_index(op.f('ix_workflow_version_created_at'), table_name='workflow_version')
    op.drop_table('workflow_version')
    # ### end Alembic commands ###
