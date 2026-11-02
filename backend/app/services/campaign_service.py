from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.social_account import SocialAccount
from app.schemas.campaign import CampaignCreate, CampaignStatus, CampaignUpdate


CAMPAIGN_TRACKING_WORKFLOW = ["Draft", "Scheduled", "Active", "Completed"]
POST_METRIC_NAMES = (
    "reach",
    "impressions",
    "likes",
    "comments",
    "shares",
    "clicks",
    "views",
    "engagement",
)


def _get_post_performance(post) -> dict:
    snapshots = list(getattr(post, "metric_snapshots", []) or [])
    if not snapshots:
        return {name: None for name in POST_METRIC_NAMES}
    latest = max(
        snapshots,
        key=lambda snapshot: (
            getattr(snapshot, "snapshot_date", date.min),
            str(getattr(snapshot, "captured_at", "") or ""),
        ),
    )
    values = {name: getattr(latest, name, None) for name in POST_METRIC_NAMES}
    if values["engagement"] is None and (
        values["likes"] is not None and values["comments"] is not None
    ):
        values["engagement"] = values["likes"] + values["comments"]
    return values


def build_campaign_analytics(campaigns: list[Campaign], posts: list) -> dict:
    """Aggregate the latest recorded post metrics; missing values stay unavailable."""
    totals = {name: 0 for name in POST_METRIC_NAMES}
    observed = {name: False for name in POST_METRIC_NAMES}

    for post in posts:
        if str(getattr(post, "status", "")).lower() != "published":
            continue
        performance = _get_post_performance(post)
        for name in POST_METRIC_NAMES:
            if performance[name] is not None:
                totals[name] += performance[name]
                observed[name] = True

    metrics = {
        name: totals[name] if observed[name] else None
        for name in POST_METRIC_NAMES
    }
    engagement_rate = (
        round((metrics["engagement"] / metrics["reach"]) * 100, 2)
        if metrics["engagement"] is not None
        and metrics["reach"] is not None
        and metrics["reach"] > 0
        else None
    )

    return {
        **metrics,
        "total_engagement": metrics["engagement"],
        "engagement_rate": engagement_rate,
    }


def build_campaign_tracking(campaign: Campaign) -> dict:
    """Return a lightweight summary for campaign lifecycle tracking."""
    posts = list(getattr(campaign, "posts", []) or [])
    total_posts = len(posts)
    scheduled_posts = sum(
        1 for post in posts if str(getattr(post, "status", "")).lower() == "scheduled"
    )
    published_posts = sum(
        1 for post in posts if str(getattr(post, "status", "")).lower() == "published"
    )
    failed_posts = sum(
        1 for post in posts if str(getattr(post, "status", "")).lower() == "failed"
    )
    current_status = getattr(campaign, "status", "Draft") or "Draft"

    return {
        "total_posts": total_posts,
        "scheduled_posts": scheduled_posts,
        "published_posts": published_posts,
        "failed_posts": failed_posts,
        "status": current_status,
        "start_date": getattr(campaign, "start_date", None),
        "end_date": getattr(campaign, "end_date", None),
        "workflow": CAMPAIGN_TRACKING_WORKFLOW,
    }


