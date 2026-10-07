"""Durable TracePilot investigation worker.

Claims queued investigation jobs from the database and executes them, so
investigations survive API restarts: any job left behind is durable state,
not memory.

Local startup::

    cd backend
    python scripts/run_investigation_worker.py            # single pass (claim one batch, exit)
    python scripts/run_investigation_worker.py --loop     # poll continuously

Production constraints (documented limitation, no Redis/task framework added):
- Run exactly ONE worker replica (or scope replicas per organization via
  --organization-id). Claiming is atomic (conditional UPDATE), so concurrent
  workers are safe from double-execution, but a single worker keeps
  provider rate-limit behavior predictable.
- The worker needs the same DATABASE_URL and LLM provider keys as the API.
- Jobs stuck in ``running`` longer than INVESTIGATION_STALE_RUNNING_SECONDS
  are re-queued (up to max_attempts) on each pass.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db.session import close_db_engine, get_session_factory  # noqa: E402
from app.services.investigations.engine import execute_claimed_job  # noqa: E402
from app.services.investigations.service import InvestigationService  # noqa: E402

logger = logging.getLogger("investigation_worker")


async def run_once(organization_id: str | None = None) -> int:
    """Reclaim stale jobs, claim and execute queued jobs. Returns jobs completed."""
    settings = get_settings()
    factory = get_session_factory()
    done = 0
    async with factory() as session:
        await InvestigationService.requeue_stale_running(
            session, settings.INVESTIGATION_STALE_RUNNING_SECONDS, organization_id
        )
    while True:
        async with factory() as session:
            job = await InvestigationService.claim_next_queued(session, organization_id)
            if job is None:
                break
            job_id, org_id = job.id, job.organization_id
        # Execute on a fresh session so each job gets its own transaction scope.
        async with factory() as work_session:
            claimed = await InvestigationService.get_job(work_session, job_id, org_id)
            if claimed is None or claimed.status != "running":
                continue
            try:
                finished = await execute_claimed_job(work_session, claimed)
            except Exception:
                # execute_claimed_job is contractually total (it maps every
                # failure to a safe terminal state), so reaching here means
                # the database itself is unreachable. The job stays running
                # and will be reclaimed by stale recovery; never touch the
                # possibly-expired ORM object — log plain IDs only.
                logger.exception("Job %s execution raised outside the engine", job_id)
                break
            logger.info("Job %s finished with status=%s", job_id, finished.status)
            done += 1
    return done


async def run_loop(organization_id: str | None, interval_seconds: int) -> None:
    while True:
        try:
            count = await run_once(organization_id)
            if count:
                logger.info("Worker pass completed %d job(s).", count)
        except Exception:
            logger.exception("Worker pass failed; retrying after interval.")
        await asyncio.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="TracePilot investigation worker.")
    parser.add_argument(
        "--loop", action="store_true", help="Poll continuously instead of one pass."
    )
    parser.add_argument(
        "--interval", type=int, default=10, help="Poll interval seconds for --loop."
    )
    parser.add_argument("--organization-id", default=None, help="Restrict to one organization.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        if args.loop:
            asyncio.run(run_loop(args.organization_id, args.interval))
        else:
            count = asyncio.run(run_once(args.organization_id))
            print(f"Worker pass done: {count} job(s) executed.")
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(close_db_engine())


if __name__ == "__main__":
    main()
