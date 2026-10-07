"""Enforce single active investigation per incident at the database level.

Revision ID: 0011_investigation_single_active
Revises: 0010_investigation_engine
Create Date: 2026-10-06 00:00:00.000000

Forward-only hardening migration for TracePilot Milestone 2.5:

Adds partial unique index ``uq_investigation_jobs_single_active`` on
``investigation_jobs(incident_id)`` restricted to rows with
``status IN ('queued', 'running')``. This is the final safety boundary for
the check-then-insert race in ``InvestigationService.create_job`` when
concurrent requests arrive without an idempotency key (NULL keys never
conflict in ``uq_investigation_jobs_incident_idempotency`` on either
PostgreSQL or SQLite, so the older constraint cannot cover that case).

Terminal states (completed/failed/cancelled) are unconstrained, so explicit
re-investigation after a terminal state keeps working.

NOTE: if the table already contains two active (queued/running) jobs for one
incident, index creation will fail. Resolve (cancel/complete the stale row)
before upgrading in that case.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_investigation_single_active"
down_revision: str | None = "0010_investigation_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_investigation_jobs_single_active",
        "investigation_jobs",
        ["incident_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_investigation_jobs_single_active", table_name="investigation_jobs")
