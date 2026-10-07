"""Add TracePilot investigation engine tables (jobs, hypotheses, evidence links).

Revision ID: 0010_investigation_engine
Revises: 0009_evidence_dedup_idempotency
Create Date: 2026-10-05 00:00:00.000000

Forward-only migration for TracePilot Milestone 2 (Investigation Engine):

1. ``investigation_jobs`` — durable investigation job state (queued -> running
   -> completed/failed, plus cancelled). UNIQUE(incident_id, idempotency_key)
   makes duplicate submissions safe; NULL keys never conflict so key-less
   jobs are unaffected.
2. ``root_cause_hypotheses`` — inferred hypotheses linked to job + incident.
3. ``hypothesis_evidence_links`` — per-hypothesis supporting/contradicting
   evidence references. UNIQUE(hypothesis_id, evidence_event_id, link_type).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_investigation_engine"
down_revision: str | None = "0009_evidence_dedup_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigation_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_category", sa.String(length=50), nullable=False, server_default="none"),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("app_version", sa.String(length=50), nullable=True),
        sa.Column("result_summary", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="investigation_jobs_incident_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="investigation_jobs_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "incident_id", "idempotency_key", name="uq_investigation_jobs_incident_idempotency"
        ),
    )
    op.create_index(
        "ix_investigation_jobs_organization_id", "investigation_jobs", ["organization_id"]
    )
    op.create_index("ix_investigation_jobs_status", "investigation_jobs", ["status"])
    op.create_index("ix_investigation_jobs_incident", "investigation_jobs", ["incident_id"])
    op.create_index(
        "ix_investigation_jobs_org_status", "investigation_jobs", ["organization_id", "status"]
    )

    op.create_table(
        "root_cause_hypotheses",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("investigation_job_id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="supported"),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["investigation_job_id"],
            ["investigation_jobs.id"],
            name="root_cause_hypotheses_job_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="root_cause_hypotheses_incident_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="root_cause_hypotheses_organization_id_fkey",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_hypotheses_job", "root_cause_hypotheses", ["investigation_job_id"])
    op.create_index("ix_hypotheses_incident", "root_cause_hypotheses", ["incident_id"])
    op.create_index("ix_hypotheses_org", "root_cause_hypotheses", ["organization_id"])

    op.create_table(
        "hypothesis_evidence_links",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("hypothesis_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_event_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("link_type", sa.String(length=20), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"],
            ["root_cause_hypotheses.id"],
            name="hypothesis_evidence_links_hypothesis_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_event_id"],
            ["evidence_events.id"],
            name="hypothesis_evidence_links_evidence_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="hypothesis_evidence_links_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "hypothesis_id", "evidence_event_id", "link_type", name="uq_hypothesis_evidence_link"
        ),
    )
    op.create_index("ix_hyp_evidence_hypothesis", "hypothesis_evidence_links", ["hypothesis_id"])
    op.create_index("ix_hyp_evidence_event", "hypothesis_evidence_links", ["evidence_event_id"])


def downgrade() -> None:
    op.drop_index("ix_hyp_evidence_event", table_name="hypothesis_evidence_links")
    op.drop_index("ix_hyp_evidence_hypothesis", table_name="hypothesis_evidence_links")
    op.drop_table("hypothesis_evidence_links")

    op.drop_index("ix_hypotheses_org", table_name="root_cause_hypotheses")
    op.drop_index("ix_hypotheses_incident", table_name="root_cause_hypotheses")
    op.drop_index("ix_hypotheses_job", table_name="root_cause_hypotheses")
    op.drop_table("root_cause_hypotheses")

    op.drop_index("ix_investigation_jobs_org_status", table_name="investigation_jobs")
    op.drop_index("ix_investigation_jobs_incident", table_name="investigation_jobs")
    op.drop_index("ix_investigation_jobs_status", table_name="investigation_jobs")
    op.drop_index("ix_investigation_jobs_organization_id", table_name="investigation_jobs")
    op.drop_table("investigation_jobs")
