"""add trigram indexes for user and person search

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS users_search_trgm_idx
        ON users USING gin (
            lower(
                coalesce(login, '') || ' ' ||
                coalesce(last_name, '') || ' ' ||
                coalesce(first_name, '') || ' ' ||
                coalesce(middle_name, '')
            )
            gin_trgm_ops
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS persons_search_trgm_idx
        ON persons USING gin (
            lower(
                person_id::text || ' ' ||
                coalesce(last_name, '') || ' ' ||
                coalesce(first_name, '') || ' ' ||
                coalesce(middle_name, '')
            )
            gin_trgm_ops
        )
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS cameras_search_trgm_idx
        ON cameras USING gin (
            lower(
                camera_id::text || ' ' ||
                coalesce(name, '') || ' ' ||
                coalesce(location, '') || ' ' ||
                coalesce(ip_address, '')
            )
            gin_trgm_ops
        )
        WHERE deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS groups_search_trgm_idx
        ON groups USING gin (
            lower(group_id::text || ' ' || coalesce(name, '') || ' ' || coalesce(description, ''))
            gin_trgm_ops
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS groups_search_trgm_idx")
    op.execute("DROP INDEX IF EXISTS cameras_search_trgm_idx")
    op.execute("DROP INDEX IF EXISTS persons_search_trgm_idx")
    op.execute("DROP INDEX IF EXISTS users_search_trgm_idx")
