from collections import defaultdict
from datetime import date, datetime, timedelta
import csv
import logging
import os
from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query
import requests
from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.core.security import get_current_user
from app.database.postgres import SessionLocal
from app.models.campaign import Campaign
from app.models.follower_snapshot import FollowerSnapshot
from app.models.post import Post
from app.models.post_metric_snapshot import PostMetricSnapshot
from app.models.social_account import SocialAccount
from app.services.instagram_analytics import (
    capture_daily_follower_snapshots,
    get_instagram_post_metrics,
)


router = APIRouter(prefix="/analytics", tags=["Analytics"])
logger = logging.getLogger(__name__)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_analytics_data(
    db: Session,
    user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    campaign_id: int | None = None,
    platform: str | None = None,
):
    campaign_query = db.query(Campaign).filter(Campaign.user_id == user_id)
    if campaign_id is not None:
        campaign_query = campaign_query.filter(Campaign.id == campaign_id)
    campaigns = campaign_query.order_by(Campaign.created_at.desc()).all()

    if campaign_id is not None and not campaigns:
        raise HTTPException(status_code=404, detail="Campaign not found")

    post_query = db.query(Post).filter(
        Post.user_id == user_id,
        func.lower(Post.status) == "published",
    )
    if campaign_id is not None:
        post_query = post_query.filter(Post.campaign_id == campaign_id)
    if start_date is not None:
        post_query = post_query.filter(
            func.coalesce(Post.published_at, Post.created_at)
            >= datetime.combine(start_date, datetime.min.time())
        )
    if end_date is not None:
        post_query = post_query.filter(
            func.coalesce(Post.published_at, Post.created_at)
            < datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        )
    if platform:
        normalized_platform = _normalize_platform(platform)
        post_query = post_query.join(SocialAccount).filter(
            SocialAccount.user_id == user_id,
            func.lower(SocialAccount.platform).in_(
                _platform_filter_values(normalized_platform or platform)
            ),
        )

    posts = post_query.order_by(Post.published_at.asc().nullslast()).all()
    return campaigns, posts


def _metrics(
    campaigns: list[Campaign],
    posts: list[Post],
    instagram_metrics: dict | None = None,
) -> dict:
    values = {
        "reach": None,
        "impressions": None,
        "engagement": None,
        "engagement_rate": None,
        "clicks": None,
        "likes": None,
        "comments": None,
        "shares": None,
        "views": None,
    }
    instagram_metrics = instagram_metrics or get_instagram_post_metrics(posts)
    for name in ("reach", "impressions", "engagement", "likes", "comments"):
        values[name] = instagram_metrics[name]
    if values["engagement"] is None and (
        values["likes"] is not None and values["comments"] is not None
    ):
        values["engagement"] = values["likes"] + values["comments"]
    if values["reach"]:
        values["engagement_rate"] = round(
            (values["engagement"] or 0) / values["reach"] * 100,
            2,
        )
    return values


