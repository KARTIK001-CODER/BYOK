"""Add TracePilot remediation approval and audit trail tables (Milestone 5B).

Revision ID: 0015_remediation_approval_and_audit
Revises: 0014_remediation_proposals
Create Date: 2026-10-11 00:00:00.000000

Forward-only migration for TracePilot Milestone 5B:
- Add proposal version and approval tracking columns to ``remediation_proposals``
- Create ``remediation_approvals`` for durable append-only decision records
- Create ``remediation_audit_events`` for immutable lifecycle audit trail
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015_remediation_approval_and_audit"
down_revision: str | None = "0014_remediation_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add version and approval columns to remediation_proposals
    op.add_column(
        "remediation_proposals",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "remediation_proposals",
        sa.Column(
            "approved_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "remediation_proposals",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Create remediation_approvals table
    op.create_table(
        "remediation_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "remediation_proposal_id",
            sa.String(length=36),
            sa.ForeignKey("remediation_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column(
            "reviewer_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("risk_level_at_decision", sa.String(length=20), nullable=False),
        sa.Column("policy_version", sa.String(length=20), nullable=False, server_default="v1"),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column(
            "snapshot",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
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
        "ix_remediation_approvals_proposal",
        "remediation_approvals",
        ["remediation_proposal_id"],
    )
    op.create_index(
        "ix_remediation_approvals_org",
        "remediation_approvals",
        ["organization_id"],
    )
    op.create_index(
        "ix_remediation_approvals_prop_ver",
        "remediation_approvals",
        ["remediation_proposal_id", "proposal_version"],
    )

    # 3. Create remediation_audit_events table
    op.create_table(
        "remediation_audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "remediation_proposal_id",
            sa.String(length=36),
            sa.ForeignKey("remediation_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_role", sa.String(length=20), nullable=True),
        sa.Column("proposal_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=True),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_remediation_audit_proposal_created",
        "remediation_audit_events",
        ["remediation_proposal_id", "created_at"],
    )
    op.create_index(
        "ix_remediation_audit_org_created",
        "remediation_audit_events",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_remediation_audit_event_type",
        "remediation_audit_events",
        ["event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_remediation_audit_event_type", table_name="remediation_audit_events")
    op.drop_index("ix_remediation_audit_org_created", table_name="remediation_audit_events")
    op.drop_index("ix_remediation_audit_proposal_created", table_name="remediation_audit_events")
    op.drop_table("remediation_audit_events")

    op.drop_index("ix_remediation_approvals_prop_ver", table_name="remediation_approvals")
    op.drop_index("ix_remediation_approvals_org", table_name="remediation_approvals")
    op.drop_index("ix_remediation_approvals_proposal", table_name="remediation_approvals")
    op.drop_table("remediation_approvals")

    op.drop_column("remediation_proposals", "approved_at")
    op.drop_column("remediation_proposals", "approved_by_user_id")
    op.drop_column("remediation_proposals", "version")
