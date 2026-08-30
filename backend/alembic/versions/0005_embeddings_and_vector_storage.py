"""Add vector embedding columns, embedding_jobs table, and HNSW index

Revision ID: 0005_embeddings_and_vector_storage
Revises: 0004_ingestion_jobs_and_chunks
Create Date: 2026-08-30 04:00:00.000000

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_embeddings_and_vector_storage"
down_revision: str | None = "0004_ingestion_jobs_and_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add embedding columns to document_chunks
    op.add_column(
        "document_chunks",
        sa.Column("embedding", pgvector.sqlalchemy.Vector(384), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedding_provider", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Add embedding_status column to documents
    op.add_column(
        "documents",
        sa.Column("embedding_status", sa.String(length=30), nullable=True),
    )

    # 3. Create embedding_jobs table
    op.create_table(
        "embedding_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("document_version_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="PENDING", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("total_chunks", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("processed_chunks", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_chunks", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_embedding_jobs_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_embedding_jobs_document_version_id_document_versions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_embedding_jobs_organization_id_organizations",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_embedding_jobs_document_id", "embedding_jobs", ["document_id"])
    op.create_index(
        "ix_embedding_jobs_document_version_id",
        "embedding_jobs",
        ["document_version_id"],
    )
    op.create_index("ix_embedding_jobs_organization_id", "embedding_jobs", ["organization_id"])
    op.create_index("ix_embedding_jobs_status", "embedding_jobs", ["status"])

    # 4. Create HNSW Cosine Vector Index on document_chunks
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.drop_table("embedding_jobs")
    op.drop_column("documents", "embedding_status")
    op.drop_column("document_chunks", "embedded_at")
    op.drop_column("document_chunks", "embedding_dimension")
    op.drop_column("document_chunks", "embedding_provider")
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "embedding")
