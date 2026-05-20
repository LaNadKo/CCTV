"""add stable processor node uid

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-20 19:20:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE processors
        ADD COLUMN IF NOT EXISTS node_uid VARCHAR(128)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS processors_node_uid_idx
        ON processors(node_uid)
        WHERE node_uid IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS processors_node_uid_idx")
    op.execute("ALTER TABLE processors DROP COLUMN IF EXISTS node_uid")
