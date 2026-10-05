"""Retire hidden classifier-local CV without preventing profile startup.

Revision ID: l1m3n5o7p159
Revises: k0l2m4n6o048

Only the editable graph changes. Historical versions, runs and artifacts retain
both their parameters and their original scientific interpretation.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "l1m3n5o7p159"
down_revision = "k0l2m4n6o048"
branch_labels = None
depends_on = None

# Freeze the historical operation identities in this migration.
_CLASSIFIERS = ("classification.knn", "classification.plsda", "classification.simca")
_MARKER = "[Classifier validation migration l1m3n5o7p159]"
_NOTICE = (
    "Classifier-local cross-validation has been retired. New classifier outputs "
    "are calibration-fit diagnostics, not cross-validation evidence. Review the "
    "preserved edges and add an explicit held-out or grouped validation plan "
    "before making validation claims. Historical runs and snapshots are unchanged."
)


def upgrade() -> None:
    """Keep legacy graphs editable and disclose the changed validation contract."""
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("workflow_node"):
        return
    metadata = sa.MetaData()
    nodes = sa.Table("workflow_node", metadata, autoload_with=bind)
    workflows = sa.Table("workflow", metadata, autoload_with=bind)
    affected: dict[int, list[str]] = {}
    for row in bind.execute(sa.select(nodes).where(nodes.c.node_type.in_(_CLASSIFIERS))).mappings():
        parameters = row["parameters"]
        # Invalid retired values need no interpretation: preserve their exact JSON
        # value in the notice and remove only this obsolete, unused input.
        removed = isinstance(parameters, dict) and "cv_folds" in parameters
        original = json.dumps(parameters["cv_folds"], ensure_ascii=True) if removed else "not explicitly stored"
        notice = f"{_MARKER}\n{_NOTICE}\nOriginal cv_folds: {original}"
        updates = {}
        if _MARKER not in (row["annotation"] or ""):
            updates["annotation"] = ((row["annotation"] + "\n\n") if row["annotation"] else "") + notice
        if removed:
            updates["parameters"] = {key: value for key, value in parameters.items() if key != "cv_folds"}
        if updates:
            bind.execute(nodes.update().where(nodes.c.id == row["id"]).values(**updates))
            affected.setdefault(row["workflow_id"], []).append(f"{row['node_id']} (original cv_folds: {original})")
    for workflow_id, node_ids in affected.items():
        row = bind.execute(sa.select(workflows).where(workflows.c.id == workflow_id)).mappings().one()
        notes = row["notes"] or ""
        if _MARKER not in notes:
            notice = f"{_MARKER}\nAffected nodes: {', '.join(sorted(node_ids))}. {_NOTICE}"
            notes += ("\n\n" if notes else "") + notice
        # A historical graph digest must not attest the revised editable graph.
        # Saving it will issue a current digest; historical receipts are untouched.
        bind.execute(
            workflows.update()
            .where(workflows.c.id == workflow_id)
            .values(notes=notes, status="draft", integrity_hash=None)
        )


def downgrade() -> None:
    """Do not invent legacy CV semantics or rewrite historical evidence."""