def build_campaign_comparison(campaigns: list[Campaign]) -> dict:
    """Compare multiple campaigns by cost, revenue, reach, engagement, and ROI."""
    comparison_rows = []
    observed_costs = []

    for campaign in campaigns:
        posts = list(getattr(campaign, "posts", []) or [])
        published_posts = [post for post in posts if str(getattr(post, "status", "")).lower() == "published"]
        analytics = build_campaign_analytics([campaign], published_posts)
        cost = float(campaign.budget) if campaign.budget is not None else None
        if cost is not None:
            observed_costs.append(cost)

        row = {
            "campaign_id": campaign.id,
            "name": campaign.name,
            "status": getattr(campaign, "status", "Draft"),
            "budget": round(cost, 2) if cost is not None else None,
            "cost": round(cost, 2) if cost is not None else None,
            "revenue": None,
            "roi": None,
            "reach": analytics["reach"],
            "engagement": analytics["total_engagement"],
            "impressions": analytics["impressions"],
            "published_posts": len(published_posts),
            "total_posts": len(posts),
            "engagement_rate": analytics["engagement_rate"],
            "performance": round((len(published_posts) / len(posts) * 100), 2) if posts else 0.0,
        }
        comparison_rows.append(row)

    best_campaign = {
        "campaign_id": None,
        "name": "N/A",
        "roi": None,
    }

    return {
        "summary": {
            "total_campaigns": len(comparison_rows),
            "total_cost": round(sum(observed_costs), 2) if observed_costs else None,
            "total_revenue": None,
            "average_roi": None,
            "best_campaign": {
                "campaign_id": best_campaign.get("campaign_id"),
                "name": best_campaign.get("name"),
                "roi": best_campaign.get("roi"),
            },
        },
        "comparison": comparison_rows,
    }


def _campaign_audience_metrics(campaign: Campaign, posts: list) -> dict:
    accounts = {
        account.id: account
        for account in list(getattr(campaign, "social_accounts", []) or [])
        if account.id is not None
        and (getattr(account, "platform", "") or "").lower() == "instagram"
    }
    for post in posts:
        account = getattr(post, "social_account", None)
        if (
            account
            and account.id is not None
            and (getattr(account, "platform", "") or "").lower() == "instagram"
        ):
            accounts[account.id] = account

    account_snapshots = {}
    for account_id, account in accounts.items():
        snapshots = sorted(
            (
                snapshot
                for snapshot in list(getattr(account, "follower_snapshots", []) or [])
                if (
                    getattr(campaign, "start_date", None) is None
                    or snapshot.snapshot_date >= campaign.start_date
                )
                and (
                    getattr(campaign, "end_date", None) is None
                    or snapshot.snapshot_date <= campaign.end_date
                )
            ),
            key=lambda snapshot: snapshot.snapshot_date,
        )
        if snapshots:
            account_snapshots[account_id] = {
                snapshot.snapshot_date: snapshot.followers_count
                for snapshot in snapshots
            }

    current_followers = None
    net_growth = None
    growth_percentage = None
    timeline = []
    if accounts and len(account_snapshots) == len(accounts):
        current_followers = sum(
            max(values.items())[1] for values in account_snapshots.values()
        )
        shared_dates = set.intersection(
            *(set(values) for values in account_snapshots.values())
        )
        ordered_dates = sorted(shared_dates)
        if len(ordered_dates) >= 2:
            for snapshot_date in ordered_dates:
                total = sum(
                    values[snapshot_date] for values in account_snapshots.values()
                )
                previous = timeline[-1]["followers"] if timeline else None
                timeline.append({
                    "date": snapshot_date.isoformat(),
                    "followers": total,
                    "new_followers": (
                        max(total - previous, 0) if previous is not None else None
                    ),
                    "net_growth": total - previous if previous is not None else None,
                    "growth_percentage": (
                        round((total - previous) / previous * 100, 2)
                        if previous
                        else None
                    ),
                })
            starting_followers = timeline[0]["followers"]
            ending_followers = timeline[-1]["followers"]
            net_growth = ending_followers - starting_followers
            growth_percentage = (
                round(net_growth / starting_followers * 100, 2)
                if starting_followers
                else None
            )

    return {
        "current_followers": current_followers,
        "net_growth": net_growth,
        "new_followers": max(net_growth, 0) if net_growth is not None else None,
        "lost_followers": max(-net_growth, 0) if net_growth is not None else None,
        "growth_percentage": growth_percentage,
        "timeline": timeline,
        "message": (
            "Follower history is not available until snapshots are collected."
            if current_followers is None
            else "Follower growth requires snapshots on at least two matching dates."
            if net_growth is None
            else "Follower growth is calculated from recorded account snapshots."
        ),
    }


