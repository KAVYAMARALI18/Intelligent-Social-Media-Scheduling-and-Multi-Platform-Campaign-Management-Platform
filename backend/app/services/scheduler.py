import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from dateutil.relativedelta import relativedelta

from app.database.postgres import SessionLocal
from app.models.post import Post
from app.models.social_account import SocialAccount
from app.models.publishing_log import PublishingLog
from app.services.instagram_analytics import (
    capture_daily_follower_snapshots,
    capture_daily_post_metric_snapshots,
)
from app.services.publisher import publish_to_social_media


# ============================================================
# INDIAN TIMEZONE
# ============================================================

INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)


# ============================================================
# CURRENT INDIA TIME
# ============================================================

def get_current_india_time():
    """
    Returns the current Indian Standard Time
    as a naive datetime.

    The database scheduling values are treated
    as Indian local time.
    """

    return datetime.now(
        INDIA_TIMEZONE
    ).replace(
        tzinfo=None
    )


# ============================================================
# NEXT RECURRING DATE
# ============================================================

def get_next_schedule(
    current_time,
    recurrence_type
):
    """
    Calculate the next occurrence of
    a recurring post.
    """

    if recurrence_type == "daily":

        return (
            current_time
            + relativedelta(days=1)
        )

    elif recurrence_type == "weekly":

        return (
            current_time
            + relativedelta(weeks=1)
        )

    elif recurrence_type == "monthly":

        return (
            current_time
            + relativedelta(months=1)
        )

    return None


# ============================================================
# CREATE PUBLISHING LOG
# ============================================================

def create_publishing_log(
    db,
    post,
    social_account,
    status,
    message
):
    """
    Create a publishing log for a post.
    """

    log = PublishingLog(
        post_id=post.id,

        user_id=post.user_id,

        social_account_id=(
            post.social_account_id
        ),

        platform=social_account.platform,

        status=status,

        message=message,

        published_at=(
            get_current_india_time()
        )
    )

    db.add(log)


# ============================================================
# PROCESS SCHEDULED POSTS
# ============================================================

