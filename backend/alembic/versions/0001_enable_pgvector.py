"""Enable pgvector and uuid-ossp extensions

Revision ID: 0001_enable_pgvector
Revises:
Create Date: 2026-08-30 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_enable_pgvector"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable pgvector extension for dense embedding storage and index types (HNSW, IVFFlat)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    # Enable uuid-ossp extension for UUID generation
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector;")
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp";')
