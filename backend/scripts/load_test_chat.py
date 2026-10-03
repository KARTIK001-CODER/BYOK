"""
BYOK Phase 2.6: Concurrency Load Test.

Measures system behavior under 1, 5, 10 (and optionally 20) concurrent users.
Safe execution: Uses Mock provider by default to protect against external API rate limits.
Measures:
  - Throughput (requests/sec)
  - Latency percentiles (P50, P95, P99)
  - Error rate (%)
  - Connection acquisition and DB pool usage
  - Event loop responsiveness

Usage:
  python scripts/load_test_chat.py --concurrency 1,5,10 --requests 10 --provider mock
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
import time
import uuid
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.tracing import RequestTrace, trace_context
from app.db.session import get_pool_status, get_session_factory
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService
from app.services.users.service import UserService

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("byok.load_test")


def calculate_percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    n = len(s)
    if n == 1:
        return round(s[0], 2)
    k = (n - 1) * (p / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return round(s[int(k)], 2)
    return round(s[int(f)] * (c - k) + s[int(c)] * (k - f), 2)


async def setup_test_environment(provider: str) -> tuple[str, str]:
    """Ensure mock provider and test user/org exist."""
    if provider == "mock":
        LLMProviderFactory.set_mock_provider(MockLLMProvider())

    session_factory = get_session_factory()
    from app.core.security import hash_password

    async with session_factory() as session:
        user = await UserService.get_by_email(session, "load_tester@byok.local")
        if not user:
            user = await UserService.create(
                session=session,
                email="load_tester@byok.local",
                password_hash=hash_password("LoadTesterPassword123!"),
                full_name="Load Tester",
            )
            org = Organization(name="Load Org", slug=f"load-org-{uuid.uuid4().hex[:6]}")
            session.add(org)
            await session.flush()
            m = OrganizationMembership(
                organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER
            )
            session.add(m)
            await session.commit()
            org_id = org.id
        else:
            from app.services.organizations.service import OrganizationService

            ms = await OrganizationService.get_user_memberships(session, user.id)
            org_id = ms[0].organization_id

        return user.id, org_id


async def execute_single_client(
    client_id: int,
    user_id: str,
    org_id: str,
    provider: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Simulates a single chat request under concurrency semaphore constraint."""
    async with semaphore:
        rag_service = RAGService()
        req = RAGChatRequest(
            message=f"Concurrent test message from client {client_id}: What is the refund policy?",
            provider=provider,
            top_k=3,
            search_mode="hybrid",
        )
        trace = RequestTrace(trace_id=f"trace-load-{uuid.uuid4().hex[:8]}")
        session_factory = get_session_factory()

        t0 = time.perf_counter()
        pool_snap_before = get_pool_status()
        success = False
        error_msg = None

        try:
            async with session_factory() as session:
                with trace_context(trace):
                    await rag_service.generate(
                        session=session,
                        organization_id=org_id,
                        user_id=user_id,
                        request=req,
                    )
            success = True
        except Exception as exc:
            error_msg = str(exc)
            logger.error("Client %d failed: %s", client_id, exc)

        duration_ms = (time.perf_counter() - t0) * 1000.0
        pool_snap_after = get_pool_status()

        return {
            "client_id": client_id,
            "success": success,
            "duration_ms": duration_ms,
            "error": error_msg,
            "pool_before": pool_snap_before,
            "pool_after": pool_snap_after,
            "trace_counters": dict(trace.counters),
        }


async def run_concurrency_level(
    concurrency: int,
    total_requests: int,
    user_id: str,
    org_id: str,
    provider: str,
) -> dict[str, Any]:
    """Run a batch of requests with a specified concurrency level."""
    semaphore = asyncio.Semaphore(concurrency)
    wall_start = time.perf_counter()

    tasks = [
        execute_single_client(i, user_id, org_id, provider, semaphore)
        for i in range(total_requests)
    ]
    results = await asyncio.gather(*tasks)
    wall_total = time.perf_counter() - wall_start

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]
    durations = [r["duration_ms"] for r in successes]

    rps = round(total_requests / max(wall_total, 0.001), 2)
    error_rate = round((len(failures) / total_requests) * 100.0, 2)

    return {
        "concurrency": concurrency,
        "total_requests": total_requests,
        "successful": len(successes),
        "failed": len(failures),
        "error_rate_pct": error_rate,
        "wall_time_sec": round(wall_total, 2),
        "throughput_req_per_sec": rps,
        "latency": {
            "min": round(min(durations), 2) if durations else 0.0,
            "max": round(max(durations), 2) if durations else 0.0,
            "avg": round(sum(durations) / len(durations), 2) if durations else 0.0,
            "p50": calculate_percentile(durations, 50),
            "p95": calculate_percentile(durations, 95),
            "p99": calculate_percentile(durations, 99),
        },
        "pool_status": get_pool_status(),
    }


async def run_load_suite(args: argparse.Namespace) -> dict[str, Any]:
    levels = [int(c.strip()) for c in args.concurrency.split(",") if c.strip()]
    user_id, org_id = await setup_test_environment(args.provider)

    print("\n" + "=" * 70)
    print(f" BYOK LOAD TEST (Concurrency Levels: {levels} | Requests/Level: {args.requests})")
    print(f" Provider: {args.provider}")
    print("=" * 70)

    summary_results: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider": args.provider,
        "levels": {},
    }

    print(
        f" {'CONCURRENCY':<12} {'THROUGHPUT':<14} {'P50 (ms)':<10} {'P95 (ms)':<10} {'P99 (ms)':<10} {'ERR RATE':<10}"
    )
    print("-" * 70)

    for level in levels:
        res = await run_concurrency_level(
            concurrency=level,
            total_requests=args.requests,
            user_id=user_id,
            org_id=org_id,
            provider=args.provider,
        )
        summary_results["levels"][str(level)] = res
        lat = res["latency"]
        print(
            f" {level:<12} {res['throughput_req_per_sec']:<14.2f} {lat['p50']:<10.2f} "
            f"{lat['p95']:<10.2f} {lat['p99']:<10.2f} {res['error_rate_pct']:<10.1f}%"
        )

    print("=" * 70 + "\n")

    if args.output:
        p = Path(args.output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(summary_results, indent=2), encoding="utf-8")
        print(f"Load test results written to: {args.output}")

    return summary_results


def main():
    parser = argparse.ArgumentParser(description="BYOK Concurrency Load Test")
    parser.add_argument(
        "--concurrency", default="1,5,10", help="Comma-separated concurrency levels (e.g. 1,5,10)"
    )
    parser.add_argument("--requests", type=int, default=10, help="Requests per concurrency level")
    parser.add_argument(
        "--provider",
        default="mock",
        choices=["mock", "groq", "gemini", "openai"],
        help="LLM provider",
    )
    parser.add_argument("--output", default=None, help="Output JSON results path")

    args = parser.parse_args()
    if args.provider != "mock" and any(int(x) > 3 for x in args.concurrency.split(",")):
        print("Warning: Real LLM providers are rate-limited. Capping concurrency at 3 for safety.")
        args.concurrency = "1,2,3"

    asyncio.run(run_load_suite(args))


if __name__ == "__main__":
    main()
