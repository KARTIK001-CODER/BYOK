import logging
import time

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ROLE_HIERARCHY, get_current_active_user
from app.core.exceptions import ForbiddenException, ValidationException
from app.core.tracing import get_current_trace
from app.db.session import get_db
from app.models.membership import OrganizationRole
from app.models.user import User
from app.services.knowledge_bases.service import KnowledgeBaseService
from app.services.llm.registry import ModelRegistry, ProviderInfo
from app.services.organizations.service import OrganizationService
from app.services.rag.schemas import RAGChatRequest, RAGChatResponse
from app.services.rag.service import RAGService

logger = logging.getLogger("app.api.chat")

router = APIRouter(prefix="/chat", tags=["Generation Engine & Production RAG"])


async def _resolve_organization_and_verify(
    session: AsyncSession,
    current_user: User,
    x_organization_id: str | None,
    kb_ids: list[str] | None,
) -> str:
    """Resolve target organization ID and ensure caller has at least MEMBER role."""
    trace = get_current_trace()
    t0 = time.perf_counter()

    # -- knowledge_base_resolution when needed
    org_id = x_organization_id
    kb_resolve_ms = 0.0
    if not org_id and kb_ids:
        kb_t0 = time.perf_counter()
        kb = await KnowledgeBaseService.get_by_id(session, kb_ids[0])
        org_id = kb.organization_id
        kb_resolve_ms = (time.perf_counter() - kb_t0) * 1000.0

    # -- organization_resolution
    org_t0 = time.perf_counter()
    if not org_id:
        memberships = await OrganizationService.get_user_memberships(session, current_user.id)
        if not memberships:
            raise ValidationException(message="User does not belong to any organization.")
        org_id = memberships[0].organization_id
    org_resolve_ms = (time.perf_counter() - org_t0) * 1000.0

    # -- authorization (membership + role check)
    authz_t0 = time.perf_counter()
    membership = await OrganizationService.get_membership(session, org_id, current_user.id)
    if membership is None:
        raise ForbiddenException(message="Access denied: You do not belong to this organization.")

    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    if user_level < ROLE_HIERARCHY[OrganizationRole.MEMBER]:
        raise ForbiddenException(
            message="Insufficient permissions: Chat generation requires at least MEMBER role."
        )
    authz_ms = (time.perf_counter() - authz_t0) * 1000.0

    total_ms = (time.perf_counter() - t0) * 1000.0
    if trace:
        trace.record("organization_resolution_ms", org_resolve_ms)
        trace.record("knowledge_base_resolution_ms", kb_resolve_ms)
        trace.record("authorization_ms", authz_ms)
        trace.record("org_verify_total_ms", total_ms)
        trace.mark("org_verify_done")
        logger.debug(
            "org_verify trace=%s total=%.2f ms (org=%.2f kb=%.2f authz=%.2f)",
            trace.trace_id, total_ms, org_resolve_ms, kb_resolve_ms, authz_ms,
        )

    return org_id


@router.post(
    "",
    response_model=RAGChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Synchronous RAG Chat Generation",
    description="Executes hybrid retrieval, token-budgeted context assembly, and LLM answer generation with citations.",
)
async def chat(
    payload: RAGChatRequest,
    x_organization_id: str | None = Header(
        default=None,
        alias="X-Organization-ID",
        description="Target Organization ID for multi-tenant isolation.",
    ),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> RAGChatResponse:
    org_id = await _resolve_organization_and_verify(
        session=session,
        current_user=current_user,
        x_organization_id=x_organization_id,
        kb_ids=payload.knowledge_base_ids,
    )

    rag_service = RAGService()
    return await rag_service.generate(
        session=session,
        organization_id=org_id,
        user_id=current_user.id,
        request=payload,
    )


@router.post(
    "/stream",
    summary="Streaming RAG Chat Generation (SSE)",
    description="Streams Server-Sent Events (SSE) tokens, retrieval telemetry, structured citations, and completion envelope.",
)
async def chat_stream(
    payload: RAGChatRequest,
    x_organization_id: str | None = Header(
        default=None,
        alias="X-Organization-ID",
        description="Target Organization ID for multi-tenant isolation.",
    ),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    org_id = await _resolve_organization_and_verify(
        session=session,
        current_user=current_user,
        x_organization_id=x_organization_id,
        kb_ids=payload.knowledge_base_ids,
    )

    rag_service = RAGService()
    event_generator = rag_service.stream_chat(
        session=session,
        organization_id=org_id,
        user_id=current_user.id,
        request=payload,
    )

    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/models",
    response_model=list[ProviderInfo],
    status_code=status.HTTP_200_OK,
    summary="List Supported LLM Providers and Models",
    description="Returns registry of supported providers, configuration status, and model capabilities.",
)
async def list_models(
    _: User = Depends(get_current_active_user),
) -> list[ProviderInfo]:
    return ModelRegistry.list_providers_with_metadata()
