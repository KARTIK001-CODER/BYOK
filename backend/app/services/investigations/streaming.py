"""Real-time Server-Sent Events (SSE) streaming for TracePilot investigation jobs.

PostgreSQL remains the durable source of truth. SSE is strictly a real-time
observation/delivery mechanism:
- Disconnecting clients do not cancel or alter the investigation job.
- Reconnecting clients receive the current authoritative state from PostgreSQL.
- Short-lived DB sessions are used per poll cycle to prevent holding open
  transactions or exhausting database connection pools.
- Closes cleanly when the job reaches a terminal state (completed, failed, cancelled).
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.investigation import InvestigationJob, InvestigationStatus
from app.services.investigations.service import InvestigationService

logger = logging.getLogger("app.services.investigations.streaming")


class InvestigationEventType(enum.StrEnum):
    CONNECTED = "investigation.connected"
    SNAPSHOT = "investigation.snapshot"
    PROGRESS = "investigation.progress"
    COMPLETED = "investigation.completed"
    FAILED = "investigation.failed"
    CANCELLED = "investigation.cancelled"


def _format_datetime(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def format_sse_event(event_name: str, data: dict[str, Any]) -> str:
    """Format a dictionary payload as a valid Server-Sent Event."""
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n"


def format_heartbeat() -> str:
    """Format a keepalive SSE comment."""
    return ": heartbeat\n\n"


def build_connected_payload(job: InvestigationJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "incident_id": job.incident_id,
        "status": job.status,
        "connected_at": datetime.now(UTC).isoformat(),
    }


def build_snapshot_payload(job: InvestigationJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "incident_id": job.incident_id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "attempt_count": job.attempt_count,
        "provider": job.provider,
        "model": job.model,
        "result_summary": job.result_summary,
        "error_category": job.error_category,
        "error_summary": job.error_summary,
        "updated_at": _format_datetime(job.updated_at),
    }


def build_progress_payload(job: InvestigationJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "incident_id": job.incident_id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "updated_at": _format_datetime(job.updated_at),
    }


def build_completed_payload(job: InvestigationJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "incident_id": job.incident_id,
        "status": InvestigationStatus.COMPLETED.value,
        "stage": "completed",
        "progress": 100,
        "result_summary": job.result_summary,
        "completed_at": _format_datetime(job.completed_at) or datetime.now(UTC).isoformat(),
    }


def build_failed_payload(job: InvestigationJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "incident_id": job.incident_id,
        "status": InvestigationStatus.FAILED.value,
        "stage": "failed",
        "progress": job.progress,
        "error_category": job.error_category,
        "error_summary": job.error_summary,
        "updated_at": _format_datetime(job.updated_at) or datetime.now(UTC).isoformat(),
    }


def build_cancelled_payload(job: InvestigationJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "incident_id": job.incident_id,
        "status": InvestigationStatus.CANCELLED.value,
        "stage": "cancelled",
        "progress": job.progress,
        "updated_at": _format_datetime(job.updated_at) or datetime.now(UTC).isoformat(),
    }


async def stream_investigation_events(
    request: Request,
    job_id: str,
    organization_id: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    poll_interval: float | None = None,
    heartbeat_interval: float | None = None,
    timeout_seconds: float | None = None,
) -> AsyncGenerator[str, None]:
    """Yield Server-Sent Events observing an investigation job's lifecycle.

    Session lifecycle:
    Short-lived async sessions are acquired and released on each check to guarantee
    zero open database connections while sleeping.
    """
    settings = get_settings()
    actual_poll = (
        poll_interval if poll_interval is not None else settings.INVESTIGATION_SSE_POLL_INTERVAL
    )
    actual_heartbeat = (
        heartbeat_interval
        if heartbeat_interval is not None
        else settings.INVESTIGATION_SSE_HEARTBEAT_INTERVAL
    )
    actual_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.INVESTIGATION_SSE_TIMEOUT_SECONDS
    )

    factory = session_factory if session_factory is not None else get_session_factory()

    # 1. Load initial state
    try:
        async with factory() as session:
            job = await InvestigationService.get_job(session, job_id, organization_id)
    except Exception as exc:
        logger.warning(
            "Initial job lookup failed during SSE stream initialization for job %s: %s",
            job_id,
            type(exc).__name__,
        )
        return

    if job is None:
        return

    # 2. Emit initial connection and snapshot events
    yield format_sse_event(InvestigationEventType.CONNECTED, build_connected_payload(job))
    yield format_sse_event(InvestigationEventType.SNAPSHOT, build_snapshot_payload(job))

    # 3. Check if job is already in a terminal state
    if job.status == InvestigationStatus.COMPLETED.value:
        yield format_sse_event(InvestigationEventType.COMPLETED, build_completed_payload(job))
        return
    elif job.status == InvestigationStatus.FAILED.value:
        yield format_sse_event(InvestigationEventType.FAILED, build_failed_payload(job))
        return
    elif job.status == InvestigationStatus.CANCELLED.value:
        yield format_sse_event(InvestigationEventType.CANCELLED, build_cancelled_payload(job))
        return

    # 4. State tracking for change detection
    last_status = job.status
    last_stage = job.stage
    last_progress = job.progress
    last_error_category = job.error_category

    start_time = time.monotonic()
    last_heartbeat_time = time.monotonic()

    # 5. Main streaming loop
    try:
        while True:
            # Check for client disconnect
            if await request.is_disconnected():
                logger.debug("Client disconnected from SSE stream for job %s", job_id)
                break

            # Check timeout safety cap
            if time.monotonic() - start_time >= actual_timeout:
                logger.info("SSE stream reached timeout limit for job %s", job_id)
                break

            await asyncio.sleep(actual_poll)

            if await request.is_disconnected():
                logger.debug("Client disconnected after sleep for job %s", job_id)
                break

            # Poll database with short-lived session
            try:
                async with factory() as session:
                    fresh_job = await InvestigationService.get_job(session, job_id, organization_id)

            except Exception as exc:
                logger.warning(
                    "Error querying job %s during SSE polling: %s", job_id, type(exc).__name__
                )
                continue

            if fresh_job is None:
                # Job was removed/deleted mid-flight
                break

            state_changed = (
                fresh_job.status != last_status
                or fresh_job.stage != last_stage
                or fresh_job.progress != last_progress
                or fresh_job.error_category != last_error_category
            )

            if state_changed:
                last_status = fresh_job.status
                last_stage = fresh_job.stage
                last_progress = fresh_job.progress
                last_error_category = fresh_job.error_category

                if fresh_job.status == InvestigationStatus.COMPLETED.value:
                    yield format_sse_event(
                        InvestigationEventType.COMPLETED, build_completed_payload(fresh_job)
                    )
                    break
                elif fresh_job.status == InvestigationStatus.FAILED.value:
                    yield format_sse_event(
                        InvestigationEventType.FAILED, build_failed_payload(fresh_job)
                    )
                    break
                elif fresh_job.status == InvestigationStatus.CANCELLED.value:
                    yield format_sse_event(
                        InvestigationEventType.CANCELLED, build_cancelled_payload(fresh_job)
                    )
                    break
                else:
                    yield format_sse_event(
                        InvestigationEventType.PROGRESS, build_progress_payload(fresh_job)
                    )
            else:
                # Heartbeat check to keep connection alive
                now = time.monotonic()
                if now - last_heartbeat_time >= actual_heartbeat:
                    yield format_heartbeat()
                    last_heartbeat_time = now

    except asyncio.CancelledError:
        logger.debug("SSE stream connection cancelled for job %s", job_id)
    except Exception as exc:
        logger.warning("Unexpected error in SSE stream for job %s: %s", job_id, type(exc).__name__)
