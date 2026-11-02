import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader, StatusBadge, EmptyState } from "../components/UI";
import "./Reports.css";

const API_URL = "http://127.0.0.1:8000";
const PERIODS = { "7d": "Last 7 days", "30d": "Last 30 days", "90d": "Last 90 days" };
const formatMetric = (value) => value == null ? "Not available" : Number(value).toLocaleString();

function Reports() {
  const navigate = useNavigate();
  const [campaigns, setCampaigns] = useState([]);
  const [platforms, setPlatforms] = useState([]);
  const [overview, setOverview] = useState(null);
  const [performance, setPerformance] = useState([]);
  const [audience, setAudience] = useState(null);
  const [roi, setRoi] = useState(null);
  const [filters, setFilters] = useState({ period: "30d", campaign: "all", platform: "all" });
  const [activeReport, setActiveReport] = useState("campaigns");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(null);

  function updateFilters(updater) {
    setLoading(true);
    setError("");
    setFilters(updater);
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
        if ([campaignResponse, accountResponse].some((response) => response.status === 401)) {
          localStorage.removeItem("access_token");
          navigate("/login", { replace: true });
          return null;
        }
        if (!campaignResponse.ok || !accountResponse.ok) throw new Error("Unable to load report filters.");
        return Promise.all([campaignResponse.json(), accountResponse.json()]);
      })
      .then((data) => {
        if (!data) return;
        setCampaigns(data[0]);
        setPlatforms([...new Set(data[1].map((account) => account.platform).filter(Boolean))]);
      })
      .catch((requestError) => setError(requestError.message));
  }, [navigate]);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) return;
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - Number(filters.period.replace("d", "")) + 1);
    const query = new URLSearchParams({ start_date: start.toISOString().slice(0, 10), end_date: end.toISOString().slice(0, 10) });
    if (filters.campaign !== "all") query.set("campaign_id", filters.campaign);
    if (filters.platform !== "all") query.set("platform", filters.platform);
    const headers = { Authorization: `Bearer ${token}` };
    const requests = [
      { name: "overview", request: fetch(`${API_URL}/analytics/overview?${query}`, { headers }), update: setOverview },
      { name: "campaign", request: fetch(`${API_URL}/analytics/campaigns?${query}`, { headers }), update: (data) => setPerformance(data.campaigns || []) },
      { name: "audience", request: fetch(`${API_URL}/analytics/audience?${query}`, { headers }), update: setAudience },
      { name: "ROI", request: fetch(`${API_URL}/analytics/roi${filters.campaign === "all" ? "" : `?campaign_id=${filters.campaign}`}`, { headers }), update: setRoi },
    ];
    Promise.all(requests.map(async ({ name, request, update }) => {
      try {
        const response = await request;
        if (response.status === 401) return { unauthorized: true };
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
        setError(failed.length ? `Unable to load ${failed.join(", ")} report data.` : "");
      })
      .finally(() => setLoading(false));
  }, [filters.campaign, filters.period, filters.platform, navigate]);

  async function exportCampaignReport(campaignId, campaignName) {
    const token = localStorage.getItem("access_token");
    setExporting(campaignId);
    setError("");
    try {
      const response = await fetch(`${API_URL}/campaigns/${campaignId}/report`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await response.json();
      if (response.status === 401) {
        localStorage.removeItem("access_token");
        navigate("/login", { replace: true });
        return;
      }
      if (!response.ok) throw new Error(data.detail || "Unable to export report.");
      const file = new Blob([data.report_text || JSON.stringify(data, null, 2)], { type: "text/plain" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(file);
      link.download = `${campaignName.trim().replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-report.txt`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (requestError) {
      setError(requestError.message || "Unable to export report.");
    } finally {
      setExporting(null);
    }
  }

  const tabs = ["campaigns", "engagement", "audience", "roi"];
  const summary = [
    ["Reach", overview?.reach],
    ["Impressions", overview?.impressions],
    ["Engagement", overview?.engagement],
    ["Engagement rate", overview?.engagement_rate == null ? null : `${overview.engagement_rate}%`],
  ];

  return <div className="workspace-page reports-page">
    <PageHeader eyebrow="REPORTING" title="Reports" description="Review campaign outcomes and export campaign reports." className="reports-heading" />
    <section className="reports-filters" aria-label="Report filters">
      <label><span>Date range</span><select value={filters.period} onChange={(event) => updateFilters((current) => ({ ...current, period: event.target.value }))}>{Object.entries(PERIODS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label><span>Campaign</span><select value={filters.campaign} onChange={(event) => updateFilters((current) => ({ ...current, campaign: event.target.value }))}><option value="all">All campaigns</option>{campaigns.map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name}</option>)}</select></label>
      <label><span>Platform</span><select value={filters.platform} onChange={(event) => updateFilters((current) => ({ ...current, platform: event.target.value }))}><option value="all">All platforms</option>{platforms.map((platform) => <option key={platform} value={platform}>{platform}</option>)}</select></label>
    </section>
    {error && <p className="reports-error" role="alert">{error}</p>}
    {loading && <p className="reports-empty">Updating report data...</p>}
    <section className="reports-summary" aria-label="Report summary">{summary.map(([label, value]) => <article key={label}><span>{label}</span><strong>{value == null ? "Not tracked" : typeof value === "number" ? value.toLocaleString() : value}</strong></article>)}</section>
    <p className="reports-note">Live engagement insights are currently available for Instagram posts when returned by Instagram. Other platforms’ engagement data and revenue are not currently tracked. Audience growth appears after follower snapshots have been collected on at least two dates.</p>
    <nav className="report-tabs" aria-label="Report type">{tabs.map((tab) => <button key={tab} className={activeReport === tab ? "active" : ""} onClick={() => setActiveReport(tab)}>{tab[0].toUpperCase() + tab.slice(1)} report</button>)}</nav>

    {activeReport === "campaigns" && <section className="report-content"><header><div><p className="eyebrow">CAMPAIGN REPORTS</p><h2>Campaign performance</h2></div></header><div className="reports-table-wrap"><table><thead><tr><th>Campaign</th><th>Platform</th><th>Posts</th><th>Reach</th><th>Engagement</th><th>Clicks</th><th>Status</th><th>Actions</th></tr></thead><tbody>{performance.map((row) => <tr key={row.campaign_id}><td>{row.campaign_name}</td><td>{row.platform}</td><td>{row.posts}</td><td>{formatMetric(row.reach)}</td><td>{formatMetric(row.engagement)}</td><td>{formatMetric(row.clicks)}</td><td><StatusBadge value={row.status} /></td><td><div className="report-row-actions"><button onClick={() => navigate(`/campaigns/${row.campaign_id}`)}>View</button><button disabled={exporting === row.campaign_id} onClick={() => exportCampaignReport(row.campaign_id, row.campaign_name)}>{exporting === row.campaign_id ? "Exporting..." : "Export"}</button></div></td></tr>)}</tbody></table></div>{!performance.length && <EmptyState title="No matching campaigns" description="Adjust the report filters to see results." />}</section>}

    {activeReport === "engagement" && <section className="report-content"><header><div><p className="eyebrow">ENGAGEMENT REPORT</p><h2>Interactions by type</h2></div></header><div className="report-metric-grid">{[["Likes", overview?.likes], ["Comments", overview?.comments], ["Shares", overview?.shares], ["Clicks", overview?.clicks], ["Views", overview?.views]].map(([label, value]) => <article key={label}><span>{label}</span><strong>{formatMetric(value)}</strong></article>)}</div><p className="reports-note">Likes and comments use current Instagram post insights. Other interaction metrics are shown only when supported and returned by the connected platform.</p></section>}

    {activeReport === "audience" && <section className="report-content"><header><div><p className="eyebrow">AUDIENCE REPORT</p><h2>Follower movement</h2></div></header><div className="report-metric-grid">{[["Current followers", audience?.current_followers], ["New followers", audience?.new_followers], ["Lost followers", audience?.lost_followers], ["Net growth", audience?.net_growth], ["Growth rate", audience?.growth_percentage == null ? null : `${audience.growth_percentage}%`]].map(([label, value]) => <article key={label}><span>{label}</span><strong>{value == null ? "Not available" : typeof value === "number" ? value.toLocaleString() : value}</strong></article>)}</div><p className="reports-note">{audience?.message || "Follower history is not available yet."}</p>{audience?.last_synced_at && <p className="reports-note">Last follower snapshot: {new Date(audience.last_synced_at).toLocaleDateString()}</p>}</section>}

    {activeReport === "roi" && <section className="report-content"><header><div><p className="eyebrow">ROI REPORT</p><h2>Costs and returns</h2></div></header><div className="reports-table-wrap"><table><thead><tr><th>Campaign</th><th>Campaign cost</th><th>Revenue</th><th>Profit</th><th>ROI</th></tr></thead><tbody>{(roi?.campaigns || []).map((row) => <tr key={row.campaign_id}><td>{row.campaign_name}</td><td>{row.campaign_cost == null ? "Not tracked" : Number(row.campaign_cost).toLocaleString()}</td><td>{row.revenue == null ? "Not tracked" : Number(row.revenue).toLocaleString()}</td><td>{row.profit == null ? "Not tracked" : Number(row.profit).toLocaleString()}</td><td>{row.roi == null ? "Not tracked" : `${row.roi}%`}</td></tr>)}</tbody></table></div><p className="reports-note">{roi?.message || "Revenue tracking is not available yet, so ROI cannot be calculated."}</p></section>}
  </div>;
}

export default Reports;