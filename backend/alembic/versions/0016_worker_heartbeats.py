"""Add worker heartbeats table for operational readiness (Milestone 6).

Revision ID: 0016_worker_heartbeats
Revises: 0015_remediation_approval_and_audit
Create Date: 2026-10-11 00:00:00.000000

Forward-only migration for TracePilot Milestone 6:
- Create ``worker_heartbeats`` for monitoring investigation worker liveness and lag.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_worker_heartbeats"
down_revision: str | None = "0015_remediation_approval_and_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_col = (
        postgresql.JSONB(astext_type=sa.Text())
        .with_variant(sa.JSON(), "sqlite")
    )

    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("worker_id", sa.String(length=100), nullable=False, unique=True),
        sa.Column(
            "worker_type",
            sa.String(length=50),
            nullable=False,
            server_default="investigation_worker",
        ),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "completed_jobs_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "worker_metadata",
            json_col,
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_worker_heartbeats_worker_id",
        "worker_heartbeats",
        ["worker_id"],
        unique=True,
    )
    op.create_index(
        "ix_worker_heartbeats_worker_type",
        "worker_heartbeats",
        ["worker_type"],
        unique=False,
    )
    op.create_index(
        "ix_worker_heartbeats_last_heartbeat_at",
        "worker_heartbeats",
        ["last_heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_worker_heartbeats_last_heartbeat_at", table_name="worker_heartbeats")
    op.drop_index("ix_worker_heartbeats_worker_type", table_name="worker_heartbeats")
    op.drop_index("ix_worker_heartbeats_worker_id", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
