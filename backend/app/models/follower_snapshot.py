from sqlalchemy import Column, Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database.postgres import Base


class FollowerSnapshot(Base):
    __tablename__ = "follower_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "social_account_id",
            "snapshot_date",
            name="uq_follower_snapshot_account_date",
        ),
    )

    id = Column(Integer, primary_key=True)
    social_account_id = Column(
        Integer,
        ForeignKey("social_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_date = Column(Date, nullable=False, index=True)
    followers_count = Column(Integer, nullable=False)

    social_account = relationship("SocialAccount", back_populates="follower_snapshots")
