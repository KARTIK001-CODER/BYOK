import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app.services.health")


class HealthService:
    """Service responsible for infrastructure and system health verifications."""

    @staticmethod
    async def check_infrastructure(session: AsyncSession) -> tuple[bool, str, str]:
        """
        Verify connectivity to PostgreSQL and check pgvector extension availability.

        Returns:
            (is_ready: bool, db_status: str, vector_status: str)
        """
        db_status = "error"
        vector_status = "error"
        is_ready = False

        try:
            # 1. Check basic database connectivity
            db_res = await session.execute(text("SELECT 1"))
            if db_res.scalar() == 1:
                db_status = "ok"

            # 2. Check pgvector extension availability
            bind = session.bind
            dialect_name = bind.dialect.name if bind else ""

            if dialect_name == "postgresql":
                vec_res = await session.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector';")
                )
                if vec_res.scalar() == 1:
                    vector_status = "ok"
                else:
                    logger.warning(
                        "PostgreSQL connection active, but pgvector extension is disabled."
                    )
                    vector_status = "disabled"
            else:
                # Test/non-postgres environment (e.g. SQLite for unit tests)
                vector_status = "ok"

            is_ready = (db_status == "ok") and (vector_status == "ok")

        except Exception as exc:
            logger.error("Infrastructure health check failure: %s", str(exc))
            db_status = "error"
            vector_status = "error"
            is_ready = False

        return is_ready, db_status, vector_status
