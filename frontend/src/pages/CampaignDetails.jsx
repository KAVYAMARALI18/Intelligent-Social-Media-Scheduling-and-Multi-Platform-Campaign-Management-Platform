import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import "./CampaignDetails.css";
import "./CampaignWorkspace.css";

const API_URL = "http://127.0.0.1:8000";
const formatMetric = (value) => value == null ? "Not available" : Number(value).toLocaleString("en-US");
const formatPercentage = (value) => value == null ? "Not available" : `${Number(value).toFixed(2)}%`;

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function CampaignDetails() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [campaign, setCampaign] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [accounts, setAccounts] = useState([]);
  const [posts, setPosts] = useState([]);
  const [report, setReport] = useState(null);
  const [postForm, setPostForm] = useState({ content: "", social_account_id: "", scheduled_date: "", scheduled_time: "", status: "draft", media_url: "", media_type: null, media_filename: "" });
  const [postSaving, setPostSaving] = useState(false);

  useEffect(() => {
    const loadCampaign = async () => {
      const token = localStorage.getItem("access_token");
      if (!token) {
        navigate("/login", { replace: true });
        return;
      }

      try {
        const response = await fetch(`${API_URL}/campaigns/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (response.status === 401) {
          localStorage.removeItem("access_token");
          navigate("/login", { replace: true });
          return;
        }
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Unable to load campaign.");
        setCampaign(data);
        const [accountsResponse, postsResponse] = await Promise.all([
          fetch(`${API_URL}/campaigns/${id}/accounts`, { headers: { Authorization: `Bearer ${token}` } }),
          fetch(`${API_URL}/campaigns/${id}/posts`, { headers: { Authorization: `Bearer ${token}` } }),
        ]);
        if (accountsResponse.ok) setAccounts(await accountsResponse.json());
        if (postsResponse.ok) setPosts(await postsResponse.json());
      } catch (requestError) {
        setError(requestError.message || "Unable to load campaign.");
      } finally {
        setLoading(false);
      }
    };

    loadCampaign();
  }, [id, navigate]);

  if (loading) return <main className="campaign-details-page"><div className="campaign-details-state">Loading campaign...</div></main>;
  if (error) return <main className="campaign-details-page"><div className="campaign-details-state"><strong>{error}</strong><button className="campaigns-back-button" type="button" onClick={() => navigate("/campaigns")}>Back to campaigns</button></div></main>;

  const connectedAccounts = accounts;

  const submitPost = async (event) => {
    event.preventDefault();
    const token = localStorage.getItem("access_token");
    try {
      setPostSaving(true);
      const scheduledAt = postForm.scheduled_date && postForm.scheduled_time
        ? `${postForm.scheduled_date}T${postForm.scheduled_time}:00`
        : null;
      const response = await fetch(`${API_URL}/campaigns/${id}/posts`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ content: postForm.content, social_account_id: Number(postForm.social_account_id), scheduled_at: scheduledAt, status: postForm.status, media_url: postForm.media_url || null, media_type: postForm.media_type, media_filename: postForm.media_filename || null }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to create post.");
      setPosts((current) => [...current, data]);
      setPostForm({ content: "", social_account_id: "", scheduled_date: "", scheduled_time: "", status: "draft", media_url: "", media_type: null, media_filename: "" });
    } catch (requestError) {
      setError(requestError.message || "Unable to create post.");
    } finally {
      setPostSaving(false);
    }
  };

  const updatePostField = (event) => setPostForm((current) => ({ ...current, [event.target.name]: event.target.value }));
  const uploadMedia = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(`${API_URL}/posts/upload-media`, { method: "POST", headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` }, body: formData });
    const data = await response.json();
    if (!response.ok) { setError(data.detail || "Unable to upload media."); return; }
    setPostForm((current) => ({ ...current, media_url: data.media_url, media_type: data.media_type, media_filename: data.media_filename }));
  };
  const publishPost = async (postId) => {
    const response = await fetch(`${API_URL}/posts/${postId}/publish`, { method: "POST", headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` } });
    const data = await response.json();
    if (!response.ok || data.success === false) { setError(data.message || data.detail || "Unable to publish post."); return; }
    setPosts((current) => current.map((post) => post.id === postId ? { ...post, status: "published", scheduled_at: null } : post));
  };
  const generateReport = async () => {
    const token = localStorage.getItem("access_token");
    const response = await fetch(`${API_URL}/campaigns/${id}/report`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await response.json();
    if (!response.ok) {
      setError(data.detail || "Unable to generate campaign report.");
      return;
    }
    setReport(data);
  };
  const scheduledPosts = posts.filter((post) => post.scheduled_at);
  const tracking = campaign?.tracking || {
    total_posts: posts.length,
    scheduled_posts: posts.filter((post) => post.status === "scheduled").length,
    published_posts: posts.filter((post) => post.status === "published").length,
    failed_posts: posts.filter((post) => post.status === "failed").length,
    workflow: ["Draft", "Scheduled", "Active", "Completed"],
  };
  const workflowStages = tracking.workflow || ["Draft", "Scheduled", "Active", "Completed"];
  const currentStatusIndex = workflowStages.indexOf(campaign?.status || "Draft");

  return (
    <main className="campaign-details-page">
      <div className="campaign-details-shell">
        <header className="campaign-details-header">
          <div>
            <p className="campaigns-eyebrow">Campaign details</p>
            <h1>{campaign.name}</h1>
            <p>{campaign.objective || "No objective provided"}</p>
          </div>
          <div className="campaign-details-actions">
            <button className="campaigns-back-button" type="button" onClick={() => navigate("/campaigns")}>Back to campaigns</button>
            <button className="campaign-save-button" type="button" onClick={generateReport}>Generate report</button>
          </div>
        </header>

        {report && (
          <section className="campaign-report-panel">
            <div className="campaign-related-heading">
              <h2>Audience growth & performance report</h2>
              <span>{formatMetric(report.total_followers)}</span>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "12px", marginTop: "18px" }}>
              <div style={{ padding: "14px", background: "rgba(13, 30, 27, 0.7)", border: "1px solid #23443e", borderRadius: "8px" }}>
                <div style={{ color: "#6f9289", fontSize: "10px", letterSpacing: "1px", textTransform: "uppercase" }}>New followers</div>
                <strong style={{ display: "block", marginTop: "8px", color: "#ebfff7", fontSize: "22px" }}>{formatMetric(report.new_followers)}</strong>
              </div>
              <div style={{ padding: "14px", background: "rgba(13, 30, 27, 0.7)", border: "1px solid #23443e", borderRadius: "8px" }}>
                <div style={{ color: "#6f9289", fontSize: "10px", letterSpacing: "1px", textTransform: "uppercase" }}>Lost followers</div>
                <strong style={{ display: "block", marginTop: "8px", color: "#ebfff7", fontSize: "22px" }}>{formatMetric(report.lost_followers)}</strong>
              </div>
              <div style={{ padding: "14px", background: "rgba(13, 30, 27, 0.7)", border: "1px solid #23443e", borderRadius: "8px" }}>
                <div style={{ color: "#6f9289", fontSize: "10px", letterSpacing: "1px", textTransform: "uppercase" }}>Total followers</div>
                <strong style={{ display: "block", marginTop: "8px", color: "#ebfff7", fontSize: "22px" }}>{formatMetric(report.total_followers)}</strong>
              </div>
              <div style={{ padding: "14px", background: "rgba(13, 30, 27, 0.7)", border: "1px solid #23443e", borderRadius: "8px" }}>
                <div style={{ color: "#6f9289", fontSize: "10px", letterSpacing: "1px", textTransform: "uppercase" }}>Growth</div>
                <strong style={{ display: "block", marginTop: "8px", color: "#ebfff7", fontSize: "22px" }}>{formatMetric(report.follower_growth)}</strong>
              </div>
              <div style={{ padding: "14px", background: "rgba(13, 30, 27, 0.7)", border: "1px solid #23443e", borderRadius: "8px" }}>
                <div style={{ color: "#6f9289", fontSize: "10px", letterSpacing: "1px", textTransform: "uppercase" }}>Growth %</div>
                <strong style={{ display: "block", marginTop: "8px", color: "#ebfff7", fontSize: "22px" }}>{formatPercentage(report.growth_percentage)}</strong>
              </div>
              <div style={{ padding: "14px", background: "rgba(13, 30, 27, 0.7)", border: "1px solid #23443e", borderRadius: "8px" }}>
                <div style={{ color: "#6f9289", fontSize: "10px", letterSpacing: "1px", textTransform: "uppercase" }}>Reach</div>
                <strong style={{ display: "block", marginTop: "8px", color: "#ebfff7", fontSize: "22px" }}>{formatMetric(report.reach)}</strong>
              </div>
              <div style={{ padding: "14px", background: "rgba(13, 30, 27, 0.7)", border: "1px solid #23443e", borderRadius: "8px" }}>
                <div style={{ color: "#6f9289", fontSize: "10px", letterSpacing: "1px", textTransform: "uppercase" }}>Impressions</div>
                <strong style={{ display: "block", marginTop: "8px", color: "#ebfff7", fontSize: "22px" }}>{formatMetric(report.impressions)}</strong>
              </div>
            </div>

            {!report.audience_timeline?.length && <p className="reports-note">{report.audience_message || "Historical follower data is not available yet."}</p>}

            {report.audience_timeline?.length > 0 && (
              <div style={{ marginTop: "24px" }}>
                <h3 style={{ margin: "0 0 12px", color: "#effcf7", fontSize: "16px" }}>Follower timeline</h3>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", color: "#dfeae6", fontSize: "13px" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid #20433e" }}>
                        <th style={{ textAlign: "left", padding: "10px 8px", color: "#6f9289" }}>Date</th>
                        <th style={{ textAlign: "right", padding: "10px 8px", color: "#6f9289" }}>Followers</th>
                        <th style={{ textAlign: "right", padding: "10px 8px", color: "#6f9289" }}>New</th>
                        <th style={{ textAlign: "right", padding: "10px 8px", color: "#6f9289" }}>Growth</th>
                        <th style={{ textAlign: "right", padding: "10px 8px", color: "#6f9289" }}>Reach</th>
                        <th style={{ textAlign: "right", padding: "10px 8px", color: "#6f9289" }}>Impressions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.audience_timeline.map((point) => (
                        <tr key={point.date} style={{ borderBottom: "1px solid rgba(32, 67, 62, 0.6)" }}>
                          <td style={{ padding: "10px 8px" }}>{point.date}</td>
                          <td style={{ textAlign: "right", padding: "10px 8px" }}>{formatMetric(point.followers)}</td>
                          <td style={{ textAlign: "right", padding: "10px 8px" }}>{formatMetric(point.new_followers)}</td>
                          <td style={{ textAlign: "right", padding: "10px 8px" }}>{formatPercentage(point.growth_percentage)}</td>
                          <td style={{ textAlign: "right", padding: "10px 8px" }}>{formatMetric(point.reach)}</td>
                          <td style={{ textAlign: "right", padding: "10px 8px" }}>{formatMetric(point.impressions)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {report.top_performing_content?.length > 0 && (
              <div style={{ marginTop: "24px" }}>
                <h3 style={{ margin: "0 0 12px", color: "#effcf7", fontSize: "16px" }}>Top-performing content</h3>
                <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: "10px" }}>
                  {report.top_performing_content.map((item, index) => (
                    <li key={`${item.content}-${index}`} style={{ padding: "12px 14px", border: "1px solid #23443e", borderRadius: "8px", background: "rgba(13, 30, 27, 0.7)" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "10px", marginBottom: "6px", color: "#dfeae6" }}>
                        <strong>{item.platform || "Social"}</strong>
                        <span style={{ color: "#83dec4", fontWeight: 700 }}>{formatMetric(item.engagement_score)}</span>
                      </div>
                      <div style={{ color: "#b6d1c8", lineHeight: 1.5 }}>{item.content}</div>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {!report.top_performing_content?.length && <p className="reports-note">Top-performing posts will appear after actual post metrics have been synchronized.</p>}

            <pre style={{ marginTop: "22px" }}>{report.report_text}</pre>
          </section>
        )}

        <section className="campaign-information-grid">
          <article className="campaign-information-card campaign-information-wide">
            <p className="campaign-card-label">Campaign information</p>
            <h2>{campaign.name}</h2>
            <p>{campaign.description || "No description provided."}</p>
          </article>
          <article className="campaign-information-card">
            <p className="campaign-card-label">Status</p>
            <span className={`campaign-status ${campaign.status?.toLowerCase()}`}>{campaign.status}</span>
          </article>
          <article className="campaign-information-card">
            <p className="campaign-card-label">Dates</p>
            <strong>{formatDate(campaign.start_date)} <span>to</span> {formatDate(campaign.end_date)}</strong>
          </article>
          <article className="campaign-information-card">
            <p className="campaign-card-label">Target audience</p>
            <p>{campaign.target_audience || "No target audience provided."}</p>
          </article>
          <article className="campaign-information-card">
            <p className="campaign-card-label">Budget</p>
            <strong>{campaign.budget == null ? "No budget set" : `₹${Number(campaign.budget).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}</strong>
          </article>
        </section>

        <section className="campaign-tracker-panel">
          <div className="campaign-related-heading"><h2>Campaign tracking workflow</h2><span>{campaign.status}</span></div>
          <div className="campaign-tracker-flow" aria-label="Campaign workflow tracking">
            {workflowStages.map((stage, index) => (
              <div key={stage} className={`campaign-tracker-step ${index <= currentStatusIndex ? "active" : ""} ${campaign.status === stage ? "current" : ""}`}>
                <span className="campaign-tracker-bullet">{index + 1}</span>
                <span>{stage}</span>
                {index < workflowStages.length - 1 && <i className="campaign-tracker-arrow" aria-hidden="true">→</i>}
              </div>
            ))}
          </div>
          <div className="campaign-tracker-metrics">
            <article><span>Total posts</span><strong>{tracking.total_posts ?? 0}</strong></article>
            <article><span>Scheduled posts</span><strong>{tracking.scheduled_posts ?? 0}</strong></article>
            <article><span>Published posts</span><strong>{tracking.published_posts ?? 0}</strong></article>
            <article><span>Failed posts</span><strong>{tracking.failed_posts ?? 0}</strong></article>
            <article><span>Start</span><strong>{formatDate(campaign.start_date)}</strong></article>
            <article><span>End</span><strong>{formatDate(campaign.end_date)}</strong></article>
            <article><span>Status</span><strong>{campaign.status}</strong></article>
          </div>
        </section>

        <section className="campaign-related-grid">
          <article className="campaign-related-panel">
            <div className="campaign-related-heading"><h2>Connected social accounts</h2><span>{connectedAccounts.length}</span></div>
            {connectedAccounts.length ? <ul>{connectedAccounts.map((account) => <li key={account.id || account.platform}>{account.name || account.platform || "Connected account"}</li>)}</ul> : <p className="campaign-related-empty">No social accounts connected to this campaign yet.</p>}
          </article>
          <article className="campaign-related-panel">
            <div className="campaign-related-heading"><h2>Campaign posts</h2><span>{posts.length}</span></div>
            {posts.length ? <ul>{posts.map((post) => <li key={post.id}><span>{post.content || post.title || "Campaign post"} · {post.status}</span>{post.status !== "published" && <button type="button" className="post-publish-button" onClick={() => publishPost(post.id)}>Publish</button>}</li>)}</ul> : <p className="campaign-related-empty">No posts have been added to this campaign yet.</p>}
          </article>
          <article className="campaign-related-panel campaign-post-composer">
            <div className="campaign-related-heading"><h2>Add campaign post</h2><span>+</span></div>
            <form onSubmit={submitPost}>
              <textarea name="content" value={postForm.content} onChange={updatePostField} required placeholder="Write your post content" rows="3" />
              <select name="social_account_id" value={postForm.social_account_id} onChange={updatePostField} required>
                <option value="">Select social account</option>
                {connectedAccounts.map((account) => <option key={account.id} value={account.id}>{account.platform} · {account.username}</option>)}
              </select>
              <input type="file" accept="image/*,video/*" onChange={uploadMedia} />
              <div className="post-schedule-fields"><input name="scheduled_date" type="date" value={postForm.scheduled_date} onChange={updatePostField} /><input name="scheduled_time" type="time" value={postForm.scheduled_time} onChange={updatePostField} /></div>
              <select name="status" value={postForm.status} onChange={updatePostField}><option value="draft">Draft</option><option value="scheduled">Scheduled</option></select>
              <button className="campaign-save-button" type="submit" disabled={postSaving}>{postSaving ? "Adding..." : "Add Post"}</button>
            </form>
          </article>
        </section>

        <section className="campaign-calendar-panel">
          <div className="campaign-related-heading"><h2>Campaign scheduling</h2><span>{scheduledPosts.length}</span></div>
          <div className="campaign-calendar-list">
            {scheduledPosts.length ? scheduledPosts.map((post) => <div className="campaign-calendar-item" key={post.id}><strong>{new Date(post.scheduled_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</strong><span>{post.platform || "Social"} post · {post.content}</span></div>) : <p className="campaign-related-empty">Scheduled posts will appear here.</p>}
          </div>
        </section>
      </div>
    </main>
  );
}

export default CampaignDetails;