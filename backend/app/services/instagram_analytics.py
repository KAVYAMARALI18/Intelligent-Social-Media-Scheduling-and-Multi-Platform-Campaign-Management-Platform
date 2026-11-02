import logging
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import requests
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.follower_snapshot import FollowerSnapshot
from app.models.post import Post
from app.models.post_metric_snapshot import PostMetricSnapshot
from app.models.social_account import SocialAccount


logger = logging.getLogger(__name__)
INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")


def _response_data(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else {}
    if isinstance(data, dict):
        return data
    return payload


def _metric_values(payload: dict) -> dict[str, int]:
    values = {}
    data = payload.get("data")
    if not isinstance(data, list):
        return values

    for metric in data:
        if not isinstance(metric, dict):
            continue
        metric_values = metric.get("values")
        if not isinstance(metric_values, list) or not metric_values:
            continue
        value = metric_values[0].get("value")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            name = metric.get("name")
            if isinstance(name, str):
                values[name] = value
    return values


def _request_instagram(url: str, access_token: str, params: dict) -> dict:
    response = requests.get(
        url,
        params={**params, "access_token": access_token},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Instagram returned an invalid metrics response")
    return payload


def get_instagram_post_metrics(posts: list[Post]) -> dict:
    metrics = {
        "reach": None,
        "impressions": None,
        "engagement": None,
        "likes": None,
        "comments": None,
        "timeline": {},
        "failed_posts": 0,
    }
    api_version = os.getenv("INSTAGRAM_API_VERSION", "v26.0")
    base_url = f"https://graph.instagram.com/{api_version}"

    for post in posts:
        account = post.social_account
        if (
            not account
            or account.user_id != post.user_id
            or (account.platform or "").strip().lower() != "instagram"
        ):
            continue
        if not account.access_token or not post.platform_post_id:
            metrics["failed_posts"] += 1
            continue

        media_url = f"{base_url}/{post.platform_post_id}/insights"
        try:
            payload = _request_instagram(
                media_url,
                account.access_token,
                {"metric": "reach,engagement,likes,comments"},
            )
            media_metrics = _metric_values(payload)
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                "Could not fetch Instagram insights for post %s (%s)",
                post.id,
                type(exc).__name__,
            )
            metrics["failed_posts"] += 1
            continue

        try:
            impressions_payload = _request_instagram(
                media_url,
                account.access_token,
                {"metric": "impressions"},
            )
            media_metrics.update(_metric_values(impressions_payload))
        except (requests.RequestException, ValueError) as exc:
            logger.info(
                "Instagram impressions unavailable for post %s (%s)",
                post.id,
                type(exc).__name__,
            )

        post_date = (post.published_at or post.created_at).date().isoformat()
        date_metrics = metrics["timeline"].setdefault(post_date, {"date": post_date})
        for metric_name in ("reach", "impressions", "engagement", "likes", "comments"):
            value = media_metrics.get(metric_name)
            if value is None:
                continue
            metrics[metric_name] = (metrics[metric_name] or 0) + value
            date_metrics[metric_name] = date_metrics.get(metric_name, 0) + value

    metrics["timeline"] = [
        metrics["timeline"][key] for key in sorted(metrics["timeline"])
    ]
    metrics["available"] = any(
        metrics[name] is not None
        for name in ("reach", "impressions", "engagement", "likes", "comments")
    )
    return metrics


def get_instagram_followers(account: SocialAccount) -> int | None:
    if not account.access_token:
        return None

    api_version = os.getenv("INSTAGRAM_API_VERSION", "v26.0")
    try:
        payload = _request_instagram(
            f"https://graph.instagram.com/{api_version}/me",
            account.access_token,
            {"fields": "user_id,followers_count"},
        )
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "Could not fetch Instagram follower count for account %s (%s)",
            account.id,
            type(exc).__name__,
        )
        return None

    profile = _response_data(payload)
    followers = profile.get("followers_count")
    if isinstance(followers, int) and not isinstance(followers, bool) and followers >= 0:
        return followers
    return None


def capture_daily_follower_snapshots(
    db: Session,
    snapshot_date: date | None = None,
    user_id: int | None = None,
) -> dict[int, int]:
    observed_date = snapshot_date or datetime.now(INDIA_TIMEZONE).date()
    account_query = db.query(SocialAccount).filter(
        SocialAccount.platform.ilike("instagram"),
        SocialAccount.access_token.isnot(None),
        func.trim(SocialAccount.access_token) != "",
    )
    if user_id is not None:
        account_query = account_query.filter(SocialAccount.user_id == user_id)
    accounts = account_query.all()
    captured = {}

    for account in accounts:
        followers = get_instagram_followers(account)
        if followers is None:
            continue
        snapshot = (
            db.query(FollowerSnapshot)
            .filter(
                FollowerSnapshot.social_account_id == account.id,
                FollowerSnapshot.snapshot_date == observed_date,
            )
            .first()
        )
        if snapshot is None:
            snapshot = FollowerSnapshot(
                social_account_id=account.id,
                snapshot_date=observed_date,
                followers_count=followers,
            )
            db.add(snapshot)
        else:
            snapshot.followers_count = followers
        captured[account.id] = followers

    if captured:
        db.commit()
    return captured


def capture_daily_post_metric_snapshots(
    db: Session,
    snapshot_date: date | None = None,
) -> int:
    observed_date = snapshot_date or datetime.now(INDIA_TIMEZONE).date()
    posts = (
        db.query(Post)
        .join(
            SocialAccount,
            and_(
                Post.social_account_id == SocialAccount.id,
                SocialAccount.user_id == Post.user_id,
            ),
        )
        .filter(
            func.lower(Post.status) == "published",
            func.lower(SocialAccount.platform) == "instagram",
            SocialAccount.access_token.isnot(None),
            Post.platform_post_id.isnot(None),
        )
        .all()
    )
    saved = 0
    metric_names = (
        "reach",
        "impressions",
        "engagement",
        "likes",
        "comments",
        "shares",
        "clicks",
        "views",
    )

    for post in posts:
        metrics = get_instagram_post_metrics([post])
        if not metrics["available"]:
            continue

        snapshot = (
            db.query(PostMetricSnapshot)
            .filter(
                PostMetricSnapshot.post_id == post.id,
                PostMetricSnapshot.snapshot_date == observed_date,
            )
            .first()
        )
        if snapshot is None:
            snapshot = PostMetricSnapshot(
                post_id=post.id,
                social_account_id=post.social_account_id,
                platform="Instagram",
                snapshot_date=observed_date,
                captured_at=datetime.now(timezone.utc),
            )
            db.add(snapshot)

        snapshot.social_account_id = post.social_account_id
        snapshot.platform = "Instagram"
        snapshot.captured_at = datetime.now(timezone.utc)
        for metric_name in metric_names:
            value = metrics.get(metric_name)
            if value is not None:
                setattr(snapshot, metric_name, value)
        saved += 1

    if saved:
        db.commit()
    return saved
