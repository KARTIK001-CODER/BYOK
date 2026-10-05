"""Enforce evidence deduplication idempotency and align source_type index

Revision ID: 0009_evidence_dedup_idempotency
Revises: 0008_incident_foundation
Create Date: 2026-10-05 00:00:00.000000

Forward-only stabilization migration for TracePilot Incident Foundation v0:

1. Adds UNIQUE constraint ``uq_evidence_events_incident_dedup`` on
   ``(incident_id, deduplication_key)`` so concurrent
   ``POST /incidents/{id}/evidence`` requests with the same key cannot
   create duplicates (check-then-insert race). NULL keys never conflict
   on PostgreSQL or SQLite, so key-less events are unaffected. Replaces
   the non-unique ``ix_evidence_events_dedup`` index.
2. Aligns ``ix_evidence_events_source_type`` with the ORM metadata
   (composite ``(incident_id, source_type)`` used by
   ``list_evidence`` filtering) and drops the redundant
   ``ix_evidence_events_incident_source`` index.

NOTE: if the table already contains duplicate (incident_id,
deduplication_key) rows, the UNIQUE constraint creation will fail.
Deduplicate existing rows before upgrading in that case.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_evidence_dedup_idempotency"
down_revision: str | None = "0008_incident_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enforce idempotency at the database level.
    op.create_unique_constraint(
        "uq_evidence_events_incident_dedup",
        "evidence_events",
        ["incident_id", "deduplication_key"],
    )
    op.drop_index("ix_evidence_events_dedup", table_name="evidence_events")

    # 2. Align source_type index with ORM metadata; drop redundant index.
    op.drop_index("ix_evidence_events_incident_source", table_name="evidence_events")
    op.drop_index("ix_evidence_events_source_type", table_name="evidence_events")
    op.create_index(
        "ix_evidence_events_source_type",
        "evidence_events",
        ["incident_id", "source_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_events_source_type", table_name="evidence_events")
    op.create_index("ix_evidence_events_source_type", "evidence_events", ["source_type"])
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
    op.drop_constraint("uq_evidence_events_incident_dedup", "evidence_events", type_="unique")
