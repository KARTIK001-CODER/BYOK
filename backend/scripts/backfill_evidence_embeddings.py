"""Operational CLI script to backfill vector embeddings for evidence events.

Idempotent, resumable, tenant-safe batch backfill of evidence_events using FastEmbed pgvector.

Usage::

    cd backend
    python scripts/backfill_evidence_embeddings.py --dry-run
    python scripts/backfill_evidence_embeddings.py --batch-size 50
    python scripts/backfill_evidence_embeddings.py --org-id <uuid> --incident-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import close_db_engine, get_session_factory  # noqa: E402
from app.services.investigations.backfill import EvidenceEmbeddingBackfillService  # noqa: E402

logger = logging.getLogger("backfill_evidence_embeddings")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill vector embeddings for TracePilot evidence events."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Batch size for embedding generation (default: 50).",
    )
    parser.add_argument(
        "--org-id",
        type=str,
        default=None,
        help="Filter backfill to a specific organization ID.",
    )
    parser.add_argument(
        "--incident-id",
        type=str,
        default=None,
        help="Filter backfill to a specific incident ID.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect eligible events without generating or saving embeddings.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-embedding of events that already have an embedding.",
    )
    return parser.parse_args()


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args()
    factory = get_session_factory()

    logger.info(
        "Starting evidence embeddings backfill (dry_run=%s, batch_size=%d, org=%s, incident=%s, force=%s)",
        args.dry_run,
        args.batch_size,
        args.org_id,
        args.incident_id,
        args.force,
    )

    try:
        async with factory() as session:
            stats = await EvidenceEmbeddingBackfillService.backfill(
                session=session,
                batch_size=args.batch_size,
                organization_id=args.org_id,
                incident_id=args.incident_id,
                dry_run=args.dry_run,
                force_reembed=args.force,
            )

        print("=" * 60)
        print("Backfill Summary:")
        print(f"  Dry Run:          {stats.dry_run}")
        print(f"  Total Eligible:   {stats.total_eligible}")
        print(f"  Processed:        {stats.processed}")
        print(f"  Embedded:         {stats.embedded}")
        print(f"  Failed:           {stats.failed}")
        print(f"  Batches:          {stats.batch_count}")
        print("=" * 60)
    finally:
        await close_db_engine()


if __name__ == "__main__":
    asyncio.run(main())
