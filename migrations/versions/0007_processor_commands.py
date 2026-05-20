"""add processor command queue

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-20 20:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processor_commands",
        sa.Column("command_id", sa.Integer(), primary_key=True),
        sa.Column("processor_id", sa.Integer(), nullable=False),
        sa.Column("command_type", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("claimed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=False), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')",
            name="processor_commands_status_chk",
        ),
        sa.ForeignKeyConstraint(["processor_id"], ["processors.processor_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.user_id"], ondelete="SET NULL"),
    )
    op.create_index(
        "processor_commands_processor_status_idx",
        "processor_commands",
        ["processor_id", "status"],
    )
    op.create_index(
        "processor_commands_created_idx",
        "processor_commands",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("processor_commands_created_idx", table_name="processor_commands")
    op.drop_index("processor_commands_processor_status_idx", table_name="processor_commands")
    op.drop_table("processor_commands")
