"""Add TracePilot remediation proposals table (Milestone 5A).

Revision ID: 0014_remediation_proposals
Revises: 0013_hypothesis_groundedness_assessment
Create Date: 2026-10-11 00:00:00.000000

Forward-only migration for TracePilot Milestone 5A (Remediation Proposals):
- ``remediation_proposals`` table with strict tenant isolation,
  risk assessment details, non-executable safety constraints, and lifecycle state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014_remediation_proposals"
down_revision: str | None = "0013_hypothesis_groundedness_assessment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "remediation_proposals",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "incident_id",
            sa.String(length=36),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "hypothesis_id",
            sa.String(length=36),
            sa.ForeignKey("root_cause_hypotheses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "investigation_job_id",
            sa.String(length=36),
            sa.ForeignKey("investigation_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="proposed"),
        sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column(
            "risk_assessment",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "actions",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "is_executable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("rollback_plan", sa.Text(), nullable=True),
        sa.Column("estimated_impact", sa.String(length=255), nullable=True),
        sa.Column("mitigation_rationale", sa.Text(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "superseded_by_id",
            sa.String(length=36),
            sa.ForeignKey("remediation_proposals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    )
    op.create_index(
        "ix_remediation_proposals_incident",
        "remediation_proposals",
        ["incident_id"],
    )
    op.create_index(
        "ix_remediation_proposals_org_status",
        "remediation_proposals",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_remediation_proposals_hypothesis",
        "remediation_proposals",
        ["hypothesis_id"],
    )
    op.create_index(
        "ix_remediation_proposals_job",
        "remediation_proposals",
        ["investigation_job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_remediation_proposals_job", table_name="remediation_proposals")
    op.drop_index("ix_remediation_proposals_hypothesis", table_name="remediation_proposals")
    op.drop_index("ix_remediation_proposals_org_status", table_name="remediation_proposals")
    op.drop_index("ix_remediation_proposals_incident", table_name="remediation_proposals")
    op.drop_table("remediation_proposals")
