from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database.postgres import Base


class PostMetricSnapshot(Base):
    __tablename__ = "post_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "post_id",
            "snapshot_date",
            name="uq_post_metric_snapshot_post_date",
        ),
    )

    id = Column(Integer, primary_key=True)
    post_id = Column(
        Integer,
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    social_account_id = Column(
        Integer,
        ForeignKey("social_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    platform = Column(String, nullable=False)
    snapshot_date = Column(Date, nullable=False, index=True)
    captured_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reach = Column(Integer, nullable=True)
    impressions = Column(Integer, nullable=True)
    engagement = Column(Integer, nullable=True)
    likes = Column(Integer, nullable=True)
    comments = Column(Integer, nullable=True)
    shares = Column(Integer, nullable=True)
    clicks = Column(Integer, nullable=True)
    views = Column(Integer, nullable=True)

    post = relationship("Post", back_populates="metric_snapshots")
