import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader, StatusBadge, EmptyState } from "../components/UI";
import "./Analytics.css";

const API_URL = "http://127.0.0.1:8000";
const METRICS = ["likes", "comments", "shares", "clicks", "views", "reach", "impressions"];
const RANGES = { "7d": "Last 7 days", "30d": "Last 30 days", "3m": "Last 3 months", custom: "Custom date range" };
const PLATFORM_OPTIONS = ["Facebook", "Instagram", "LinkedIn", "YouTube", "X"];
const number = (value) => value == null ? "Data unavailable" : Number(value).toLocaleString();

function Analytics() {
  const navigate = useNavigate();
  const [campaigns, setCampaigns] = useState([]);
  const [overview, setOverview] = useState(null);
  const [advanced, setAdvanced] = useState(null);
  const [engagement, setEngagement] = useState(null);
  const [audience, setAudience] = useState(null);
  const [performance, setPerformance] = useState([]);
  const [comparison, setComparison] = useState([]);
  const [roi, setRoi] = useState(null);
  const [selectedCampaigns, setSelectedCampaigns] = useState([]);
  const [filters, setFilters] = useState({ range: "30d", campaign: "all", platform: "all", metric: "reach" });
  const [customDates, setCustomDates] = useState(() => {
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - 29);
    return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const [exportNotice, setExportNotice] = useState("");
  const [reportType, setReportType] = useState("post_details");
  const [exportFormat, setExportFormat] = useState("csv");

  function updateFilters(updater) {
    setLoading(true);
    setError("");
    setFilters(updater);
  }

  function updateCustomDate(field, value) {
    const start = field === "start" ? value : customDates.start;
    const end = field === "end" ? value : customDates.end;
    setLoading(Boolean(start && end));
    setError("");
    setCustomDates((current) => ({ ...current, [field]: value }));
  }

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      navigate("/login", { replace: true });
      return;
    }
    const headers = { Authorization: `Bearer ${token}` };
    Promise.all([
      fetch(`${API_URL}/campaigns`, { headers }),
      fetch(`${API_URL}/social-accounts/`, { headers }),
    ])
      .then(async ([campaignResponse, accountResponse]) => {
        if (campaignResponse.status === 401 || accountResponse.status === 401) {
          localStorage.removeItem("access_token");
          navigate("/login", { replace: true });
          return null;
        }
        if (!campaignResponse.ok || !accountResponse.ok) throw new Error("Could not load campaigns and connected accounts.");
        return Promise.all([campaignResponse.json(), accountResponse.json()]);
      })
      .then((data) => {
        if (!data) return;
        setCampaigns(data[0]);
      })
      .catch((requestError) => setError(requestError.message));
  }, [navigate]);

  const dates = useMemo(() => {
    const end = new Date();
    if (filters.range === "custom") return customDates;
    const start = new Date(end);
    if (filters.range === "3m") {
      start.setMonth(start.getMonth() - 3);
    } else {
      start.setDate(start.getDate() - Number(filters.range.replace("d", "")) + 1);
    }
    return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
  }, [customDates, filters.range]);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) return;
    if (!dates.start || !dates.end) return;
    const query = new URLSearchParams({ start_date: dates.start, end_date: dates.end });
    if (filters.campaign !== "all") query.set("campaign_id", filters.campaign);
    if (filters.platform !== "all") query.set("platform", filters.platform);
    const advancedQuery = new URLSearchParams(query);
    const headers = { Authorization: `Bearer ${token}` };

    const requests = [
      { name: "overview", request: fetch(`${API_URL}/analytics/overview?${query}`, { headers }), update: setOverview },
      { name: "engagement", request: fetch(`${API_URL}/analytics/engagement?${query}&metric=${filters.metric}`, { headers }), update: setEngagement },
      { name: "audience", request: fetch(`${API_URL}/analytics/audience?${query}`, { headers }), update: setAudience },
      { name: "campaign performance", request: fetch(`${API_URL}/analytics/campaigns?${query}`, { headers }), update: (data) => setPerformance(data.campaigns || []) },
      { name: "ROI", request: fetch(`${API_URL}/analytics/roi${filters.campaign === "all" ? "" : `?campaign_id=${filters.campaign}`}`, { headers }), update: setRoi },
      { name: "post analytics", request: fetch(`${API_URL}/analytics/advanced?${advancedQuery}`, { headers }), update: setAdvanced },
    ];

    Promise.all(requests.map(async ({ name, request, update }) => {
      try {
        const response = await request;
        if (response.status === 401) return { name, unauthorized: true };
        if (!response.ok) return { name, error: true };
        return { name, update, data: await response.json() };
      } catch {
        return { name, error: true };
      }
    }))
      .then((results) => {
        if (results.some((result) => result.unauthorized)) {
          localStorage.removeItem("access_token");
          navigate("/login", { replace: true });
          return;
        }
        results.forEach((result) => {
          if (result.data) result.update(result.data);
        });
        const failed = results.filter((result) => result.error).map((result) => result.name);
        setError(failed.length ? `Could not load ${failed.join(", ")} analytics data.` : "");
      })
      .finally(() => setLoading(false));
  }, [dates, filters.campaign, filters.metric, filters.platform, navigate]);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token || !dates.start || !dates.end) return;
    if (!selectedCampaigns.length) {
      return;
    }
    const query = new URLSearchParams();
    selectedCampaigns.forEach((id) => query.append("campaign_ids", id));
    if (filters.platform !== "all") query.set("platform", filters.platform);
    const range = new URLSearchParams({ start_date: dates.start, end_date: dates.end });
    const comparisonQuery = new URLSearchParams(query);
    range.forEach((value, key) => comparisonQuery.set(key, value));
    fetch(`${API_URL}/analytics/comparison?${comparisonQuery}`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (response) => {
        if (!response.ok) return { campaigns: [] };
        return response.json();
      })
      .then((data) => setComparison(data.campaigns || []))
      .catch(() => setComparison([]));
  }, [dates, filters.platform, selectedCampaigns]);

  const timeline = engagement?.timeline || [];
  const comparisonRows = selectedCampaigns.length ? comparison : [];
  const postTimeline = advanced?.posts_over_time || [];
  const postTimelinePeak = Math.max(1, ...postTimeline.map((point) => point.total_posts));
  const postTimelineTickInterval = Math.max(1, Math.ceil(postTimeline.length / 6));
  const chartMetric = filters.metric;
  const peak = Math.max(1, ...timeline.map((point) => point[chartMetric] || 0));
  const metricLabel = chartMetric.charAt(0).toUpperCase() + chartMetric.slice(1);

  function toggleCampaign(id) {
    setSelectedCampaigns((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function exportReport() {
    const token = localStorage.getItem("access_token");
    if (!token) {
      navigate("/login", { replace: true });
      return;
    }

    setExporting(true);
    setExportError("");
    setExportNotice("");
    const query = new URLSearchParams({
      start_date: dates.start,
      end_date: dates.end,
      report_type: reportType,
      file_format: exportFormat,
    });
    if (filters.platform !== "all") query.set("platform", filters.platform);
    if (filters.campaign !== "all") query.set("campaign_id", filters.campaign);

    try {
      const response = await fetch(`${API_URL}/analytics/export?${query}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.status === 401) {
        localStorage.removeItem("access_token");
        navigate("/login", { replace: true });
        return;
      }
      if (!response.ok) {
        let message = `Could not export report (HTTP ${response.status}).`;
        try {
          const body = await response.json();
          if (typeof body.detail === "string") message = body.detail;
        } catch {
          // Use the HTTP status message if the server did not return JSON.
        }
        throw new Error(message);
      }

      const report = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
        || `socialpilot-analytics-report.${exportFormat}`;
      const downloadUrl = URL.createObjectURL(report);
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(downloadUrl);
      setExportNotice(`${exportFormat.toUpperCase()} report downloaded using the current date, platform, and campaign filters.`);
    } catch (exportRequestError) {
      setExportError(exportRequestError instanceof Error ? exportRequestError.message : "Could not export analytics report.");
    } finally {
      setExporting(false);
    }
  }

  return <>
    <div className="workspace-page analytics-page">
      <PageHeader eyebrow="MEASURE PERFORMANCE" title="Analytics" description="Post activity and available performance data for the selected period." className="analytics-heading" actions={<span className="metric-source">Only recorded metrics are shown</span>} />

      <section className="analytics-filters" aria-label="Analytics filters">
        <label><span>Date range</span><select value={filters.range} onChange={(event) => updateFilters((current) => ({ ...current, range: event.target.value }))}>
          {Object.entries(RANGES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        {filters.range === "custom" && <>
          <label><span>Start date</span><input type="date" value={customDates.start} max={customDates.end} onChange={(event) => updateCustomDate("start", event.target.value)} /></label>
          <label><span>End date</span><input type="date" value={customDates.end} min={customDates.start} onChange={(event) => updateCustomDate("end", event.target.value)} /></label>
        </>}
        <label><span>Campaign</span><select value={filters.campaign} onChange={(event) => updateFilters((current) => ({ ...current, campaign: event.target.value }))}>
          <option value="all">All campaigns</option>{campaigns.map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name}</option>)}
        </select></label>
        <label><span>Platform</span><select value={filters.platform} onChange={(event) => updateFilters((current) => ({ ...current, platform: event.target.value }))}>
          <option value="all">All platforms</option>{PLATFORM_OPTIONS.map((platform) => <option key={platform} value={platform}>{platform}</option>)}
        </select></label>
        <label><span>Metric</span><select value={filters.metric} onChange={(event) => updateFilters((current) => ({ ...current, metric: event.target.value }))}>
          {METRICS.map((metric) => <option key={metric} value={metric}>{metric[0].toUpperCase() + metric.slice(1)}</option>)}
        </select></label>
      </section>

      <section className="analytics-export-panel" aria-label="Export analytics report">
        <div className="analytics-export-description">
          <strong>Export report</strong>
          <span>Uses the current date range, platform, and campaign filters.</span>
        </div>
        <label htmlFor="analytics-report-type">
          <span>Report type</span>
          <select
            id="analytics-report-type"
            value={reportType}
            onChange={(event) => {
              setReportType(event.target.value);
              setExportError("");
              setExportNotice("");
            }}
          >
            <option value="post_details">Post details</option>
            <option value="platform_summary">Platform summary</option>
            <option value="campaign_summary">Campaign summary</option>
          </select>
        </label>
        <label htmlFor="analytics-export-format">
          <span>File format</span>
          <select
            id="analytics-export-format"
            value={exportFormat}
            onChange={(event) => {
              setExportFormat(event.target.value);
              setExportError("");
              setExportNotice("");
            }}
          >
            <option value="csv">CSV (.csv)</option>
            <option value="xlsx">Excel (.xlsx)</option>
          </select>
        </label>
        <button type="button" className="analytics-export-button" onClick={exportReport} disabled={exporting || !dates.start || !dates.end}>
          {exporting ? `Preparing ${exportFormat.toUpperCase()}...` : "Export Report"}
        </button>
        {(exportError || exportNotice) && <p className={`analytics-export-message${exportError ? " is-error" : " is-success"}`} role={exportError ? "alert" : "status"}>
          {exportError || exportNotice}
        </p>}
      </section>

      {error && <p className="analytics-error" role="alert">{error}</p>}
      {loading && <p className="analytics-loading">Updating analytics...</p>}

      <section className="analytics-kpis advanced-kpis" aria-label="Post analytics summary">
        {[
          ["Total posts", advanced?.summary?.total_posts],
          ["Published posts", advanced?.summary?.published_posts],
          ["Scheduled posts", advanced?.summary?.scheduled_posts],
          ["Failed posts", advanced?.summary?.failed_posts],
          ["Instagram likes", engagement?.metrics?.likes],
          ["Total engagement", overview?.engagement],
        ].map(([label, value]) => <article className="analytics-kpi" key={label}>
          <span>{label}</span><strong>{number(value)}</strong>
        </article>)}
      </section>

      <section className="analytics-advanced-grid" aria-label="Advanced analytics charts">
        <article className="analytics-panel advanced-chart-card posts-over-time-card">
          <div className="analytics-panel-heading"><div><p className="eyebrow">POST ACTIVITY</p><h2>Posts over time</h2></div><span>{dates.start} – {dates.end}</span></div>
          {postTimeline.length ? <div className="advanced-time-chart" role="img" aria-label="Posts over time">
            {postTimeline.map((point, index) => {
              const showDate = index === 0
                || index === postTimeline.length - 1
                || index % postTimelineTickInterval === 0;
              const dateLabel = advanced.time_bucket === "month"
                ? point.date.slice(0, 7)
                : point.date.slice(8, 10);
              return <div className="advanced-time-column" key={point.date} title={`${point.date}: ${point.total_posts} posts`}>
                <span style={{ height: `${Math.max(point.total_posts ? 5 : 0, (point.total_posts / postTimelinePeak) * 100)}%` }} />
                <small aria-hidden={!showDate}>{showDate ? dateLabel : ""}</small>
              </div>;
            })}
          </div> : <p className="analytics-empty">No post records match this date range.</p>}
          <div className="advanced-chart-legend"><span>Total posts</span><span>Published and scheduled dates use their actual event timestamps.</span></div>
        </article>

        <article className="analytics-panel advanced-chart-card">
          <div className="analytics-panel-heading"><div><p className="eyebrow">ENGAGEMENT</p><h2>Engagement over time</h2></div></div>
          <p className="data-note">Historical engagement charts use daily provider snapshots. Current Instagram likes and comments are shown in the summary when available.</p>
        </article>

        <article className="analytics-panel advanced-chart-card">
          <div className="analytics-panel-heading"><div><p className="eyebrow">PLATFORMS</p><h2>Platform comparison</h2></div></div>
          {advanced?.platform_performance?.length ? <div className="advanced-bar-list">
            {advanced.platform_performance.map((row) => {
              const maxPosts = Math.max(1, ...advanced.platform_performance.map((item) => item.total_posts));
              return <div className="advanced-bar-row" key={row.platform}>
                <div className="advanced-bar-label"><strong>{row.platform}</strong><span>{row.total_posts} posts</span></div>
                <div className="advanced-bar-track"><span style={{ width: `${(row.total_posts / maxPosts) * 100}%` }} /></div>
                <small>{row.published_posts} published · {row.failed_posts} failed · engagement: Data unavailable</small>
              </div>;
            })}
          </div> : <p className="analytics-empty">No platform post records match these filters.</p>}
        </article>

        <article className="analytics-panel advanced-chart-card">
          <div className="analytics-panel-heading"><div><p className="eyebrow">CAMPAIGNS</p><h2>Campaign performance</h2></div></div>
          {advanced?.campaign_performance?.length ? <div className="advanced-bar-list">
            {advanced.campaign_performance.map((row) => {
              const maxPosts = Math.max(1, ...advanced.campaign_performance.map((item) => item.total_posts));
              return <div className="advanced-bar-row" key={row.campaign_id}>
                <div className="advanced-bar-label"><strong>{row.campaign_name}</strong><span>{row.total_posts} posts</span></div>
                <div className="advanced-bar-track"><span style={{ width: `${(row.total_posts / maxPosts) * 100}%` }} /></div>
                <small>{row.published_posts} published · {row.scheduled_posts} scheduled · {row.failed_posts} failed · engagement: Data unavailable</small>
              </div>;
            })}
          </div> : <p className="analytics-empty">No campaign post records match these filters.</p>}
        </article>
      </section>

      <section className="analytics-kpis" aria-label="Performance overview">
        {[["Total reach", overview?.reach], ["Impressions", overview?.impressions], ["Engagement", overview?.engagement], ["Engagement rate", overview?.engagement_rate == null ? null : `${overview.engagement_rate}%`], ["Total clicks", overview?.clicks], ["Audience growth", audience?.available ? audience.net_growth : null]].map(([label, value]) => <article className="analytics-kpi" key={label}>
          <span>{label}</span><strong>{typeof value === "string" ? value : number(value)}</strong>
        </article>)}
      </section>

      <section className="analytics-panel engagement-panel">
        <div className="analytics-panel-heading"><div><p className="eyebrow">ENGAGEMENT ANALYTICS</p><h2>{metricLabel} over time</h2></div><span>{engagement?.last_synced_at ? `Last synced ${new Date(engagement.last_synced_at).toLocaleString()}` : RANGES[filters.range]}</span></div>
        {timeline.length ? <div className="timeline-chart" role="img" aria-label={`${metricLabel} over time`}>
          {timeline.map((point) => <div className="timeline-column" key={point.date}>
            <strong>{number(point[chartMetric])}</strong><div className="timeline-track"><span style={{ height: `${Math.max(4, (point[chartMetric] / peak) * 100)}%` }} /></div><small>{point.date.slice(5)}</small>
          </div>)}
        </div> : <p className="analytics-empty">{engagement?.message || "Data unavailable. Connected platforms do not provide engagement history."}</p>}
        <div className="metric-legend">{METRICS.map((metric) => <button key={metric} className={metric === chartMetric ? "selected" : ""} onClick={() => updateFilters((current) => ({ ...current, metric }))}>{metric}</button>)}</div>
        {timeline.length > 0 && <div className="metric-breakdown" aria-label="All engagement metrics">
          {METRICS.map((metric) => {
            const metricPeak = Math.max(1, ...timeline.map((point) => point[metric] || 0));
            return <article key={metric} className="metric-breakdown-item"><span>{metric}</span><div>{timeline.map((point) => <i key={point.date} title={`${point.date}: ${number(point[metric])}`} style={{ height: `${Math.max(4, (point[metric] / metricPeak) * 100)}%` }} />)}</div></article>;
          })}
        </div>}
      </section>

      <section className="analytics-panel audience-panel">
        <div className="analytics-panel-heading"><div><p className="eyebrow">AUDIENCE</p><h2>Audience growth</h2></div></div>
        <div className="audience-values">
          {[["Current followers", audience?.current_followers], ["New followers", audience?.new_followers], ["Lost followers", audience?.lost_followers], ["Net growth", audience?.net_growth], ["Growth", audience?.growth_percentage == null ? null : `${audience.growth_percentage}%`]].map(([label, value]) => <div key={label}><span>{label}</span><strong>{typeof value === "string" ? value : number(value)}</strong></div>)}
        </div>
        {!audience?.available && <p className="data-note">{audience?.message || "Follower history is not available yet."}</p>}
        {audience?.last_synced_at && <p className="data-note">Last follower snapshot: {new Date(audience.last_synced_at).toLocaleDateString()}</p>}
      </section>

      <section className="analytics-panel performance-panel">
        <div className="analytics-panel-heading"><div><p className="eyebrow">PLATFORM PERFORMANCE</p><h2>Results by platform</h2></div><span>Post records</span></div>
        {advanced?.platform_performance?.length ? <div className="platform-performance-list">{advanced.platform_performance.map((row) => <article key={row.platform}>
          <div className="platform-performance-heading"><strong>{row.platform}</strong><span>{number(row.total_posts)} posts</span></div>
          <div className="platform-performance-track"><span style={{ width: `${Math.max(2, (row.total_posts / Math.max(...advanced.platform_performance.map((item) => item.total_posts), 1)) * 100)}%` }} /></div>
          <small>{row.published_posts} published · {row.failed_posts} failed · Engagement: Data unavailable</small>
        </article>)}</div> : <p className="analytics-empty">No platform post records match these filters.</p>}
      </section>

      <section className="analytics-panel performance-panel">
        <div className="analytics-panel-heading"><div><p className="eyebrow">CAMPAIGN PERFORMANCE</p><h2>Campaign results</h2></div><span>Published posts only · real post records</span></div>
        <div className="analytics-table-wrap"><table><thead><tr><th>Campaign</th><th>Platform</th><th>Posts</th><th>Reach</th><th>Engagement</th><th>Clicks</th><th>Engagement rate</th><th>Status</th></tr></thead>
          <tbody>{performance.map((row) => <tr key={row.campaign_id}><td>{row.campaign_name}</td><td>{row.platform}</td><td>{row.posts}</td><td>{number(row.reach)}</td><td>{number(row.engagement)}</td><td>{number(row.clicks)}</td><td>{row.engagement_rate == null ? "Data unavailable" : `${row.engagement_rate}%`}</td><td><StatusBadge value={row.status} /></td></tr>)}</tbody>
        </table></div>
        {!performance.length && <EmptyState title="No campaign performance" description="No published results match these filters." />}
      </section>

      <section className="analytics-panel comparison-panel">
        <div className="analytics-panel-heading"><div><p className="eyebrow">COMPARE CAMPAIGNS</p><h2>Campaign comparison</h2></div><span>Select campaigns to compare</span></div>
        <div className="campaign-selector">{campaigns.map((campaign) => <label key={campaign.id}><input type="checkbox" checked={selectedCampaigns.includes(campaign.id)} onChange={() => toggleCampaign(campaign.id)} /><span>{campaign.name}</span></label>)}</div>
        <div className="analytics-table-wrap"><table><thead><tr><th>Campaign</th><th>Reach</th><th>Engagement</th><th>Clicks</th><th>Impressions</th><th>Audience growth</th></tr></thead>
          <tbody>{comparisonRows.map((row) => <tr key={row.campaign_id}><td>{row.campaign_name}</td><td>{number(row.reach)}</td><td>{number(row.engagement)}</td><td>{number(row.clicks)}</td><td>{number(row.impressions)}</td><td>{number(row.audience_growth)}</td></tr>)}</tbody>
        </table></div>
        {!comparisonRows.length && <p className="analytics-empty">Select one or more campaigns to compare.</p>}
      </section>

      <section className="analytics-panel roi-panel">
        <div className="analytics-panel-heading"><div><p className="eyebrow">ROI REPORT</p><h2>Campaign costs and returns</h2></div></div>
        {roi?.campaigns?.some((item) => item.campaign_cost != null) ? <div className="analytics-table-wrap"><table><thead><tr><th>Campaign</th><th>Campaign cost</th><th>Revenue</th><th>Profit</th><th>ROI</th></tr></thead><tbody>
          {roi.campaigns.filter((item) => item.campaign_cost != null).map((item) => <tr key={item.campaign_id}><td>{item.campaign_name}</td><td>{Number(item.campaign_cost).toLocaleString()}</td><td>{number(item.revenue)}</td><td>{number(item.profit)}</td><td>{number(item.roi)}</td></tr>)}
        </tbody></table></div> : <p className="analytics-empty">No campaign cost data is available.</p>}
        {!roi?.available && <p className="data-note">{roi?.message || "Revenue tracking is not available yet. ROI will appear when financial data is connected."}</p>}
      </section>
    </div>
  </>;
}

export default Analytics;