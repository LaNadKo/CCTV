"""add soft delete columns for cameras and persons

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-19 16:30:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cameras
        ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITHOUT TIME ZONE NULL
        """
    )
    op.execute(
        """
        ALTER TABLE persons
        ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITHOUT TIME ZONE NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS cameras_deleted_at_idx ON cameras(deleted_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS persons_deleted_at_idx ON persons(deleted_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS persons_deleted_at_idx")
    op.execute("DROP INDEX IF EXISTS cameras_deleted_at_idx")
    op.execute("ALTER TABLE persons DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE cameras DROP COLUMN IF EXISTS deleted_at")