def build_campaign_report(campaign: Campaign) -> dict:
    """Build a campaign report only from stored post and follower snapshots."""
    tracking = build_campaign_tracking(campaign)
    posts = list(getattr(campaign, "posts", []) or [])
    total_posts = tracking["total_posts"]
    published_posts = [post for post in posts if str(getattr(post, "status", "")).lower() == "published"]
    failed_posts = tracking["failed_posts"]
    start_date = getattr(campaign, "start_date", None)
    end_date = getattr(campaign, "end_date", None)

    duration = "Not set"
    if start_date and end_date:
        duration = f"{start_date.isoformat()} to {end_date.isoformat()}"
    elif start_date:
        duration = f"Starts {start_date.isoformat()}"
    elif end_date:
        duration = f"Ends {end_date.isoformat()}"

    analytics = build_campaign_analytics([campaign], published_posts)
    reach = analytics["reach"]
    impressions = analytics["impressions"]
    engagement = analytics["total_engagement"]
    performance = round((tracking["published_posts"] / total_posts * 100), 2) if total_posts else 0.0

    audience = _campaign_audience_metrics(campaign, posts)
    total_followers = audience["current_followers"]
    new_followers = audience["new_followers"]
    lost_followers = audience["lost_followers"]
    follower_growth = audience["net_growth"]
    growth_percentage = audience["growth_percentage"]
    audience_timeline = audience["timeline"]

    top_performing_content = []
    for post in published_posts:
        performance_summary = _get_post_performance(post)
        if performance_summary["engagement"] is None:
            continue
        top_performing_content.append({
            "content": post.content[:90],
            "platform": getattr(getattr(post, "social_account", None), "platform", "unknown"),
            "published_at": getattr(post, "published_at", None).isoformat() if getattr(post, "published_at", None) else None,
            "engagement_score": performance_summary["engagement"],
            "reach": performance_summary["reach"],
            "impressions": performance_summary["impressions"],
        })
    top_performing_content = sorted(top_performing_content, key=lambda item: item["engagement_score"], reverse=True)[:3]

    def report_value(value):
        return f"{value:,}" if value is not None else "Not available"

    report_text = (
        "Campaign Report\n"
        "--------------------------------\n"
        f"Campaign: {campaign.name}\n\n"
        f"Duration:           {duration}\n"
        f"Status:             {tracking['status']}\n"
        f"Total Posts:        {total_posts}\n"
        f"Published:          {tracking['published_posts']}\n"
        f"Failed:             {failed_posts}\n"
        f"Reach:              {report_value(reach)}\n"
        f"Impressions:        {report_value(impressions)}\n"
        f"Engagement:         {report_value(engagement)}\n"
        f"New Followers:      {report_value(new_followers)}\n"
        f"Lost Followers:     {report_value(lost_followers)}\n"
        f"Total Followers:    {report_value(total_followers)}\n"
        f"Follower Growth:    {report_value(follower_growth)}\n"
        f"Growth Rate:        {f'{growth_percentage:.2f}%' if growth_percentage is not None else 'Not available'}\n"
        f"Performance:        {performance}%\n"
    )
    if top_performing_content:
        top_item = top_performing_content[0]
        report_text += f"Top Content:        {top_item['content']}\n"

    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "campaign_duration": duration,
        "status": tracking["status"],
        "total_posts": total_posts,
        "published_posts": tracking["published_posts"],
        "failed_posts": failed_posts,
        "engagement": engagement,
        "reach": reach,
        "impressions": impressions,
        "new_followers": new_followers,
        "lost_followers": lost_followers,
        "total_followers": total_followers,
        "follower_growth": follower_growth,
        "growth_percentage": growth_percentage,
        "audience_growth": follower_growth,
        "audience_message": audience["message"],
        "performance": performance,
        "audience_timeline": audience_timeline,
        "top_performing_content": top_performing_content,
        "report_text": report_text,
    }