def _instagram_engagement(posts: list[Post]) -> dict:
    totals = {"likes": None, "comments": None}
    timeline: dict[str, dict] = {}
    failed_posts = 0
    api_version = os.getenv("INSTAGRAM_API_VERSION", "v26.0")

    for post in posts:
        account = post.social_account
        if (
            not account
            or account.user_id != post.user_id
            or (account.platform or "").strip().lower() != "instagram"
        ):
            continue
        if not account.access_token or not post.platform_post_id:
            failed_posts += 1
            continue

        media_url = (
            f"https://graph.instagram.com/{api_version}/"
            f"{post.platform_post_id}"
        )
        try:
            response = requests.get(
                media_url,
                params={
                    "fields": "like_count,comments_count",
                    "access_token": account.access_token,
                },
                timeout=10,
            )
            response.raise_for_status()
            media_metrics = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                "Could not fetch Instagram metrics for post %s (%s)",
                post.id,
                type(exc).__name__,
            )
            failed_posts += 1
            continue

        if not isinstance(media_metrics, dict):
            failed_posts += 1
            continue

        post_date = (post.published_at or post.created_at).date().isoformat()
        date_metrics = timeline.setdefault(post_date, {
            "date": post_date,
            "likes": None,
            "comments": None,
        })
        for response_key, metric_key in (
            ("like_count", "likes"),
            ("comments_count", "comments"),
        ):
            value = media_metrics.get(response_key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                totals[metric_key] = (totals[metric_key] or 0) + value
                date_metrics[metric_key] = (date_metrics[metric_key] or 0) + value

    return {
        **totals,
        "timeline": [timeline[key] for key in sorted(timeline)],
        "failed_posts": failed_posts,
        "available": totals["likes"] is not None or totals["comments"] is not None,
    }


def _performance_rows(campaigns: list[Campaign], posts: list[Post]) -> list[dict]:
    rows = []
    for campaign in campaigns:
        campaign_posts = [post for post in posts if post.campaign_id == campaign.id]
        metrics = _metrics([campaign], campaign_posts)
        platforms = sorted({
            post.social_account.platform
            for post in campaign_posts
            if post.social_account and post.social_account.user_id == campaign.user_id
        })
        rows.append({
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "platform": ", ".join(platforms) if platforms else "-",
            "posts": len(campaign_posts),
            **metrics,
            "status": campaign.status,
            "available": any(metrics[name] is not None for name in (
                "reach",
                "impressions",
                "engagement",
                "likes",
                "comments",
                "shares",
                "clicks",
                "views",
            )),
            "message": (
                "Current Instagram metrics are returned where the connected "
                "account and post support them. Historical data is not included."
            ),
        })
    return rows


def _filters(
    start_date: date | None,
    end_date: date | None,
    campaign_id: int | None,
    platform: str | None,
):
    return {
        "start_date": start_date,
        "end_date": end_date,
        "campaign_id": campaign_id,
        "platform": platform,
    }


def _normalize_platform(platform: str | None) -> str | None:
    if not platform:
        return None
    normalized = platform.strip().lower()
    if normalized in {"x", "x (twitter)", "twitter"}:
        return "X"
    known_platforms = {
        "facebook": "Facebook",
        "instagram": "Instagram",
        "linkedin": "LinkedIn",
        "youtube": "YouTube",
    }
    return known_platforms.get(normalized, platform.strip())


def _platform_filter_values(platform: str) -> list[str]:
    if platform == "X":
        return ["x", "x (twitter)", "twitter"]
    return [platform.lower()]


def _csv_safe_value(value) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{text}"
    return text


def _xlsx_column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _build_xlsx(fieldnames: list[str], rows: list[dict]) -> bytes:
    sheet_rows = [fieldnames, *[
        [row.get(fieldname, "") for fieldname in fieldnames]
        for row in rows
    ]]
    xml_rows = []
    for row_number, values in enumerate(sheet_rows, start=1):
        cells = []
        for column_number, value in enumerate(values, start=1):
            cell_reference = f"{_xlsx_column_name(column_number)}{row_number}"
            if isinstance(value, int) and not isinstance(value, bool):
                cell_xml = f'<c r="{cell_reference}"><v>{value}</v></c>'
            else:
                safe_value = escape("" if value is None else str(value))
                cell_xml = (
                    f'<c r="{cell_reference}" t="inlineStr"><is><t '
                    'xml:space="preserve">'
                    f"{safe_value}</t></is></c>"
                )
            cells.append(cell_xml)
        xml_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Analytics" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    package_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    workbook_buffer = BytesIO()
    with ZipFile(workbook_buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_relationships)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return workbook_buffer.getvalue()


@router.get("/export")
def export_analytics_report(
    start_date: date,
    end_date: date,
    platform: str | None = None,
    campaign_id: int | None = None,
    report_type: str = Query(
        default="post_details",
        pattern="^(post_details|platform_summary|campaign_summary)$",
    ),
    file_format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date.",
        )

    selected_platform = _normalize_platform(platform)
    allowed_platforms = {"Facebook", "Instagram", "LinkedIn", "YouTube", "X"}
    if selected_platform and selected_platform not in allowed_platforms:
        raise HTTPException(status_code=422, detail="Unsupported platform filter.")

    if campaign_id is not None:
        campaign_exists = (
            db.query(Campaign.id)
            .filter(
                Campaign.id == campaign_id,
                Campaign.user_id == current_user_id,
            )
            .first()
        )
        if not campaign_exists:
            raise HTTPException(status_code=404, detail="Campaign not found")

    status = func.lower(Post.status)
    event_timestamp = case(
        (
            status == "published",
            func.coalesce(Post.published_at, Post.created_at),
        ),
        (
            status == "scheduled",
            func.coalesce(Post.scheduled_at, Post.created_at),
        ),
        else_=Post.created_at,
    )
    event_date = func.date(event_timestamp)
    query = (
        db.query(
            Post.id.label("post_id"),
            event_date.label("event_date"),
            SocialAccount.platform.label("platform"),
            status.label("status"),
            Campaign.id.label("campaign_id"),
            Campaign.name.label("campaign_name"),
        )
        .select_from(Post)
        .outerjoin(
            SocialAccount,
            and_(
                Post.social_account_id == SocialAccount.id,
                SocialAccount.user_id == current_user_id,
            ),
        )
        .outerjoin(
            Campaign,
            and_(
                Post.campaign_id == Campaign.id,
                Campaign.user_id == current_user_id,
            ),
        )
        .filter(
            Post.user_id == current_user_id,
            event_date >= start_date,
            event_date <= end_date,
        )
    )
    if campaign_id is not None:
        query = query.filter(Post.campaign_id == campaign_id)
    if selected_platform:
        query = query.filter(
            func.lower(SocialAccount.platform).in_(
                _platform_filter_values(selected_platform)
            )
        )

    records = query.order_by(event_date.asc(), Post.id.asc()).all()
    post_ids = [record.post_id for record in records]
    latest_snapshot_by_post = {}
    if post_ids:
        snapshots = (
            db.query(PostMetricSnapshot)
            .filter(
                PostMetricSnapshot.post_id.in_(post_ids),
                PostMetricSnapshot.snapshot_date <= end_date,
            )
            .order_by(
                PostMetricSnapshot.snapshot_date.desc(),
                PostMetricSnapshot.captured_at.desc(),
            )
            .all()
        )
        for snapshot in snapshots:
            latest_snapshot_by_post.setdefault(snapshot.post_id, snapshot)

    rows = []
    if report_type == "post_details":
        for record in records:
            record_date = (
                record.event_date.isoformat()
                if isinstance(record.event_date, date)
                else str(record.event_date)[:10]
            )
            record_status = (record.status or "").lower()
            rows.append({
                "Date": record_date,
                "Platform": _normalize_platform(record.platform) or "Unknown",
                "Posts": 1,
                "Published Posts": int(record_status == "published"),
                "Scheduled Posts": int(record_status == "scheduled"),
                "Failed Posts": int(record_status == "failed"),
                "Status": record_status,
                "Campaign": record.campaign_name or "",
                "Campaigns": "",
                "_post_ids": [record.post_id],
            })
    elif report_type == "platform_summary":
        summaries = {}
        for record in records:
            platform_name = _normalize_platform(record.platform) or "Unknown"
            summary = summaries.setdefault(
                platform_name,
                {
                    "Posts": 0,
                    "Published Posts": 0,
                    "Scheduled Posts": 0,
                    "Failed Posts": 0,
                    "Campaigns": set(),
                    "_post_ids": set(),
                },
            )
            record_status = (record.status or "").lower()
            summary["Posts"] += 1
            if record_status in {"published", "scheduled", "failed"}:
                summary[f"{record_status.title()} Posts"] += 1
            if record.campaign_name:
                summary["Campaigns"].add(record.campaign_name)
            summary["_post_ids"].add(record.post_id)
        rows = [
            {
                "Date": f"{start_date.isoformat()} to {end_date.isoformat()}",
                "Platform": platform_name,
                "Posts": summary["Posts"],
                "Published Posts": summary["Published Posts"],
                "Scheduled Posts": summary["Scheduled Posts"],
                "Failed Posts": summary["Failed Posts"],
                "Status": "",
                "Campaign": "",
                "Campaigns": ", ".join(sorted(summary["Campaigns"])),
                "_post_ids": summary["_post_ids"],
            }
            for platform_name, summary in sorted(summaries.items())
        ]
    else:
        summaries = {}
        for record in records:
            if record.campaign_id is None:
                continue
            summary = summaries.setdefault(
                record.campaign_id,
                {
                    "Campaign": record.campaign_name or "",
                    "Posts": 0,
                    "Published Posts": 0,
                    "Scheduled Posts": 0,
                    "Failed Posts": 0,
                    "Platforms": set(),
                    "_post_ids": set(),
                },
            )
            record_status = (record.status or "").lower()
            summary["Posts"] += 1
            if record_status in {"published", "scheduled", "failed"}:
                summary[f"{record_status.title()} Posts"] += 1
            if record.platform:
                summary["Platforms"].add(
                    _normalize_platform(record.platform) or record.platform
                )
            summary["_post_ids"].add(record.post_id)
        rows = [
            {
                "Date": f"{start_date.isoformat()} to {end_date.isoformat()}",
                "Platform": ", ".join(sorted(summary["Platforms"])),
                "Posts": summary["Posts"],
                "Published Posts": summary["Published Posts"],
                "Scheduled Posts": summary["Scheduled Posts"],
                "Failed Posts": summary["Failed Posts"],
                "Status": "",
                "Campaign": summary["Campaign"],
                "Campaigns": "",
                "_post_ids": summary["_post_ids"],
            }
            for _, summary in sorted(summaries.items())
        ]

    unavailable_metrics = [
        "Engagement",
        "Likes",
        "Comments",
        "Shares",
        "Clicks",
        "Reach",
        "Impressions",
        "Views",
    ]
    fieldnames = [
        "Date",
        "Platform",
        "Posts",
        "Published Posts",
        "Scheduled Posts",
        "Failed Posts",
        "Status",
        "Campaign",
        "Campaigns",
        *unavailable_metrics,
    ]
    snapshot_metric_names = {
        "Reach": "reach",
        "Impressions": "impressions",
        "Engagement": "engagement",
        "Likes": "likes",
        "Comments": "comments",
        "Shares": "shares",
        "Clicks": "clicks",
        "Views": "views",
    }
    for row in rows:
        post_snapshot_ids = row.pop("_post_ids", [])
        if isinstance(post_snapshot_ids, set):
            post_snapshot_ids = sorted(post_snapshot_ids)
        for export_name, metric_name in snapshot_metric_names.items():
            values = []
            for post_id in post_snapshot_ids:
                snapshot = latest_snapshot_by_post.get(post_id)
                value = getattr(snapshot, metric_name, None) if snapshot else None
                if (
                    metric_name == "engagement"
                    and value is None
                    and snapshot
                    and snapshot.likes is not None
                    and snapshot.comments is not None
                ):
                    value = snapshot.likes + snapshot.comments
                if value is not None:
                    values.append(value)
            row[export_name] = (
                sum(values)
                if post_snapshot_ids and len(values) == len(post_snapshot_ids)
                else "Data unavailable"
            )

    csv_buffer = StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames, lineterminator="\r\n")
    writer.writeheader()
    base_filename = (
        f"socialpilot-analytics-{report_type}-{start_date.isoformat()}-"
        f"{end_date.isoformat()}"
    )
    if file_format == "xlsx":
        content = _build_xlsx(fieldnames, rows)
        media_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"{base_filename}.xlsx"
    else:
        for row in rows:
            writer.writerow({key: _csv_safe_value(row.get(key)) for key in fieldnames})
        content = csv_buffer.getvalue()
        media_type = "text/csv; charset=utf-8"
        filename = f"{base_filename}.csv"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/advanced")
