"""Add incidents and evidence_events tables for TracePilot Incident Foundation v0

Revision ID: 0008_incident_foundation
Revises: 0007_conversations_and_messages
Create Date: 2026-10-04 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_incident_foundation"
down_revision: str | None = "0007_conversations_and_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create incidents table
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("service_name", sa.String(length=100), nullable=True),
        sa.Column("environment", sa.String(length=50), nullable=False, server_default="production"),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("incident_metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
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
            ["organization_id"],
            ["organizations.id"],
            name="incidents_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="incidents_created_by_user_id_fkey",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_incidents_organization_id", "incidents", ["organization_id"])
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_severity", "incidents", ["severity"])
    op.create_index("ix_incidents_service_name", "incidents", ["service_name"])
    op.create_index("ix_incidents_environment", "incidents", ["environment"])
    op.create_index("ix_incidents_org_status", "incidents", ["organization_id", "status"])
    op.create_index("ix_incidents_org_severity", "incidents", ["organization_id", "severity"])
    op.create_index("ix_incidents_org_service", "incidents", ["organization_id", "service_name"])
    op.create_index("ix_incidents_org_created_at", "incidents", ["organization_id", "created_at"])

    # 2. Create evidence_events table
    op.create_table(
        "evidence_events",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingestion_timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("normalized_payload", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("deduplication_key", sa.String(length=255), nullable=True),
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
            name="evidence_events_incident_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="evidence_events_organization_id_fkey",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_evidence_events_incident_id", "evidence_events", ["incident_id"])
    op.create_index("ix_evidence_events_organization_id", "evidence_events", ["organization_id"])
    op.create_index("ix_evidence_events_source_type", "evidence_events", ["source_type"])
    op.create_index("ix_evidence_events_event_type", "evidence_events", ["event_type"])
    op.create_index("ix_evidence_events_event_timestamp", "evidence_events", ["event_timestamp"])
    op.create_index(
        "ix_evidence_events_incident_time",
        "evidence_events",
        ["incident_id", "event_timestamp"],
    )
    op.create_index(
        "ix_evidence_events_org_incident",
        "evidence_events",
        ["organization_id", "incident_id"],
    )
    op.create_index(
        "ix_evidence_events_incident_source",
        "evidence_events",
        ["incident_id", "source_type"],
    )
    op.create_index(
        "ix_evidence_events_dedup",
        "evidence_events",
        ["incident_id", "deduplication_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_events_dedup", table_name="evidence_events")
    op.drop_index("ix_evidence_events_incident_source", table_name="evidence_events")
    op.drop_index("ix_evidence_events_org_incident", table_name="evidence_events")
    op.drop_index("ix_evidence_events_incident_time", table_name="evidence_events")
    op.drop_index("ix_evidence_events_event_timestamp", table_name="evidence_events")
    op.drop_index("ix_evidence_events_event_type", table_name="evidence_events")
    op.drop_index("ix_evidence_events_source_type", table_name="evidence_events")
    op.drop_index("ix_evidence_events_organization_id", table_name="evidence_events")
    op.drop_index("ix_evidence_events_incident_id", table_name="evidence_events")
    op.drop_table("evidence_events")

    op.drop_index("ix_incidents_org_created_at", table_name="incidents")
    op.drop_index("ix_incidents_org_service", table_name="incidents")
    op.drop_index("ix_incidents_org_severity", table_name="incidents")
    op.drop_index("ix_incidents_org_status", table_name="incidents")
    op.drop_index("ix_incidents_environment", table_name="incidents")
    op.drop_index("ix_incidents_service_name", table_name="incidents")
    op.drop_index("ix_incidents_severity", table_name="incidents")
    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_organization_id", table_name="incidents")
    op.drop_table("incidents")
