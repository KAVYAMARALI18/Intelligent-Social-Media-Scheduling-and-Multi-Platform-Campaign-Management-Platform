"""store daily provider post metric snapshots

Revision ID: d7e8f9a0b1c2
Revises: c6a7b8d9e0f1, e5f6a7b8c9d0
Create Date: 2026-10-29 10:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = (
    "c6a7b8d9e0f1",
    "e5f6a7b8c9d0",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "post_metric_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("social_account_id", sa.Integer(), nullable=True),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reach", sa.Integer(), nullable=True),
        sa.Column("impressions", sa.Integer(), nullable=True),
        sa.Column("engagement", sa.Integer(), nullable=True),
        sa.Column("likes", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=True),
        sa.Column("clicks", sa.Integer(), nullable=True),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["social_account_id"],
            ["social_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "post_id",
            "snapshot_date",
            name="uq_post_metric_snapshot_post_date",
        ),
    )
    op.create_index(
        op.f("ix_post_metric_snapshots_post_id"),
        "post_metric_snapshots",
        ["post_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_post_metric_snapshots_social_account_id"),
        "post_metric_snapshots",
        ["social_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_post_metric_snapshots_snapshot_date"),
        "post_metric_snapshots",
        ["snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_post_metric_snapshots_snapshot_date"),
        table_name="post_metric_snapshots",
    )
    op.drop_index(
        op.f("ix_post_metric_snapshots_social_account_id"),
        table_name="post_metric_snapshots",
    )
    op.drop_index(
        op.f("ix_post_metric_snapshots_post_id"),
        table_name="post_metric_snapshots",
    )
    op.drop_table("post_metric_snapshots")