def get_advanced_analytics(
    start_date: date | None = None,
    end_date: date | None = None,
    platform: str | None = None,
    campaign_id: int | None = None,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    range_end = end_date or date.today()
    range_start = start_date or range_end - timedelta(days=29)
    if range_start > range_end:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date.",
        )

    selected_platform = _normalize_platform(platform)
    allowed_platforms = {"Facebook", "Instagram", "LinkedIn", "YouTube", "X"}
    if selected_platform and selected_platform not in allowed_platforms:
        raise HTTPException(status_code=422, detail="Unsupported platform filter.")

    status = func.lower(Post.status)
    event_timestamp = case(
        (
            status == "published",
            func.coalesce(Post.published_at, Post.created_at),
        ),
        (
            status == "scheduled",
            func.coalesce(Post.scheduled_at, Post.created_at),
        ),
        else_=Post.created_at,
    )
    event_date = func.date(event_timestamp)
    query = (
        db.query(
            event_date.label("event_date"),
            status.label("status"),
            SocialAccount.platform.label("platform"),
            Campaign.id.label("campaign_id"),
            Campaign.name.label("campaign_name"),
            func.count(Post.id).label("post_count"),
        )
        .outerjoin(
            SocialAccount,
            and_(
                Post.social_account_id == SocialAccount.id,
                SocialAccount.user_id == current_user_id,
            ),
        )
        .outerjoin(
            Campaign,
            and_(
                Post.campaign_id == Campaign.id,
                Campaign.user_id == current_user_id,
            ),
        )
        .filter(
            Post.user_id == current_user_id,
            event_date >= range_start,
            event_date <= range_end,
        )
    )
    if campaign_id is not None:
        campaign_exists = (
            db.query(Campaign.id)
            .filter(
                Campaign.id == campaign_id,
                Campaign.user_id == current_user_id,
            )
            .first()
        )
        if not campaign_exists:
            raise HTTPException(status_code=404, detail="Campaign not found")
        query = query.filter(Post.campaign_id == campaign_id)

    if selected_platform:
        query = query.filter(
            func.lower(SocialAccount.platform).in_(
                _platform_filter_values(selected_platform)
            )
        )

    grouped_rows = query.group_by(
        event_date,
        status,
        SocialAccount.platform,
        Campaign.id,
        Campaign.name,
    ).all()

    status_counts = {"draft": 0, "scheduled": 0, "published": 0, "failed": 0}
    posts_by_date: dict[str, dict[str, int]] = {}
    platforms: dict[str, dict[str, int]] = {}
    campaigns: dict[int, dict] = {}
    total_posts = 0

    for row in grouped_rows:
        count = int(row.post_count)
        row_status = (row.status or "").lower()
        row_date = (
            row.event_date.isoformat()
            if isinstance(row.event_date, date)
            else str(row.event_date)[:10]
        )
        total_posts += count
        if row_status in status_counts:
            status_counts[row_status] += count

        date_bucket = posts_by_date.setdefault(
            row_date,
            {
                "total_posts": 0,
                "published_posts": 0,
                "scheduled_posts": 0,
                "failed_posts": 0,
            },
        )
        date_bucket["total_posts"] += count
        if row_status in {"published", "scheduled", "failed"}:
            date_bucket[f"{row_status}_posts"] += count

        platform_name = _normalize_platform(row.platform) if row.platform else None
        if platform_name:
            platform_row = platforms.setdefault(
                platform_name,
                {
                    "platform": platform_name,
                    "total_posts": 0,
                    "published_posts": 0,
                    "failed_posts": 0,
                },
            )
            platform_row["total_posts"] += count
            if row_status in {"published", "failed"}:
                platform_row[f"{row_status}_posts"] += count

        if row.campaign_id is not None:
            campaign_row = campaigns.setdefault(
                row.campaign_id,
                {
                    "campaign_id": row.campaign_id,
                    "campaign_name": row.campaign_name,
                    "total_posts": 0,
                    "published_posts": 0,
                    "scheduled_posts": 0,
                    "failed_posts": 0,
                },
            )
            campaign_row["total_posts"] += count
            if row_status in {"published", "scheduled", "failed"}:
                campaign_row[f"{row_status}_posts"] += count

    time_bucket = "day"
    if (range_end - range_start).days <= 366:
        posts_over_time = []
        current_date = range_start
        while current_date <= range_end:
            key = current_date.isoformat()
            posts_over_time.append({
                "date": key,
                **posts_by_date.get(
                    key,
                    {
                        "total_posts": 0,
                        "published_posts": 0,
                        "scheduled_posts": 0,
                        "failed_posts": 0,
                    },
                ),
            })
            current_date += timedelta(days=1)
    else:
        time_bucket = "month"
        monthly_posts: dict[str, dict[str, int]] = {}
        for event_day, counts in posts_by_date.items():
            event_month = date.fromisoformat(event_day).replace(day=1).isoformat()
            month_counts = monthly_posts.setdefault(
                event_month,
                {
                    "total_posts": 0,
                    "published_posts": 0,
                    "scheduled_posts": 0,
                    "failed_posts": 0,
                },
            )
            for key, value in counts.items():
                month_counts[key] += value

        posts_over_time = []
        current_month = range_start.replace(day=1)
        final_month = range_end.replace(day=1)
        while current_month <= final_month:
            key = current_month.isoformat()
            posts_over_time.append({
                "date": key,
                **monthly_posts.get(
                    key,
                    {
                        "total_posts": 0,
                        "published_posts": 0,
                        "scheduled_posts": 0,
                        "failed_posts": 0,
                    },
                ),
            })
            if current_month.month == 12:
                current_month = current_month.replace(
                    year=current_month.year + 1,
                    month=1,
                )
            else:
                current_month = current_month.replace(month=current_month.month + 1)

    return {
        "summary": {
            "total_posts": total_posts,
            "published_posts": status_counts["published"],
            "scheduled_posts": status_counts["scheduled"],
            "failed_posts": status_counts["failed"],
            "total_engagement": None,
            "engagement_available": False,
        },
        "posts_over_time": posts_over_time,
        "time_bucket": time_bucket,
        "engagement_over_time": {
            "available": False,
            "message": "Engagement history is not provided by connected accounts.",
            "data": [],
        },
        "platform_performance": sorted(
            platforms.values(),
            key=lambda item: item["total_posts"],
            reverse=True,
        ),
        "campaign_performance": sorted(
            campaigns.values(),
            key=lambda item: item["total_posts"],
            reverse=True,
        ),
        "metric_availability": {
            "reach": False,
            "impressions": False,
            "likes": False,
            "comments": False,
            "shares": False,
            "clicks": False,
            "views": False,
        },
        "filters": {
            "start_date": range_start,
            "end_date": range_end,
            "platform": selected_platform,
            "campaign_id": campaign_id,
        },
    }


