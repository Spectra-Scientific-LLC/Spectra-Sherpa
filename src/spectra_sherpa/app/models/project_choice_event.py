"""Append-only, per-scientist choices for the current project.

Generated evidence is never selected here: its active record is the newest
created record, even when that record is incomplete or faulty.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class ProjectChoiceEvent(Base):
    __tablename__ = "project_choice_event"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'dataset' AND workflow_id IS NULL) OR "
            "(kind = 'workflow' AND experiment_id IS NULL AND dataset_view_id IS NULL)",
            name="ck_project_choice_event_target",
        ),
        CheckConstraint(
            "(kind = 'dataset' AND selected_experiment_id IS NOT NULL AND selected_workflow_id IS NULL) OR "
            "(kind = 'workflow' AND selected_workflow_id IS NOT NULL "
            "AND selected_experiment_id IS NULL AND selected_dataset_view_id IS NULL)",
            name="ck_project_choice_event_snapshot",
        ),
        Index("ix_project_choice_event_current", "project_id", "user_id", "kind", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiment.id", ondelete="SET NULL"), nullable=True)
    dataset_view_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_view.id", ondelete="SET NULL"), nullable=True
    )
    workflow_id: Mapped[int | None] = mapped_column(ForeignKey("workflow.id", ondelete="SET NULL"), nullable=True)
    # FK columns can be nulled by a hard delete. Retain the scientist's exact
    # choice so a removed named view is never misread as the Default view.
    selected_experiment_id: Mapped[int | None] = mapped_column(nullable=True)
    selected_dataset_view_id: Mapped[int | None] = mapped_column(nullable=True)
    selected_workflow_id: Mapped[int | None] = mapped_column(nullable=True)
    selected_name: Mapped[str] = mapped_column(String(255), nullable=False)
    selected_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_definition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
