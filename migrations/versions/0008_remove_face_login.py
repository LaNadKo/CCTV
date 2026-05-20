"""remove face login authentication

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(column["name"] == column_name for column in sa.inspect(op.get_bind()).get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def upgrade() -> None:
    if _has_table("user_face_templates"):
        if _has_index("user_face_templates", "user_face_templates_user_idx"):
            op.drop_index("user_face_templates_user_idx", table_name="user_face_templates")
        op.drop_table("user_face_templates")

    if _has_column("users", "face_login_enabled"):
        op.drop_column("users", "face_login_enabled")


def downgrade() -> None:
    if not _has_column("users", "face_login_enabled"):
        op.add_column(
            "users",
            sa.Column("face_login_enabled", sa.Boolean(), nullable=False, server_default="false"),
        )

    if not _has_table("user_face_templates"):
        op.create_table(
            "user_face_templates",
            sa.Column("user_face_id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
            sa.Column("embedding", sa.LargeBinary(), nullable=False),
            sa.Column("model", sa.String(50)),
            sa.Column("distance_metric", sa.String(20), nullable=False, server_default="cosine"),
            sa.Column("threshold", sa.Numeric(5, 3)),
            sa.Column("quality_score", sa.Numeric(5, 2)),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("distance_metric IN ('cosine', 'l2')", name="user_face_templates_metric_chk"),
        )
        op.create_index("user_face_templates_user_idx", "user_face_templates", ["user_id"])
