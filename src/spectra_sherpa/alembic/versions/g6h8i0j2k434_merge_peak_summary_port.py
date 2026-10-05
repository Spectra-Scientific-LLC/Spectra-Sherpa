"""Merge the redundant peak-summary port in editable workflows only.

Historical runs and version snapshots deliberately retain their original graph.
"""

import sqlalchemy as sa
from alembic import op

from spectra_sherpa.alembic.versions.s8t0u2v4w137_canonical_node_identities import (
    _load_graph,
    _workflow_hash,
    _workflow_tables,
)

revision = "g6h8i0j2k434"
down_revision = "f5g7h9i1j333"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = _workflow_tables(bind)
    if tables is None:
        return
    workflow, node, edge = tables
    affected = (
        bind.execute(
            sa.select(edge.c.workflow_id)
            .join(
                node,
                (node.c.workflow_id == edge.c.workflow_id) & (node.c.node_id == edge.c.from_node_id),
            )
            .where(
                node.c.node_type == "analysis.peak_finding",
                edge.c.from_output == "salient_features",
            )
            .distinct()
        )
        .scalars()
        .all()
    )
    for workflow_id in affected:
        nodes, edges = _load_graph(bind, workflow_id, node, edge)
        stored = bind.execute(sa.select(workflow.c.integrity_hash).where(workflow.c.id == workflow_id)).scalar_one()
        if stored is not None and stored != _workflow_hash(nodes, edges):
            raise RuntimeError("refusing to migrate a peak workflow with an invalid integrity hash")
        peak_ids = {n["node_id"] for n in nodes if n["node_type"] == "analysis.peak_finding"}
        for old in edges:
            if old["from_node_id"] not in peak_ids or old["from_output"] != "salient_features":
                continue
            match = sa.and_(
                edge.c.workflow_id == workflow_id,
                edge.c.from_node_id == old["from_node_id"],
                edge.c.to_node_id == old["to_node_id"],
                edge.c.to_input == old["to_input"],
                edge.c.from_output == "salient_features",
            )
            duplicate = any(
                e["from_node_id"] == old["from_node_id"]
                and e["to_node_id"] == old["to_node_id"]
                and e["to_input"] == old["to_input"]
                and e["from_output"] == "peaks"
                for e in edges
            )
            if duplicate:
                bind.execute(sa.delete(edge).where(match))
            else:
                bind.execute(sa.update(edge).where(match).values(from_output="peaks"))
        nodes, edges = _load_graph(bind, workflow_id, node, edge)
        bind.execute(
            sa.update(workflow).where(workflow.c.id == workflow_id).values(integrity_hash=_workflow_hash(nodes, edges))
        )


def downgrade():
    bind = op.get_bind()
    tables = _workflow_tables(bind)
    if tables is None:
        return
    _, node, edge = tables
    merged_edges = bind.execute(
        sa.select(edge.c.workflow_id)
        .join(node, (node.c.workflow_id == edge.c.workflow_id) & (node.c.node_id == edge.c.from_node_id))
        .where(node.c.node_type == "analysis.peak_finding", edge.c.from_output == "peaks")
        .limit(1)
    ).first()
    if merged_edges is None:
        # No editable connection requires an ambiguous reverse mapping. This
        # data-only migration leaves unrelated schemas and history unchanged.
        return
    # The merged table contains additional information, and connections no longer
    # identify which obsolete presentation the user originally chose.
    raise RuntimeError("Peak summary consolidation is not reversible; restore a pre-migration backup to downgrade")