class CampaignNotFoundError(Exception):
    """Raised when a campaign does not exist for the requested user."""


class CampaignDateError(ValueError):
    """Raised when a campaign's end date precedes its start date."""


def check_campaign_ownership(
    campaign: Campaign,
    user_id: int,
) -> bool:
    return campaign.user_id == user_id


def _validate_dates(
    start_date,
    end_date,
) -> None:
    if start_date is not None and end_date is not None and end_date < start_date:
        raise CampaignDateError("End date must be on or after start date")


def create_campaign(
    db: Session,
    user_id: int,
    campaign_data: CampaignCreate,
) -> Campaign:
    account_ids = set(campaign_data.social_account_ids)
    accounts = (
        db.query(SocialAccount)
        .filter(
            SocialAccount.user_id == user_id,
            SocialAccount.id.in_(account_ids),
        )
        .all()
        if account_ids
        else []
    )
    if len(accounts) != len(account_ids):
        raise ValueError("One or more social accounts do not belong to the user")

    values = campaign_data.model_dump(exclude={"social_account_ids"})
    campaign = Campaign(
        user_id=user_id,
        **values,
        social_accounts=accounts,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def get_campaigns(
    db: Session,
    user_id: int,
    search: Optional[str] = None,
    status: Optional[str] = None,
    objective: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[Campaign]:
    query = db.query(Campaign).filter(Campaign.user_id == user_id)
    if search:
        query = query.filter(Campaign.name.ilike(f"%{search.strip()}%"))
    if status:
        query = query.filter(Campaign.status == status)
    if objective:
        query = query.filter(Campaign.objective.ilike(f"%{objective.strip()}%"))
    if start_date:
        query = query.filter(Campaign.start_date >= start_date)
    if end_date:
        query = query.filter(Campaign.end_date <= end_date)
    return query.order_by(Campaign.created_at.desc()).all()


def get_campaign(
    db: Session,
    campaign_id: int,
    user_id: int,
) -> Campaign:
    campaign = (
        db.query(Campaign)
        .filter(
            Campaign.id == campaign_id,
            Campaign.user_id == user_id,
        )
        .first()
    )
    if not campaign:
        raise CampaignNotFoundError("Campaign not found")
    return campaign


def update_campaign(
    db: Session,
    campaign_id: int,
    user_id: int,
    campaign_data: CampaignUpdate,
) -> Campaign:
    campaign = get_campaign(db, campaign_id, user_id)
    updates = campaign_data.model_dump(exclude_unset=True)
    account_ids = updates.pop("social_account_ids", None)
    if account_ids is not None:
        accounts = (
            db.query(SocialAccount)
            .filter(
                SocialAccount.user_id == user_id,
                SocialAccount.id.in_(set(account_ids)),
            )
            .all()
        )
        if len(accounts) != len(set(account_ids)):
            raise ValueError("One or more social accounts do not belong to the user")
        campaign.social_accounts = accounts

    _validate_dates(
        updates.get("start_date", campaign.start_date),
        updates.get("end_date", campaign.end_date),
    )

    for field, value in updates.items():
        setattr(campaign, field, value)

    db.commit()
    db.refresh(campaign)
    return campaign


def delete_campaign(
    db: Session,
    campaign_id: int,
    user_id: int,
) -> None:
    campaign = get_campaign(db, campaign_id, user_id)
    db.delete(campaign)
    db.commit()


def change_campaign_status(
    db: Session,
    campaign_id: int,
    user_id: int,
    new_status: CampaignStatus,
) -> Campaign:
    campaign = get_campaign(db, campaign_id, user_id)
    campaign.status = new_status
    db.commit()
    db.refresh(campaign)
    return campaign