@router.get("/overview")
def get_overview(
    start_date: date | None = None,
    end_date: date | None = None,
    campaign_id: int | None = None,
    platform: str | None = None,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaigns, posts = _get_analytics_data(
        db, current_user_id, start_date, end_date, campaign_id, platform
    )
    instagram_metrics = get_instagram_post_metrics(posts)
    return {
        **_metrics(campaigns, posts, instagram_metrics),
        "audience_growth": None,
        "metric_source": (
            "Instagram Graph API (current post metrics)"
            if instagram_metrics["available"]
            else "unavailable from connected platforms"
        ),
        "audience_data_available": False,
        "filters": _filters(start_date, end_date, campaign_id, platform),
    }


@router.get("/engagement")
def get_engagement(
    start_date: date | None = None,
    end_date: date | None = None,
    campaign_id: int | None = None,
    platform: str | None = None,
    metric: str = "reach",
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaigns, posts = _get_analytics_data(
        db, current_user_id, start_date, end_date, campaign_id, platform
    )
    instagram_metrics = get_instagram_post_metrics(posts)
    metrics = _metrics(campaigns, posts, instagram_metrics)
    metric_names = (
        "likes",
        "comments",
        "shares",
        "clicks",
        "views",
        "reach",
        "impressions",
        "engagement",
    )
    selected_metric = metric if metric in metric_names else "reach"
    selected_metric_available = metrics.get(selected_metric) is not None
    range_end = end_date or date.today()
    range_start = start_date or range_end - timedelta(days=29)
    post_ids = [post.id for post in posts]
    snapshots = (
        db.query(PostMetricSnapshot)
        .filter(
            PostMetricSnapshot.post_id.in_(post_ids),
            PostMetricSnapshot.snapshot_date >= range_start,
            PostMetricSnapshot.snapshot_date <= range_end,
        )
        .order_by(PostMetricSnapshot.snapshot_date.asc())
        .all()
        if post_ids
        else []
    )
    timeline_by_date: dict[date, dict] = {}
    for snapshot in snapshots:
        day = timeline_by_date.setdefault(
            snapshot.snapshot_date,
            {"date": snapshot.snapshot_date.isoformat()},
        )
        for metric_name in metric_names:
            value = getattr(snapshot, metric_name)
            if metric_name == "engagement" and value is None:
                likes = snapshot.likes
                comments = snapshot.comments
                if likes is not None and comments is not None:
                    value = likes + comments
            if value is not None:
                day[metric_name] = day.get(metric_name, 0) + value
    timeline = [timeline_by_date[key] for key in sorted(timeline_by_date)]
    history_available = any(
        point.get(selected_metric) is not None for point in timeline
    )

    if history_available:
        message = (
            "Historical Instagram metrics are daily snapshots. "
            "Other platforms are not included."
        )
    elif selected_metric_available:
        message = (
            "Current Instagram post metrics are available, but historical "
            "snapshots are not yet available. Daily collection has started; "
            "history will appear after snapshots are collected on multiple dates."
        )
    elif instagram_metrics["failed_posts"]:
        message = (
            f"Instagram insights could not be fetched for "
            f"{instagram_metrics['failed_posts']} post(s). Reconnect Instagram "
            "from Social Accounts and grant Instagram Insights permission, "
            "then refresh analytics."
        )
    else:
        message = (
            f"{selected_metric.title()} is not available for the selected posts "
            "or connected platforms."
        )

    return {
        "metrics": metrics,
        "timeline": timeline if history_available else [],
        "selected_metric": selected_metric,
        "available": selected_metric_available,
        "history_available": history_available,
        "last_synced_at": max(
            (snapshot.captured_at for snapshot in snapshots),
            default=None,
        ),
        "message": message,
        "metric_source": (
            "Instagram Graph API (current post insights)"
            if instagram_metrics["available"]
            else "unavailable from connected platforms"
        ),
        "filters": _filters(start_date, end_date, campaign_id, platform),
    }


@router.get("/audience")
def get_audience(
    start_date: date | None = None,
    end_date: date | None = None,
    campaign_id: int | None = None,
    platform: str | None = None,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_analytics_data(db, current_user_id, start_date, end_date, campaign_id, platform)
    selected_platform = _normalize_platform(platform)
    if selected_platform and selected_platform != "Instagram":
        return {
            "current_followers": None,
            "new_followers": None,
            "lost_followers": None,
            "net_growth": None,
            "growth_percentage": None,
            "available": False,
            "last_synced_at": None,
            "message": "Follower snapshots are currently collected for Instagram accounts only.",
            "filters": _filters(start_date, end_date, campaign_id, platform),
        }

    captured = capture_daily_follower_snapshots(db, user_id=current_user_id)
    range_end = end_date or date.today()
    range_start = start_date or range_end - timedelta(days=29)
    account_ids_query = db.query(SocialAccount.id).filter(
        SocialAccount.user_id == current_user_id,
        func.lower(SocialAccount.platform) == "instagram",
        SocialAccount.access_token.isnot(None),
        func.trim(SocialAccount.access_token) != "",
    )
    account_ids = [row[0] for row in account_ids_query.all()]
    snapshots = (
        db.query(FollowerSnapshot)
        .filter(
            FollowerSnapshot.social_account_id.in_(account_ids),
            FollowerSnapshot.snapshot_date >= range_start,
            FollowerSnapshot.snapshot_date <= range_end,
        )
        .order_by(FollowerSnapshot.snapshot_date.asc())
        .all()
        if account_ids
        else []
    )
    snapshots_by_account: dict[int, dict[date, int]] = defaultdict(dict)
    for snapshot in snapshots:
        snapshots_by_account[snapshot.social_account_id][
            snapshot.snapshot_date
        ] = snapshot.followers_count
    latest_snapshots = (
        db.query(FollowerSnapshot)
        .filter(
            FollowerSnapshot.social_account_id.in_(account_ids),
            FollowerSnapshot.snapshot_date <= range_end,
        )
        .order_by(FollowerSnapshot.snapshot_date.desc())
        .all()
        if account_ids
        else []
    )
    latest_by_account = {}
    for snapshot in latest_snapshots:
        latest_by_account.setdefault(
            snapshot.social_account_id,
            snapshot.followers_count,
        )
    latest_by_account.update({
        account_id: count
        for account_id, count in captured.items()
        if account_id in account_ids
    })
    current_followers = (
        sum(latest_by_account.values())
        if account_ids and len(latest_by_account) == len(account_ids)
        else None
    )

    daily_totals: dict[date, int] = defaultdict(int)
    if account_ids and all(
        account_id in snapshots_by_account for account_id in account_ids
    ):
        common_dates = set.intersection(
            *(set(snapshots_by_account[account_id]) for account_id in account_ids)
        )
        for snapshot_date in common_dates:
            if range_start <= snapshot_date <= range_end:
                daily_totals[snapshot_date] = sum(
                    snapshots_by_account[account_id][snapshot_date]
                    for account_id in account_ids
                )
    ordered_days = sorted(daily_totals)
    if len(ordered_days) >= 2:
        starting_followers = daily_totals[ordered_days[0]]
        ending_followers = daily_totals[ordered_days[-1]]
        net_growth = ending_followers - starting_followers
        new_followers = max(net_growth, 0)
        lost_followers = max(-net_growth, 0)
        growth_percentage = (
            round(net_growth / starting_followers * 100, 2)
            if starting_followers
            else None
        )
        available = True
        message = (
            f"Follower change measured from {ordered_days[0].isoformat()} "
            f"through {ordered_days[-1].isoformat()}."
        )
    else:
        new_followers = lost_followers = net_growth = growth_percentage = None
        available = False
        if not account_ids:
            message = (
                "Connect an Instagram account with follower insights enabled "
                "to track audience growth."
            )
        elif not latest_by_account:
            message = (
                "Could not retrieve follower counts from Instagram. Reconnect "
                "the account and confirm insights access."
            )
        else:
            message = (
                "Follower history is being collected. Audience growth will "
                "appear after snapshots are available on at least two dates."
            )

    return {
        "current_followers": current_followers,
        "new_followers": new_followers,
        "lost_followers": lost_followers,
        "net_growth": net_growth,
        "growth_percentage": growth_percentage,
        "available": available,
        "last_synced_at": max(
            (snapshot.snapshot_date for snapshot in latest_snapshots),
            default=None,
        ),
        "message": message,
        "filters": _filters(start_date, end_date, campaign_id, platform),
    }


@router.get("/campaigns")
def get_campaign_performance(
    start_date: date | None = None,
    end_date: date | None = None,
    campaign_id: int | None = None,
    platform: str | None = None,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaigns, posts = _get_analytics_data(
        db, current_user_id, start_date, end_date, campaign_id, platform
    )
    return {
        "campaigns": _performance_rows(campaigns, posts),
        "metric_source": "estimated from published post and platform data",
        "filters": _filters(start_date, end_date, campaign_id, platform),
    }


@router.get("/campaigns/{campaign_id}")
def get_campaign_performance_detail(
    campaign_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    platform: str | None = None,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaigns, posts = _get_analytics_data(
        db, current_user_id, start_date, end_date, campaign_id, platform
    )
    return _performance_rows(campaigns, posts)[0]


@router.get("/comparison")
def get_campaign_comparison(
    campaign_ids: list[int] = Query(default=[]),
    start_date: date | None = None,
    end_date: date | None = None,
    platform: str | None = None,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaign_query = db.query(Campaign).filter(Campaign.user_id == current_user_id)
    if campaign_ids:
        campaign_query = campaign_query.filter(Campaign.id.in_(campaign_ids))
    campaigns = campaign_query.order_by(Campaign.created_at.desc()).all()
    if campaign_ids and len(campaigns) != len(set(campaign_ids)):
        raise HTTPException(status_code=404, detail="One or more campaigns not found")

    posts_query = db.query(Post).filter(
        Post.user_id == current_user_id,
        func.lower(Post.status) == "published",
    )
    if campaign_ids:
        posts_query = posts_query.filter(Post.campaign_id.in_(campaign_ids))
    if start_date:
        posts_query = posts_query.filter(
            Post.published_at >= datetime.combine(start_date, datetime.min.time())
        )
    if end_date:
        posts_query = posts_query.filter(
            Post.published_at < datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        )
    if platform:
        normalized_platform = _normalize_platform(platform)
        posts_query = posts_query.join(SocialAccount).filter(
            SocialAccount.user_id == current_user_id,
            func.lower(SocialAccount.platform).in_(
                _platform_filter_values(normalized_platform or platform)
            ),
        )
    posts = posts_query.all()
    rows = _performance_rows(campaigns, posts)
    for row in rows:
        row["audience_growth"] = None

    return {
        "campaigns": rows,
        "comparison_metrics": ["reach", "engagement", "clicks", "impressions", "audience_growth"],
        "audience_data_available": False,
    }


@router.get("/roi")
def get_roi_report(
    campaign_id: int | None = None,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    campaign_query = db.query(Campaign).filter(Campaign.user_id == current_user_id)
    if campaign_id is not None:
        campaign_query = campaign_query.filter(Campaign.id == campaign_id)
    campaigns = campaign_query.order_by(Campaign.created_at.desc()).all()
    if campaign_id is not None and not campaigns:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return {
        "available": False,
        "message": "Revenue is not tracked, so profit and ROI cannot be calculated.",
        "campaigns": [
            {
                "campaign_id": campaign.id,
                "campaign_name": campaign.name,
                "campaign_cost": float(campaign.budget) if campaign.budget is not None else None,
                "revenue": None,
                "profit": None,
                "roi": None,
            }
            for campaign in campaigns
        ],
    }