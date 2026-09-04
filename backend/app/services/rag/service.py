import contextlib
import json
import logging
import time
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.document import Document
from app.models.message import MessageRole
from app.services.llm.base import LLMRequest
from app.services.llm.errors import LLMException
from app.services.llm.factory import LLMProviderFactory
from app.services.rag.citations import CitationBuilder
from app.services.rag.context import ContextBuilder
from app.services.rag.conversations import ConversationService
from app.services.rag.prompt import PromptBuilder
from app.services.rag.schemas import (
    RAGChatRequest,
    RAGChatResponse,
    RetrievalSummary,
)
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService
from app.services.retrieval.arxiv_client import ArxivClient

logger = logging.getLogger("app.services.rag.service")


class RAGService:
    """Core service orchestrating Hybrid Retrieval, Context Assembly, and Generation."""

    def __init__(
        self,
        context_builder: ContextBuilder | None = None,
        prompt_builder: PromptBuilder | None = None,
        citation_builder: CitationBuilder | None = None,
    ) -> None:
        self.context_builder = context_builder or ContextBuilder()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.citation_builder = citation_builder or CitationBuilder()

    @staticmethod
    async def _get_document_names(
        session: AsyncSession,
        organization_id: str,
        document_ids: list[str],
    ) -> dict[str, str]:
        """Fetch human-readable document titles for citation display."""
        if not document_ids:
            return {}
        stmt = select(Document.id, Document.name).where(
            Document.organization_id == organization_id,
            Document.id.in_(document_ids),
        )
        res = await session.execute(stmt)
        return dict(res.all())

    async def generate(
        self,
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        request: RAGChatRequest,
    ) -> RAGChatResponse:
        """
        Execute synchronous end-to-end RAG generation.

        Returns RAGChatResponse with generated answer, validated citations, and metadata.
        """
        total_start = time.perf_counter()
        settings = get_settings()

        # 1. Fetch or create conversation
        conv = await ConversationService.get_or_create_conversation(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            conversation_id=request.conversation_id,
            initial_query=request.message,
            knowledge_base_ids=request.knowledge_base_ids,
        )

        # 2. Persist user message
        user_msg = await ConversationService.add_message(
            session=session,
            conversation_id=conv.id,
            role=MessageRole.USER,
            content=request.message,
        )

        # 3. Retrieve context chunks from Phase 6 RetrievalService
        kb_scope = request.knowledge_base_ids or conv.knowledge_base_ids
        retrieval_req = RetrievalRequest(
            query=request.message,
            knowledge_base_ids=kb_scope,
            top_k=request.top_k,
            candidate_k=max(request.top_k * 4, 30),
            search_mode=SearchMode(request.search_mode),
        )

        retrieval_start = time.perf_counter()
        retrieval_resp = await RetrievalService.search(
            session=session,
            organization_id=organization_id,
            request=retrieval_req,
        )
        
        # Fallback to Arxiv search if no local results found
        if not retrieval_resp.results:
            arxiv_results = await ArxivClient.search(
                query=request.message,
                top_k=request.top_k,
                organization_id=organization_id
            )
            retrieval_resp.results = arxiv_results
            
        retrieval_latency_ms = (time.perf_counter() - retrieval_start) * 1000.0

        # 4. Fetch document names for citations
        doc_ids = list({r.document_id for r in retrieval_resp.results if not r.document_id.startswith("arxiv_")})
        doc_names = await self._get_document_names(session, organization_id, doc_ids)

        # 5. Assemble context with provenance and token budgeting
        assembled_context = self.context_builder.assemble(
            retrieval_results=retrieval_resp.results,
            document_names=doc_names,
        )

        # 6. Load recent conversation history (excluding current user message)
        all_messages = await ConversationService.get_recent_messages(
            session=session,
            conversation_id=conv.id,
            limit=settings.MAX_HISTORY_MESSAGES + 1,
        )
        history = [m for m in all_messages if m.id != user_msg.id]

        # 7. Construct LLM prompt messages
        llm_messages = self.prompt_builder.build_messages(
            query=request.message,
            context=assembled_context,
            history=history,
            max_history=settings.MAX_HISTORY_MESSAGES,
        )

        # 8. Resolve provider and model via factory
        provider, model_name = LLMProviderFactory.create(
            provider=request.provider,
            model=request.model,
        )

        # Release DB connection before network-bound LLM call so the pooled
        # Neon connection is not held idle during the external HTTP request.
        with contextlib.suppress(Exception):
            await session.commit()

        # 9. Invoke LLM generation
        llm_req = LLMRequest(
            provider=provider.name,
            model=model_name,
            messages=llm_messages,
            temperature=request.temperature,
            max_tokens=settings.MAX_GENERATION_TOKENS,
            stream=False,
        )

        gen_start = time.perf_counter()
        llm_resp = await provider.generate(llm_req)
        gen_latency_ms = (time.perf_counter() - gen_start) * 1000.0

        # 10. Extract & validate citations
        citations = self.citation_builder.build_citations(
            answer_text=llm_resp.content,
            context=assembled_context,
        )

        # 11. Persist assistant message with metadata
        retrieval_summary = RetrievalSummary(
            search_mode=request.search_mode,
            result_count=len(retrieval_resp.results),
            latency_ms=round(retrieval_latency_ms, 2),
        )

        usage_dict = None
        if llm_resp.usage:
            usage_dict = {
                "prompt_tokens": llm_resp.usage.prompt_tokens,
                "completion_tokens": llm_resp.usage.completion_tokens,
                "total_tokens": llm_resp.usage.total_tokens,
            }

        total_latency_ms = (time.perf_counter() - total_start) * 1000.0

        assistant_metadata = {
            "provider": provider.name,
            "model": model_name,
            "citations": [c.model_dump() for c in citations],
            "retrieval": retrieval_summary.model_dump(),
            "usage": usage_dict,
            "latency_ms": round(total_latency_ms, 2),
            "generation_latency_ms": round(gen_latency_ms, 2),
            "retrieval_latency_ms": round(retrieval_latency_ms, 2),
        }

        assistant_msg = await ConversationService.add_message(
            session=session,
            conversation_id=conv.id,
            role=MessageRole.ASSISTANT,
            content=llm_resp.content,
            metadata=assistant_metadata,
        )
        await session.commit()
        await session.refresh(assistant_msg)

        return RAGChatResponse(
            conversation_id=conv.id,
            message_id=assistant_msg.id,
            user_message_id=user_msg.id,
            answer=llm_resp.content,
            citations=citations,
            retrieval=retrieval_summary,
            model=model_name,
            provider=provider.name,
            usage=usage_dict,
            latency_ms=round(total_latency_ms, 2),
        )

    async def stream_chat(
        self,
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        request: RAGChatRequest,
    ) -> AsyncGenerator[str, None]:
        """Execute streaming RAG generation yielding Server-Sent Events (SSE)."""
        total_start = time.perf_counter()
        settings = get_settings()

        try:
            # 1. Fetch or create conversation
            conv = await ConversationService.get_or_create_conversation(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=request.conversation_id,
                initial_query=request.message,
                knowledge_base_ids=request.knowledge_base_ids,
            )

            # 2. Persist user message
            user_msg = await ConversationService.add_message(
                session=session,
                conversation_id=conv.id,
                role=MessageRole.USER,
                content=request.message,
            )
            await session.commit()

            # Yield start event
            provider, model_name = LLMProviderFactory.create(
                provider=request.provider,
                model=request.model,
            )
            start_payload = {
                "conversation_id": conv.id,
                "user_message_id": user_msg.id,
                "provider": provider.name,
                "model": model_name,
            }
            yield f"event: start\ndata: {json.dumps(start_payload)}\n\n"

            # 3. Retrieve context chunks
            kb_scope = request.knowledge_base_ids or conv.knowledge_base_ids
            retrieval_req = RetrievalRequest(
                query=request.message,
                knowledge_base_ids=kb_scope,
                top_k=request.top_k,
                candidate_k=max(request.top_k * 4, 30),
                search_mode=SearchMode(request.search_mode),
            )

            retrieval_start = time.perf_counter()
            retrieval_resp = await RetrievalService.search(
                session=session,
                organization_id=organization_id,
                request=retrieval_req,
            )
            
            # Fallback to Arxiv search if no local results found
            if not retrieval_resp.results:
                arxiv_results = await ArxivClient.search(
                    query=request.message,
                    top_k=request.top_k,
                    organization_id=organization_id
                )
                retrieval_resp.results = arxiv_results
                
            retrieval_latency_ms = (time.perf_counter() - retrieval_start) * 1000.0

            retrieval_payload = {
                "search_mode": request.search_mode,
                "result_count": len(retrieval_resp.results),
                "latency_ms": round(retrieval_latency_ms, 2),
            }
            yield f"event: retrieval\ndata: {json.dumps(retrieval_payload)}\n\n"

            # 4. Fetch doc names
            doc_ids = list({r.document_id for r in retrieval_resp.results if not r.document_id.startswith("arxiv_")})
            doc_names = await self._get_document_names(session, organization_id, doc_ids)

            # 5. Assemble context
            assembled_context = self.context_builder.assemble(
                retrieval_results=retrieval_resp.results,
                document_names=doc_names,
            )

            # 6. Load recent history
            all_messages = await ConversationService.get_recent_messages(
                session=session,
                conversation_id=conv.id,
                limit=settings.MAX_HISTORY_MESSAGES + 1,
            )
            history = [m for m in all_messages if m.id != user_msg.id]

            # Release DB connection before long-lived LLM streaming
            with contextlib.suppress(Exception):
                await session.commit()

            # 7. Construct prompt
            llm_messages = self.prompt_builder.build_messages(
                query=request.message,
                context=assembled_context,
                history=history,
                max_history=settings.MAX_HISTORY_MESSAGES,
            )

            # 8. Start streaming tokens from provider
            llm_req = LLMRequest(
                provider=provider.name,
                model=model_name,
                messages=llm_messages,
                temperature=request.temperature,
                max_tokens=settings.MAX_GENERATION_TOKENS,
                stream=True,
            )

            accumulated_tokens: list[str] = []
            final_usage = None
            first_token_time: float | None = None
            stream_start = time.perf_counter()

            async for chunk in provider.stream(llm_req):
                if chunk.delta:
                    if first_token_time is None:
                        first_token_time = (time.perf_counter() - stream_start) * 1000.0
                    accumulated_tokens.append(chunk.delta)
                    yield f"event: token\ndata: {json.dumps({'delta': chunk.delta})}\n\n"
                if chunk.usage:
                    final_usage = chunk.usage

            full_answer = "".join(accumulated_tokens)
            gen_latency_ms = (time.perf_counter() - stream_start) * 1000.0

            # 9. Extract & validate citations
            citations = self.citation_builder.build_citations(
                answer_text=full_answer,
                context=assembled_context,
            )

            for cit in citations:
                yield f"event: citation\ndata: {json.dumps(cit.model_dump())}\n\n"

            # 10. Persist complete response (fresh session to avoid stale pooled connection)
            total_latency_ms = (time.perf_counter() - total_start) * 1000.0
            usage_dict = None
            if final_usage:
                usage_dict = {
                    "prompt_tokens": final_usage.prompt_tokens,
                    "completion_tokens": final_usage.completion_tokens,
                    "total_tokens": final_usage.total_tokens,
                }
            elif full_answer:
                # Estimate token usage if provider omitted usage in stream
                tok_len = max(1, len(full_answer) // 4)
                usage_dict = {
                    "prompt_tokens": assembled_context.estimated_tokens,
                    "completion_tokens": tok_len,
                    "total_tokens": assembled_context.estimated_tokens + tok_len,
                }

            retrieval_summary = RetrievalSummary(
                search_mode=request.search_mode,
                result_count=len(retrieval_resp.results),
                latency_ms=round(retrieval_latency_ms, 2),
            )

            assistant_metadata = {
                "provider": provider.name,
                "model": model_name,
                "citations": [c.model_dump() for c in citations],
                "retrieval": retrieval_summary.model_dump(),
                "usage": usage_dict,
                "latency_ms": round(total_latency_ms, 2),
                "generation_latency_ms": round(gen_latency_ms, 2),
                "retrieval_latency_ms": round(retrieval_latency_ms, 2),
                "time_to_first_token_ms": (
                    round(first_token_time, 2) if first_token_time else None
                ),
            }

            assistant_msg = await ConversationService.add_message(
                session=session,
                conversation_id=conv.id,
                role=MessageRole.ASSISTANT,
                content=full_answer,
                metadata=assistant_metadata,
            )
            await session.commit()
            await session.refresh(assistant_msg)

            # Done event
            done_payload = {
                "message_id": assistant_msg.id,
                "conversation_id": conv.id,
                "latency_ms": round(total_latency_ms, 2),
                "time_to_first_token_ms": round(first_token_time, 2) if first_token_time else None,
                "usage": usage_dict,
            }
            yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"

        except LLMException as exc:
            logger.warning("RAG streaming encountered domain error: [%s] %s", exc.code, exc.message)
            err_data = {"code": exc.code, "message": exc.message}
            yield f"event: error\ndata: {json.dumps(err_data)}\n\n"
        except Exception as exc:
            logger.exception("RAG streaming unexpected failure: %s", exc)
            fallback_err = {
                "code": "GENERATION_FAILED",
                "message": "We couldn't generate an answer. Please try again.",
            }
            yield f"event: error\ndata: {json.dumps(fallback_err)}\n\n"
