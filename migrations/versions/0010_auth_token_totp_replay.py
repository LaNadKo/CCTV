"""add auth token version and totp replay counter

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE user_mfa_methods ADD COLUMN IF NOT EXISTS last_totp_counter INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE user_mfa_methods DROP COLUMN IF EXISTS last_totp_counter")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS token_version")
