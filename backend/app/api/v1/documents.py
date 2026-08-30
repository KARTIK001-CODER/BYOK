from fastapi import (
    APIRouter,
    Depends,
    File,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ROLE_HIERARCHY,
    get_current_active_user,
    get_document_or_404,
    get_knowledge_base_or_404,
)
from app.core.exceptions import ForbiddenException
from app.db.session import get_db
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.documents import (
    DocumentResponse,
    DocumentUpdate,
    DocumentUploadResponse,
    DocumentVersionResponse,
)
from app.services.documents.service import DocumentService

router = APIRouter(tags=["Documents"])


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Document",
    description="Uploads and stores a new document into a Knowledge Base.",
)
async def upload_document(
    file: UploadFile = File(..., description="File to upload (PDF, TXT, MD, DOCX)"),
    kb_and_membership: tuple[KnowledgeBase, OrganizationMembership] = Depends(
        get_knowledge_base_or_404
    ),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    kb, membership = kb_and_membership

    # RBAC: MEMBER or above can upload
    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    if user_level < ROLE_HIERARCHY[OrganizationRole.MEMBER]:
        raise ForbiddenException(message="Access denied: Membership required to upload documents.")

    content = await file.read()

    doc, version = await DocumentService.upload_document(
        session=session,
        kb=kb,
        organization_id=kb.organization_id,
        user_id=current_user.id,
        original_filename=file.filename or "unnamed_document",
        content=content,
        content_type=file.content_type,
    )

    return DocumentUploadResponse(
        document=DocumentResponse.model_validate(doc),
        version=DocumentVersionResponse.model_validate(version),
        message="Document uploaded successfully.",
    )


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    response_model=PaginatedResponse[DocumentResponse],
    summary="List Documents in Knowledge Base",
    description="Lists documents with pagination, sorting, and status filtering.",
)
async def list_documents(
    kb_and_membership: tuple[KnowledgeBase, OrganizationMembership] = Depends(
        get_knowledge_base_or_404
    ),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    status_filter: DocumentStatus | None = Query(
        None, alias="status", description="Filter by document status"
    ),
    sort_by: str = Query(
        "created_at", description="Sort by field: created_at, updated_at, name, file_size"
    ),
    order: str = Query("desc", description="Sort order: asc, desc"),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[DocumentResponse]:
    kb, membership = kb_and_membership

    items, total = await DocumentService.list_documents(
        session=session,
        kb_id=kb.id,
        organization_id=membership.organization_id,
        limit=limit,
        offset=offset,
        status=status_filter,
        sort_by=sort_by,
        order=order,
    )

    return PaginatedResponse(
        items=[DocumentResponse.model_validate(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentResponse,
    summary="Get Document Details",
    description="Retrieves document metadata by ID.",
)
async def get_document(
    doc_and_membership: tuple[Document, OrganizationMembership] = Depends(get_document_or_404),
) -> DocumentResponse:
    doc, _ = doc_and_membership
    return DocumentResponse.model_validate(doc)


@router.patch(
    "/documents/{document_id}",
    response_model=DocumentResponse,
    summary="Update Document",
    description="Updates document metadata or archives document (requires ADMIN or OWNER).",
)
async def update_document(
    payload: DocumentUpdate,
    doc_and_membership: tuple[Document, OrganizationMembership] = Depends(get_document_or_404),
    session: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    doc, membership = doc_and_membership

    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    if user_level < ROLE_HIERARCHY[OrganizationRole.ADMIN]:
        raise ForbiddenException(
            message="Insufficient permissions: Updating document requires ADMIN or OWNER role."
        )

    updated_doc = await DocumentService.update_document(
        session=session,
        document=doc,
        name=payload.name,
        status=payload.status,
    )
    return DocumentResponse.model_validate(updated_doc)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Document",
    description="Soft-deletes document metadata (requires ADMIN or OWNER).",
)
async def delete_document(
    doc_and_membership: tuple[Document, OrganizationMembership] = Depends(get_document_or_404),
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    doc, membership = doc_and_membership

    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    if user_level < ROLE_HIERARCHY[OrganizationRole.ADMIN]:
        raise ForbiddenException(
            message="Insufficient permissions: Deleting document requires ADMIN or OWNER role."
        )

    await DocumentService.delete_document(session=session, document=doc)
    return {"message": "Document deleted successfully."}
