"""Add groundedness assessment and system confidence columns to root_cause_hypotheses

Revision ID: 0013_hypothesis_groundedness_assessment
Revises: 0012_evidence_embeddings
Create Date: 2026-10-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013_hypothesis_groundedness_assessment"
down_revision: str | None = "0012_evidence_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "root_cause_hypotheses",
        sa.Column("groundedness_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "root_cause_hypotheses",
        sa.Column("system_confidence_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "root_cause_hypotheses",
        sa.Column("system_confidence", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "root_cause_hypotheses",
        sa.Column("groundedness_status", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "root_cause_hypotheses",
        sa.Column("assessment_version", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "root_cause_hypotheses",
        sa.Column(
            "assessment_details",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("root_cause_hypotheses", "assessment_details")
    op.drop_column("root_cause_hypotheses", "assessment_version")
    op.drop_column("root_cause_hypotheses", "groundedness_status")
    op.drop_column("root_cause_hypotheses", "system_confidence")
    op.drop_column("root_cause_hypotheses", "system_confidence_score")
    op.drop_column("root_cause_hypotheses", "groundedness_score")
