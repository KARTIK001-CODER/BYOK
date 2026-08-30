"""Create knowledge_bases, documents, and document_versions tables

Revision ID: 0003_knowledge_bases_and_documents
Revises: 0002_auth_and_multitenancy
Create Date: 2026-08-30 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_knowledge_bases_and_documents"
down_revision: str | None = "0002_auth_and_multitenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create knowledge_bases table
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_knowledge_bases_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_knowledge_bases_created_by_users",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "slug",
            name="uq_knowledge_bases_org_slug",
        ),
    )
    op.create_index(
        "ix_knowledge_bases_organization_id",
        "knowledge_bases",
        ["organization_id"],
    )
    op.create_index(
        "ix_knowledge_bases_slug",
        "knowledge_bases",
        ["slug"],
    )

    # 2. Create documents table
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="UPLOADED", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name="fk_documents_knowledge_base_id_knowledge_bases",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_documents_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name="fk_documents_uploaded_by_users",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_documents_knowledge_base_id", "documents", ["knowledge_base_id"])
    op.create_index("ix_documents_organization_id", "documents", ["organization_id"])
    op.create_index("ix_documents_checksum", "documents", ["checksum"])
    op.create_index("ix_documents_status", "documents", ["status"])

    # 3. Create document_versions table
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("uploaded_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_versions_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name="fk_document_versions_uploaded_by_users",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_doc_version",
        ),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index("ix_document_versions_checksum", "document_versions", ["checksum"])


def downgrade() -> None:
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
