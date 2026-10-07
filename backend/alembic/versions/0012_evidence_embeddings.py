"""Add vector embedding columns and HNSW index to evidence_events

Revision ID: 0012_evidence_embeddings
Revises: 0011_investigation_single_active
Create Date: 2026-10-07 00:00:00.000000

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_evidence_embeddings"
down_revision: str | None = "0011_investigation_single_active"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evidence_events",
        sa.Column("embedding", pgvector.sqlalchemy.Vector(384), nullable=True),
    )
    op.add_column(
        "evidence_events",
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "evidence_events",
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_evidence_events_embedding_hnsw",
        "evidence_events",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_events_embedding_hnsw", table_name="evidence_events")
    op.drop_column("evidence_events", "embedded_at")
    op.drop_column("evidence_events", "embedding_model")
    op.drop_column("evidence_events", "embedding")
