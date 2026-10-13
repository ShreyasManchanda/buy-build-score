"""run lease: one active stream executes a run; others follow

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN lease_until timestamptz")
    op.execute("ALTER TABLE leads ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()")


def downgrade() -> None:
    op.execute("ALTER TABLE leads DROP COLUMN updated_at")
    op.execute("ALTER TABLE runs DROP COLUMN lease_until")
