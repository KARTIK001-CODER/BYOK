"""Add search_vector tsvector column, GIN index, and retrieval indexes

Revision ID: 0006_retrieval_and_full_text_search
Revises: 0005_embeddings_and_vector_storage
Create Date: 2026-08-31 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_retrieval_and_full_text_search"
down_revision: str | None = "0005_embeddings_and_vector_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add search_vector generated column to document_chunks
    op.add_column(
        "document_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(section_title, '') || ' ' || content)",
                persisted=True,
            ),
            nullable=True,
        ),
    )

    # 2. Create GIN index on search_vector
    op.create_index(
        "ix_document_chunks_search_vector_gin",
        "document_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )

    # 3. Create composite index on (org_id, kb_id) for rapid tenant-scoped retrieval
    op.create_index(
        "ix_document_chunks_org_kb",
        "document_chunks",
        ["organization_id", "knowledge_base_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_org_kb", table_name="document_chunks")
    op.drop_index("ix_document_chunks_search_vector_gin", table_name="document_chunks")
    op.drop_column("document_chunks", "search_vector")
