from sqlalchemy import and_, select
from sqlalchemy.sql.elements import BinaryExpression, ColumnElement

from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.services.retrieval.schemas import RetrievalFilter


class RetrievalFilterBuilder:
    """Safe, parameterized query filter builder for tenant-scoped retrieval queries."""

    @staticmethod
    def build_chunk_filters(
        organization_id: str,
        knowledge_base_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        filters: RetrievalFilter | None = None,
    ) -> list[ColumnElement[bool] | BinaryExpression]:
        """
        Build mandatory and optional WHERE conditions for DocumentChunk retrieval.

        Enforces:
        1. Tenant Isolation: Always filters on organization_id at the DB level.
        2. Knowledge Base Scoping: Filters on explicit knowledge_base_ids if supplied.
        3. Document Scoping: Filters on explicit document_ids or document_version_ids if supplied.
        4. Document Lifecycle: Only matches READY active document chunks.
        5. Version Integrity: Only matches chunks belonging to the current document version.
        """
        conditions: list[ColumnElement[bool] | BinaryExpression] = [
            DocumentChunk.organization_id == organization_id,
        ]

        # 1. Merge knowledge_base_ids from top-level request and structured filter
        combined_kb_ids: set[str] = set()
        if knowledge_base_ids:
            combined_kb_ids.update(knowledge_base_ids)
        if filters and filters.knowledge_base_ids:
            combined_kb_ids.update(filters.knowledge_base_ids)

        if combined_kb_ids:
            conditions.append(DocumentChunk.knowledge_base_id.in_(list(combined_kb_ids)))

        # 2. Merge document_ids
        combined_doc_ids: set[str] = set()
        if document_ids:
            combined_doc_ids.update(document_ids)
        if filters and filters.document_ids:
            combined_doc_ids.update(filters.document_ids)

        if combined_doc_ids:
            conditions.append(DocumentChunk.document_id.in_(list(combined_doc_ids)))

        # 3. Document version IDs filter
        if filters and filters.document_version_ids:
            conditions.append(DocumentChunk.document_version_id.in_(filters.document_version_ids))

        # 4. Scope to active current version of READY documents (exclude ARCHIVED, FAILED, DELETED)
        # We construct a subquery on active document versions
        active_version_subquery = (
            select(DocumentVersion.id)
            .join(Document, DocumentVersion.document_id == Document.id)
            .where(
                and_(
                    Document.organization_id == organization_id,
                    Document.status == DocumentStatus.READY,
                    Document.deleted_at.is_(None),
                    DocumentVersion.version_number == Document.current_version,
                )
            )
            .scalar_subquery()
        )

        conditions.append(DocumentChunk.document_version_id.in_(active_version_subquery))

        return conditions
