import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.investigation import InvestigationJob, InvestigationStatus
from app.models.worker import WorkerHeartbeat
from app.schemas.health import DependencyStatus, ReadinessResponse, WorkerStatus

logger = logging.getLogger("app.services.health")


class HealthService:
    """Service responsible for infrastructure and system health verifications."""

    @staticmethod
    async def check_infrastructure(session: AsyncSession) -> tuple[bool, str, str]:
        """Verify connectivity to PostgreSQL and check pgvector extension availability.

        Returns:
            (is_ready: bool, db_status: str, vector_status: str)
        """
        readiness = await HealthService.check_full_readiness(session)
        is_ready = readiness.status in ("ready", "degraded") and readiness.database == "ok"
        return is_ready, readiness.database, readiness.vector_store

    @staticmethod
    async def check_full_readiness(
        session: AsyncSession,
        timeout_seconds: float = 2.0,
    ) -> ReadinessResponse:
        """Evaluate full operational readiness with bounded timeouts.

        Never leaks secrets, internal endpoints, or full exception traces.
        """
        settings = get_settings()
        now = datetime.now(UTC)
        deps: dict[str, DependencyStatus] = {}
        db_status = "error"
        vector_status = "error"
        db_latency_ms: float | None = None

        # 1. Database Liveness & Latency (Mandatory)
        start_time = time.perf_counter()
        try:
            db_res = await asyncio.wait_for(
                session.execute(text("SELECT 1")),
                timeout=timeout_seconds,
            )
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            db_latency_ms = elapsed_ms
            if db_res.scalar() == 1:
                db_status = "ok"
                deps["database"] = DependencyStatus(
                    status="ok",
                    mandatory=True,
                    latency_ms=elapsed_ms,
                    message="Relational persistence accessible.",
                )
            else:
                db_status = "error"
                deps["database"] = DependencyStatus(
                    status="error",
                    mandatory=True,
                    latency_ms=elapsed_ms,
                    message="Unexpected non-one scalar returned by database probe.",
                )
        except TimeoutError:
            logger.error("Database readiness check timed out after %.2fs", timeout_seconds)
            db_status = "error"
            deps["database"] = DependencyStatus(
                status="error",
                mandatory=True,
                latency_ms=round(timeout_seconds * 1000.0, 2),
                message="Database connection timed out.",
            )
        except Exception as exc:
            logger.error("Database readiness check failed: %s", str(exc))
            db_status = "error"
            deps["database"] = DependencyStatus(
                status="error",
                mandatory=True,
                latency_ms=None,
                message="Database query failed.",
            )

        # 2. Vector Store Extension (Optional / Dialect-Aware)
        if db_status == "ok":
            try:
                bind = session.bind
                dialect_name = bind.dialect.name if bind else ""

                if dialect_name == "postgresql":
                    vec_res = await asyncio.wait_for(
                        session.execute(
                            text("SELECT 1 FROM pg_extension WHERE extname = 'vector';")
                        ),
                        timeout=timeout_seconds,
                    )
                    if vec_res.scalar() == 1:
                        vector_status = "ok"
                        deps["vector_store"] = DependencyStatus(
                            status="ok",
                            mandatory=False,
                            message="pgvector extension enabled.",
                        )
                    else:
                        vector_status = "disabled"
                        deps["vector_store"] = DependencyStatus(
                            status="disabled",
                            mandatory=False,
                            message="pgvector extension not installed or disabled.",
                        )
                else:
                    vector_status = "ok"
                    deps["vector_store"] = DependencyStatus(
                        status="not_applicable",
                        mandatory=False,
                        message=f"Vector extension check skipped on dialect '{dialect_name}'.",
                    )
            except Exception as exc:
                logger.warning("Vector store check encountered issue: %s", str(exc))
                vector_status = "error"
                deps["vector_store"] = DependencyStatus(
                    status="error",
                    mandatory=False,
                    message="Vector extension lookup failed.",
                )
        else:
            vector_status = "error"
            deps["vector_store"] = DependencyStatus(
                status="error",
                mandatory=False,
                message="Vector store unreachable due to database connection error.",
            )

        # 3. Background Investigation Worker Status
        worker_info = WorkerStatus(status="unmonitored")
        if db_status == "ok":
            try:
                # Check most recent worker heartbeat
                hb_stmt = (
                    select(WorkerHeartbeat)
                    .where(WorkerHeartbeat.worker_type == "investigation_worker")
                    .order_by(WorkerHeartbeat.last_heartbeat_at.desc())
                    .limit(1)
                )
                hb_result = await session.execute(hb_stmt)
                recent_hb = hb_result.scalar_one_or_none()

                # Query active and stale investigation jobs
                active_stmt = select(func.count(InvestigationJob.id)).where(
                    InvestigationJob.status == InvestigationStatus.RUNNING.value
                )
                active_count = (await session.execute(active_stmt)).scalar() or 0

                cutoff = now - timedelta(seconds=settings.INVESTIGATION_STALE_RUNNING_SECONDS)
                stale_stmt = select(func.count(InvestigationJob.id)).where(
                    InvestigationJob.status == InvestigationStatus.RUNNING.value,
                    InvestigationJob.started_at < cutoff,
                )
                stale_count = (await session.execute(stale_stmt)).scalar() or 0

                if recent_hb is not None:
                    hb_cutoff = now - timedelta(seconds=120)  # 2 minute threshold
                    last_hb = recent_hb.last_heartbeat_at
                    if last_hb and last_hb.tzinfo is None:
                        last_hb = last_hb.replace(tzinfo=UTC)
                    if last_hb and last_hb >= hb_cutoff:
                        worker_status_str = "active"
                    else:
                        worker_status_str = "stale"
                    worker_info = WorkerStatus(
                        status=worker_status_str,
                        last_heartbeat_at=last_hb,
                        active_jobs_count=active_count,
                        stale_jobs_count=stale_count,
                    )
                else:
                    worker_info = WorkerStatus(
                        status="idle" if active_count == 0 else "unmonitored",
                        last_heartbeat_at=None,
                        active_jobs_count=active_count,
                        stale_jobs_count=stale_count,
                    )
            except Exception as exc:
                logger.debug("Worker heartbeat query skipped or table not initialized: %s", exc)
                worker_info = WorkerStatus(status="unknown")

        # Determine overall readiness status
        if db_status != "ok" or (vector_status in ("disabled", "error") and dialect_name == "postgresql"):
            overall_status = "unhealthy"
        elif vector_status in ("disabled", "error") or worker_info.status == "stale":
            overall_status = "degraded"
        else:
            overall_status = "ready"

        return ReadinessResponse(
            status=overall_status,
            database=db_status,
            vector_store=vector_status,
            dependencies=deps,
            worker=worker_info,
            check_duration_ms=round((time.perf_counter() - start_time) * 1000.0, 2),
            timestamp=now,
        )

    @staticmethod
    async def record_worker_heartbeat(
        session: AsyncSession,
        worker_id: str,
        worker_type: str = "investigation_worker",
        status: str = "active",
        completed_jobs_delta: int = 0,
        metadata: dict | None = None,
    ) -> WorkerHeartbeat:
        """Record or update durable heartbeat for a worker instance."""
        now = datetime.now(UTC)
        stmt = select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing is not None:
            existing.last_heartbeat_at = now
            existing.status = status
            existing.completed_jobs_count += completed_jobs_delta
            if metadata:
                existing.worker_metadata = metadata
            await session.commit()
            return existing
        else:
            new_hb = WorkerHeartbeat(
                worker_id=worker_id,
                worker_type=worker_type,
                status=status,
                last_heartbeat_at=now,
                started_at=now,
                completed_jobs_count=completed_jobs_delta,
                worker_metadata=metadata or {},
            )
            session.add(new_hb)
            await session.commit()
            await session.refresh(new_hb)
            return new_hb

    @staticmethod
    async def check_worker_status(session: AsyncSession) -> WorkerStatus:
        """Inspect background investigation worker operational state."""
        readiness = await HealthService.check_full_readiness(session)
        return readiness.worker or WorkerStatus(status="unknown")
