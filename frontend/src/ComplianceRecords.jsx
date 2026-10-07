import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems as menuItems } from "./roleMenuItems";
import { api, apiErrorMessage } from "./api";
import { useNotificationRefresh } from "./NotificationBell";
import SelectMenu from "./SelectMenu";

const STATUS_LABELS = { compliant: "Compliant", "non-compliant": "Non-compliant", pending: "Pending" };
const statusClass = (s) => ({ compliant: "green", "non-compliant": "red", pending: "yellow" }[s] || "gray");
const emptyFilters = { status: "", location_id: "", date_from: "", date_to: "" };
const emptyStats = { compliant: 0, nonCompliant: 0, pending: 0, total: 0, totalViolations: 0, complianceRate: null };

const localToday = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};

const formatDay = (value) => {
  if (!value) return "Unknown";
  const [year, month, day] = String(value).slice(0, 10).split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
};

const queryParams = (filters) => Object.fromEntries(Object.entries(filters).filter(([, value]) => value !== ""));

export default function ComplianceRecords() {
  const navigate = useNavigate();
  const [records, setRecords] = useState([]);
  const [locations, setLocations] = useState([]);
  const [stats, setStats] = useState(emptyStats);
  const [filters, setFilters] = useState(emptyFilters);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [generateDate, setGenerateDate] = useState(localToday());
  const [busy, setBusy] = useState("");
  const [review, setReview] = useState(null);

  const fetchData = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const params = queryParams(filters);
      const [recordsRes, statsRes] = await Promise.all([
        api.get("/officer/compliance-records", { params }),
        api.get("/officer/compliance-stats", { params }),
      ]);
      setRecords(recordsRes.data || []);
      setStats({ ...emptyStats, ...(statsRes.data || {}) });
      setError("");
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to load compliance records.", navigate));
    } finally {
      setLoading(false);
    }
  }, [filters, navigate]);

  useEffect(() => {
    if (!sessionStorage.getItem("token")) {
      navigate("/login", { replace: true });
      return;
    }
    fetchData();
  }, [fetchData, navigate]);

  useEffect(() => {
    api.get("/officer/locations").then((response) => setLocations(response.data || [])).catch(() => {});
  }, []);

  // New incidents and task updates change today's record.
  useNotificationRefresh(["incident", "task_update"], () => fetchData(true));

  const generate = async () => {
    setBusy("generate");
    setError("");
    setSuccess("");
    try {
      const response = await api.post("/officer/compliance-records/generate", { date: generateDate || null });
      setSuccess(response.data.detail);
      await fetchData(true);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not generate compliance records.", navigate));
    } finally {
      setBusy("");
    }
  };

  const exportCsv = async () => {
    setBusy("export");
    setError("");
    try {
      const response = await api.get("/officer/compliance-records/export", { params: queryParams(filters), responseType: "blob" });
      const disposition = response.headers?.["content-disposition"] || "";
      const filename = disposition.match(/filename="([^"]+)"/)?.[1] || `visionguard-compliance-${localToday()}.csv`;
      const url = window.URL.createObjectURL(new Blob([response.data], { type: "text/csv" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setSuccess(`Exported ${records.length} record(s) to ${filename}.`);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not export the CSV file.", navigate));
    } finally {
      setBusy("");
    }
  };

  const openReview = (record) => {
    setReview({ record, status: record.status_source === "officer" ? record.status : "auto", notes: record.notes || "", error: "" });
  };

  const saveReview = async (event) => {
    event.preventDefault();
    setBusy("review");
    try {
      await api.patch(`/officer/compliance-records/${review.record.id}`, { status: review.status, notes: review.notes });
      setReview(null);
      setSuccess(`Review saved for ${review.record.location} (${formatDay(review.record.record_date || review.record.date)}).`);
      await fetchData(true);
    } catch (requestError) {
      setReview((current) => ({ ...current, error: apiErrorMessage(requestError, "Could not save the review.", navigate) }));
    } finally {
      setBusy("");
    }
  };

  const rate = stats.complianceRate;
  const statCards = [
    { label: "Compliance Rate", value: rate === null || rate === undefined ? "—" : `${rate}%`, icon: "chart", tone: "blue" },
    { label: "Compliant", value: stats.compliant, icon: "check", tone: "green" },
    { label: "Pending", value: stats.pending, icon: "clock", tone: "amber" },
    { label: "Non-Compliant", value: stats.nonCompliant, icon: "x", tone: "red" },
  ];
  const total = Math.max(stats.total || 0, 1);
  const compliantPct = ((stats.compliant || 0) / total) * 100;
  const pendingPct = ((stats.pending || 0) / total) * 100;
  const nonCompliantPct = ((stats.nonCompliant || 0) / total) * 100;
  const filtered = Object.values(filters).some(Boolean);

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Compliance Records</div>
            <div className="dashboard-subtitle">One record per location per day, built from that day's incidents and corrective actions.</div>
          </div>
          <div className="topbar-actions">
            <button type="button" className="btn btn-primary btn-sm" onClick={exportCsv} disabled={busy === "export" || loading}>
              <Icon name="clipboard" size={16} /> {busy === "export" ? "Exporting..." : "Export CSV"}
            </button>
          </div>
        </div>

        <div className="stats-grid">
          {statCards.map((c, i) => (
            <div key={c.label} className="stat-item" style={{ animationDelay: `${i * 0.08}s` }}>
              <div className="stat-item-header">
                <div className={`stat-icon tone-${c.tone}`}><Icon name={c.icon} /></div>
                <span className="stat-label">{c.label}</span>
              </div>
              <div className={`stat-value tone-${c.tone}`}>{loading ? "…" : (c.value ?? 0)}</div>
            </div>
          ))}
        </div>

        <div className="content-section analytics-panel compliance-overview">
          <div className="panel-heading">
            <div>
              <h2 className="section-title">Compliance Mix</h2>
              <p>{stats.total || 0} record(s) · {stats.totalViolations || 0} violation(s){filtered ? " · filtered" : ""}</p>
            </div>
            <span className="live-chip">Updates automatically</span>
          </div>
          <div className="bar-track compliance-stack">
            <span className="bar-fill green" style={{ width: `${compliantPct}%` }} />
            <span className="bar-fill amber" style={{ width: `${pendingPct}%` }} />
            <span className="bar-fill red" style={{ width: `${nonCompliantPct}%` }} />
          </div>
          <div className="compliance-legend">
            <div><span className="legend-dot green" /><strong>Compliant</strong><span>No violations detected that day.</span></div>
            <div><span className="legend-dot amber" /><strong>Pending</strong><span>Violations happened and are still being handled.</span></div>
            <div><span className="legend-dot red" /><strong>Non-compliant</strong><span>Violations happened; all of them have been handled.</span></div>
          </div>
        </div>

        <div className="content-section filter-section">
          <div className="section-heading">
            <div>
              <h2 className="section-title">Generate Records</h2>
              <p>Records refresh by themselves every few minutes. Use this to build a past day or refresh now.</p>
            </div>
          </div>
          <div className="compliance-generate">
            <div className="form-group">
              <label className="form-label" htmlFor="generate-date">Day</label>
              <input id="generate-date" type="date" className="form-input" max={localToday()} value={generateDate} onChange={(e) => setGenerateDate(e.target.value)} />
            </div>
            <button type="button" className="btn btn-ghost" onClick={generate} disabled={busy === "generate" || !generateDate}>
              <Icon name="activity" size={16} /> {busy === "generate" ? "Generating..." : "Generate Records"}
            </button>
          </div>
        </div>

        <div className="content-section filter-section">
          <div className="section-heading">
            <div>
              <h2 className="section-title">Filters</h2>
              <p>Filters also apply to the CSV export.</p>
            </div>
          </div>
          <div className="compliance-filter-grid">
            <div className="form-group">
              <label className="form-label" htmlFor="filter-status">Status</label>
              <SelectMenu
                id="filter-status"
                value={filters.status}
                options={[
                  { value: "", label: "All" },
                  { value: "compliant", label: "Compliant" },
                  { value: "pending", label: "Pending" },
                  { value: "non-compliant", label: "Non-compliant" },
                ]}
                onChange={(status) => setFilters({ ...filters, status })}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="filter-location">Location</label>
              <SelectMenu
                id="filter-location"
                value={filters.location_id}
                options={[{ value: "", label: "All locations" }, ...locations.map((location) => ({ value: String(location.id), label: location.name }))]}
                onChange={(locationId) => setFilters({ ...filters, location_id: locationId })}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="filter-from">From</label>
              <input id="filter-from" type="date" className="form-input" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="filter-to">To</label>
              <input id="filter-to" type="date" className="form-input" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} />
            </div>
            <button type="button" className="btn btn-ghost btn-sm filter-clear" onClick={() => setFilters(emptyFilters)} disabled={!filtered}>Clear</button>
          </div>
        </div>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {success && <div className="alert alert-success" role="status">{success}</div>}

        <div className="content-section">
          <h2 className="section-title">Records</h2>
          {loading ? <p className="loading-text">Loading records...</p> :
           records.length === 0 ? (
             <p className="loading-text">{filtered ? "No records match these filters." : "No compliance records yet. Click Generate Records to build today's records."}</p>
           ) : (
            <div className="table-scroll">
              <table className="compliance-table">
                <thead><tr><th>Date</th><th>Location</th><th>Status</th><th>Violations</th><th>Actions</th><th>Summary &amp; remarks</th><th /></tr></thead>
                <tbody>
                  {records.map((record) => (
                    <tr key={record.id}>
                      <td style={{ whiteSpace: "nowrap", color: "var(--text2)" }}>{formatDay(record.record_date || record.date)}</td>
                      <td style={{ fontWeight: 600 }}><span className="table-icon"><Icon name="location" size={16} /></span>{record.location}</td>
                      <td>
                        <span className={`badge badge-${statusClass(record.status)}`}>{STATUS_LABELS[record.status] || record.status}</span>
                        <div className="compliance-meta">{record.status_source === "officer" ? `Set by ${record.officer || "officer"}` : "Automatic"}</div>
                      </td>
                      <td>
                        <strong>{record.violations}</strong>
                        {record.violations > 0 && (
                          <div className="compliance-meta">{record.ppe_violations} PPE · {record.restricted_violations} restricted</div>
                        )}
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {record.actions_total ? `${record.actions_resolved}/${record.actions_total} resolved` : <span style={{ color: "var(--text3)" }}>None</span>}
                      </td>
                      <td className="compliance-summary">
                        <div>{record.summary || "—"}</div>
                        {record.notes && <div className="compliance-remarks"><strong>Officer:</strong> {record.notes}</div>}
                      </td>
                      <td><button type="button" className="btn btn-ghost btn-sm" onClick={() => openReview(record)}>Review</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {review && (
          <div className="modal-backdrop" onMouseDown={() => setReview(null)}>
            <section className="modal-card" role="dialog" aria-modal="true" aria-labelledby="review-title" onMouseDown={(event) => event.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <span className="modal-eyebrow">{formatDay(review.record.record_date || review.record.date)}</span>
                  <h2 id="review-title">Review: {review.record.location}</h2>
                </div>
                <button type="button" className="modal-close" onClick={() => setReview(null)} aria-label="Close review"><Icon name="x" size={18} /></button>
              </div>
              <form onSubmit={saveReview}>
                <div className="incident-detail-grid">
                  <div><span>Violations</span><strong>{review.record.violations} ({review.record.ppe_violations} PPE, {review.record.restricted_violations} restricted)</strong></div>
                  <div><span>Corrective actions</span><strong>{review.record.actions_resolved}/{review.record.actions_total} resolved</strong></div>
                  <div className="detail-span"><span>Summary</span><strong>{review.record.summary}</strong></div>
                </div>
                <div className="form-group" style={{ marginTop: 18 }}>
                  <label className="form-label" htmlFor="review-status">Status</label>
                  <SelectMenu
                    id="review-status"
                    value={review.status}
                    options={[
                      { value: "auto", label: `Automatic (${STATUS_LABELS[review.record.auto_status] || "from incidents"})`, description: "Follows the day's incidents and actions" },
                      { value: "compliant", label: "Compliant" },
                      { value: "pending", label: "Pending" },
                      { value: "non-compliant", label: "Non-compliant" },
                    ]}
                    onChange={(status) => setReview({ ...review, status })}
                  />
                </div>
                <div className="form-group" style={{ marginTop: 14 }}>
                  <label className="form-label" htmlFor="review-notes">Officer remarks</label>
                  <textarea id="review-notes" className="form-input notes-input" rows={4} value={review.notes} onChange={(e) => setReview({ ...review, notes: e.target.value })} placeholder="e.g. Site inspected, team briefed on helmet use." />
                </div>
                {review.error && <div className="alert alert-error" role="alert">{review.error}</div>}
                <div className="modal-actions">
                  <button type="button" className="btn btn-ghost" onClick={() => setReview(null)}>Cancel</button>
                  <button type="submit" className="btn btn-primary" disabled={busy === "review"}>{busy === "review" ? "Saving..." : "Save Review"}</button>
                </div>
              </form>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
