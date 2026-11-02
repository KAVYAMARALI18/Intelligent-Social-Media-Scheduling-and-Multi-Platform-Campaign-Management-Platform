from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    DateTime,
    Boolean,
    CheckConstraint,
)
from datetime import datetime
from sqlalchemy.orm import relationship

from app.database.postgres import Base
from app.models.campaign import Campaign


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'SCHEDULED', 'PUBLISHING', 'PUBLISHED', 'FAILED', 'CANCELLED', 'draft', 'scheduled', 'publishing', 'published', 'failed', 'cancelled')",
            name="post_status_check",
        ),
    )

    # ========================================================
    # PRIMARY KEY
    # ========================================================

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    # ========================================================
    # USER
    # ========================================================

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )

    # ========================================================
    # SOCIAL MEDIA ACCOUNT
    # ========================================================

    social_account_id = Column(
        Integer,
        ForeignKey(
            "social_accounts.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    campaign_id = Column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # ========================================================
    # POST CONTENT
    # ========================================================

    content = Column(
        Text,
        nullable=False,
    )

    # ========================================================
    # POST STATUS
    # ========================================================
    #
    # Possible values:
    #
    # draft
    # scheduled
    # published
    # failed
    # cancelled
    # pending_approval
    #
    # ========================================================

    status = Column(
        String,
        nullable=False,
        default="draft",
    )

    # ========================================================
    # SCHEDULE
    # ========================================================

    scheduled_at = Column(
        DateTime,
        nullable=True,
    )

    published_at = Column(
        DateTime,
        nullable=True,
    )

    platform_post_id = Column(
        String,
        nullable=True,
    )

    error_message = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # ========================================================
    # RECURRING POST
    # ========================================================

    is_recurring = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    recurrence_type = Column(
        String,
        nullable=True,
    )

    recurrence_end = Column(
        DateTime,
        nullable=True,
    )

    # ========================================================
    # MEDIA
    # ========================================================
    #
    # media_url:
    #     URL/path of uploaded image or video
    #
    # media_type:
    #     image / video
    #
    # media_filename:
    #     Original uploaded filename
    #
    # ========================================================

    media_url = Column(
        Text,
        nullable=True,
    )

    media_type = Column(
        String,
        nullable=True,
    )

    media_filename = Column(
        String,
        nullable=True,
    )

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    user = relationship(
        "User",
        backref="posts",
    )

    social_account = relationship(
        "SocialAccount",
        backref="posts",
    )

    metric_snapshots = relationship(
        "PostMetricSnapshot",
        back_populates="post",
        cascade="all, delete-orphan",
    )

    campaign = relationship("Campaign", back_populates="posts")