def process_scheduled_posts():

    db = SessionLocal()

    try:

        # ====================================================
        # CURRENT INDIA TIME
        # ====================================================

        now = get_current_india_time()

        print(
            "Scheduler checking scheduled posts..."
        )

        print(
            f"Current India time: {now}"
        )

        # ====================================================
        # FIND DUE POSTS
        # ====================================================

        posts = (
            db.query(Post)
            .filter(
                # Legacy posts use lowercase; new API posts may use uppercase.
                Post.status.in_(["scheduled", "SCHEDULED"]),

                Post.scheduled_at <= now
            )
            .all()
        )

        if not posts:

            print(
                "Found 0 scheduled post(s) "
                "ready to publish."
            )

            return

        print(
            f"Found {len(posts)} scheduled post(s) "
            "ready to publish."
        )

        # ====================================================
        # PROCESS EACH POST
        # ====================================================

        for post in posts:

            social_account = None

            try:

                # ============================================
                # FIND SOCIAL ACCOUNT
                # ============================================

                social_account = (
                    db.query(
                        SocialAccount
                    )
                    .filter(
                        SocialAccount.id
                        == post.social_account_id,

                        SocialAccount.user_id
                        == post.user_id
                    )
                    .first()
                )

                # ============================================
                # ACCOUNT NOT FOUND
                # ============================================

                if not social_account:

                    print(
                        f"Social account not found "
                        f"for post {post.id}"
                    )

                    post.status = "failed"
                    post.error_message = "Social media account not found"

                    log = PublishingLog(
                        post_id=post.id,

                        user_id=post.user_id,

                        social_account_id=None,

                        platform="unknown",

                        status="failed",

                        message=(
                            "Social media account "
                            "not found"
                        ),

                        published_at=(
                            get_current_india_time()
                        )
                    )

                    db.add(log)

                    continue

                # ============================================
                # DISPLAY INFORMATION
                # ============================================

                print(
                    f"Processing post ID: {post.id}"
                )

                print(
                    f"Publishing post {post.id} "
                    f"to {social_account.platform} "
                    f"({social_account.username})"
                )

                # ============================================
                # DISPLAY MEDIA INFORMATION
                # ============================================

                if post.media_url:

                    print(
                        f"Media URL: "
                        f"{post.media_url}"
                    )

                    print(
                        f"Media type: "
                        f"{post.media_type}"
                    )

                    print(
                        f"Media filename: "
                        f"{post.media_filename}"
                    )

                else:

                    print(
                        "No media attached to this post."
                    )

                # ============================================
                # PUBLISH POST
                # ============================================
                #
                # IMPORTANT:
                # We call publisher ONLY ONCE.
                #
                # Media information is passed here.
                # ============================================

                post.status = "publishing"
                db.commit()

                result = (
                    publish_to_social_media(
                        platform=(
                            social_account.platform
                        ),

                        username=(
                            social_account.username
                        ),

                        content=(
                            post.content
                        ),

                        access_token=(
                            social_account.access_token
                        ),

                        media_url=(
                            post.media_url
                        ),

                        media_type=(
                            post.media_type
                        ),

                        social_account=(
                            social_account
                        )
                    )
                )

                # ============================================
                # PUBLISH SUCCESS
                # ============================================

                if result.get("success"):

                    success_message = (
                        result.get(
                            "message",
                            "Post published successfully"
                        )
                    )

                    # ----------------------------------------
                    # CREATE SUCCESS LOG
                    # ----------------------------------------

                    create_publishing_log(
                        db=db,

                        post=post,

                        social_account=social_account,

                        status="published",

                        message=success_message
                    )

                    # ========================================
                    # RECURRING POST
                    # ========================================

                    if (
                        post.is_recurring
                        and post.recurrence_type
                        and post.recurrence_end
                    ):

                        # ------------------------------------
                        # CALCULATE NEXT DATE
                        # ------------------------------------

                        next_schedule = (
                            get_next_schedule(
                                post.scheduled_at,
                                post.recurrence_type
                            )
                        )

                        # ------------------------------------
                        # CHECK RECURRENCE END DATE
                        # ------------------------------------

                        if (
                            next_schedule
                            and
                            next_schedule
                            <= post.recurrence_end
                        ):

                            # ================================
                            # CREATE NEXT RECURRING POST
                            # ================================

                            new_post = Post(

                                user_id=(
                                    post.user_id
                                ),

                                social_account_id=(
                                    post.social_account_id
                                ),

                                content=(
                                    post.content
                                ),

                                status="scheduled",

                                scheduled_at=(
                                    next_schedule
                                ),

                                is_recurring=True,

                                recurrence_type=(
                                    post.recurrence_type
                                ),

                                recurrence_end=(
                                    post.recurrence_end
                                ),

                                # ----------------------------
                                # COPY MEDIA
                                # ----------------------------

                                media_url=(
                                    post.media_url
                                ),

                                media_type=(
                                    post.media_type
                                ),

                                media_filename=(
                                    post.media_filename
                                )
                            )

                            db.add(new_post)

                            # --------------------------------
                            # MARK CURRENT POST AS PUBLISHED
                            # --------------------------------

                            post.status = "published"

                            post.scheduled_at = None

                            print(
                                "Next recurring post "
                                f"scheduled for "
                                f"{next_schedule}"
                            )

                        else:

                            # =================================
                            # RECURRING PERIOD COMPLETED
                            # =================================

                            post.status = "published"

                            post.scheduled_at = None

                            post.is_recurring = False

                            print(
                                f"Recurring schedule "
                                f"completed for post "
                                f"{post.id}"
                            )

                    # ========================================
                    # NORMAL POST
                    # ========================================

                    else:

                        post.status = "published"
                        post.published_at = get_current_india_time()
                        post.platform_post_id = result.get("post_id")
                        post.error_message = None

                        post.scheduled_at = None

                    print(
                        f"Post {post.id} "
                        "published successfully"
                    )

                # =================================================
                # PUBLISH FAILED
                # =================================================

                else:

                    error_message = (
                        result.get(
                            "message",
                            "Unknown publishing error"
                        )
                    )

                    post.status = "failed"
                    post.error_message = error_message

                    create_publishing_log(
                        db=db,

                        post=post,

                        social_account=social_account,

                        status="failed",

                        message=error_message
                    )

                    print(
                        f"Failed to publish post "
                        f"{post.id}: "
                        f"{error_message}"
                    )

            # ====================================================
            # ERROR PROCESSING INDIVIDUAL POST
            # ====================================================

            except Exception as post_error:

                post.status = "failed"
                post.error_message = str(post_error)

                try:

                    if social_account:

                        create_publishing_log(
                            db=db,

                            post=post,

                            social_account=social_account,

                            status="failed",

                            message=str(post_error)
                        )

                except Exception:
                    pass

                print(
                    f"Error while processing post "
                    f"{post.id}: "
                    f"{post_error}"
                )

        # ====================================================
        # SAVE ALL CHANGES
        # ====================================================

        db.commit()

        print(
            "Scheduler processing completed."
        )

    # ========================================================
    # GENERAL SCHEDULER ERROR
    # ========================================================

    except Exception as error:

        db.rollback()

        print(
            f"Scheduler error: {error}"
        )

    # ========================================================
    # CLOSE DATABASE
    # ========================================================

    finally:

        db.close()


# ============================================================
# APSCHEDULER
# ============================================================

scheduler = BackgroundScheduler(
    timezone="Asia/Kolkata"
)


def _capture_daily_follower_snapshots():
    db = SessionLocal()
    try:
        capture_daily_follower_snapshots(db)
    except Exception:
        logger.exception("Daily Instagram follower snapshot collection failed")
        db.rollback()
    try:
        capture_daily_post_metric_snapshots(db)
    except Exception:
        logger.exception("Daily Instagram post metric snapshot collection failed")
        db.rollback()
    finally:
        db.close()


scheduler.add_job(
    process_scheduled_posts,

    "interval",

    seconds=10,

    id="scheduled_posts_job",

    replace_existing=True,

    max_instances=1,

    coalesce=True
)

scheduler.add_job(
    _capture_daily_follower_snapshots,
    "cron",
    hour=0,
    minute=10,
    id="daily_follower_snapshots_job",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)


# ============================================================
# START SCHEDULER
# ============================================================

def start_scheduler():

    if not scheduler.running:

        scheduler.start()

        print(
            "Post scheduler started "
            "(Asia/Kolkata)"
        )


# ============================================================
# STOP SCHEDULER
# ============================================================

def stop_scheduler():

    if scheduler.running:

        scheduler.shutdown()

        print(
            "Post scheduler stopped"
        )