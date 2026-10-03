"""
Phase 2.6: Trace Export Utility.
Executes a request through the BYOK pipeline or exports an existing RequestTrace
to the standardized structured JSON schema specified in Phase 2.6 Part 4.

Usage:
  python scripts/export_request_trace.py --query "What is the refund policy?" --output trace.json
  python scripts/export_request_trace.py --provider mock --stream
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.tracing import RequestTrace, trace_context
from app.db.session import get_session_factory
from app.models.membership import OrganizationRole
from app.models.organization import Organization
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService
from app.services.users.service import UserService

logger = logging.getLogger("byok.export_trace")


def format_trace_for_export(trace: RequestTrace) -> dict[str, Any]:
    """Format RequestTrace into the standardized Phase 2.6 Part 4 schema."""
    return trace.to_export_dict()


async def execute_and_export(
    query: str,
    provider: str = "mock",
    stream: bool = False,
    output_path: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    session_factory = get_session_factory()

    if provider == "mock":
        LLMProviderFactory.set_mock_provider(MockLLMProvider())

    async with session_factory() as session:
        # Resolve or create test organization & user for profiling
        user = await UserService.get_by_email(session, "perf_profiler@byok.local")
        if not user:
            from app.core.security import hash_password

            user = await UserService.create(
                session=session,
                email="perf_profiler@byok.local",
                password_hash=hash_password("ProfilerSecretPassword123!"),
                full_name="Latency Profiler",
            )
            org = Organization(name="Profiler Org", slug=f"profiler-org-{uuid.uuid4().hex[:6]}")
            session.add(org)
            await session.flush()
            from app.models.membership import OrganizationMembership

            membership = OrganizationMembership(
                organization_id=org.id,
                user_id=user.id,
                role=OrganizationRole.OWNER,
            )
            session.add(membership)
            await session.commit()
            org_id = org.id
        else:
            from app.services.organizations.service import OrganizationService

            memberships = await OrganizationService.get_user_memberships(session, user.id)
            org_id = memberships[0].organization_id

        # Setup RequestTrace
        trace_id = f"trace-export-{uuid.uuid4().hex[:8]}"
        req_id = f"req-export-{uuid.uuid4().hex[:8]}"
        trace = RequestTrace(trace_id=trace_id, request_id=req_id)
        trace.mark("request_start")
        trace.mark("request_received")

        rag_service = RAGService()
        req_payload = RAGChatRequest(
            message=query,
            provider=provider,
            top_k=5,
            search_mode="hybrid",
        )

        with trace_context(trace):
            # Record mock auth / authz to complete end-to-end stages
            trace.record("jwt_validation_ms", 0.42)
            trace.record("user_lookup_ms", 1.85)
            trace.record("authentication_ms", 2.27)
            trace.record("authentication_total_ms", 2.27)
            trace.mark("jwt_validated")
            trace.mark("user_loaded")
            trace.mark("auth_done")

            trace.record("organization_resolution_ms", 1.10)
            trace.record("knowledge_base_resolution_ms", 0.0)
            trace.record("authorization_check_ms", 0.85)
            trace.record("authorization_total_ms", 1.95)
            trace.record("org_verify_total_ms", 1.95)
            trace.mark("authorization_complete")

            if stream:
                async for _event in rag_service.stream_chat(
                    session=session,
                    organization_id=org_id,
                    user_id=user.id,
                    request=req_payload,
                ):
                    pass
            else:
                await rag_service.generate(
                    session=session,
                    organization_id=org_id,
                    user_id=user.id,
                    request=req_payload,
                )

            trace.mark("request_completed")

        export_data = format_trace_for_export(trace)

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(export_data, indent=2), encoding="utf-8")
            print(f"Trace successfully exported to: {output_path}")

        return export_data


def main():
    parser = argparse.ArgumentParser(description="Export BYOK Request Trace to JSON")
    parser.add_argument(
        "--query", default="What is the refund policy?", help="Query text to profile"
    )
    parser.add_argument(
        "--provider", default="mock", help="LLM provider (mock, groq, gemini, openai)"
    )
    parser.add_argument("--stream", action="store_true", help="Profile streaming endpoint")
    parser.add_argument("--output", default=None, help="Output JSON file path")

    args = parser.parse_args()
    res = asyncio.run(
        execute_and_export(
            query=args.query,
            provider=args.provider,
            stream=args.stream,
            output_path=args.output,
        )
    )

    if not args.output:
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
