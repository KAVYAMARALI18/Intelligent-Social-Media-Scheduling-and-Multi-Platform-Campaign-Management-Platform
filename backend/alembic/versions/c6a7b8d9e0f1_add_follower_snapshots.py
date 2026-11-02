"""store daily connected-account follower counts

Revision ID: c6a7b8d9e0f1
Revises: 9f6e1f2873e8
Create Date: 2026-10-18 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6a7b8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "9f6e1f2873e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "follower_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("social_account_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("followers_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["social_account_id"],
            ["social_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "social_account_id",
            "snapshot_date",
            name="uq_follower_snapshot_account_date",
        ),
    )
    op.create_index(
        op.f("ix_follower_snapshots_social_account_id"),
        "follower_snapshots",
        ["social_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_follower_snapshots_snapshot_date"),
        "follower_snapshots",
        ["snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_follower_snapshots_snapshot_date"),
        table_name="follower_snapshots",
    )
    op.drop_index(
        op.f("ix_follower_snapshots_social_account_id"),
        table_name="follower_snapshots",
    )
    op.drop_table("follower_snapshots")
