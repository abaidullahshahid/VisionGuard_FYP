import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems as menuItems } from "./roleMenuItems";
import { api, apiErrorMessage } from "./api";
import {
  formatDateTime,
  incidentTypeLabel,
  severityBadge,
  severityLabel,
  severityValue,
  statusBadge,
  statusLabel,
} from "./incidentUtils";

const emptySummary = {
  total: 0,
  open: 0,
  inProgress: 0,
  resolved: 0,
  high: 0,
  ppe: 0,
  zones: 0,
  pendingActions: 0,
};

export default function OfficerDashboard() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState(emptySummary);
  const [recentIncidents, setRecentIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!sessionStorage.getItem("token")) {
      navigate("/login", { replace: true });
      return;
    }
    const fetchData = async () => {
      setLoading(true);
      setError("");
      try {
        const [statsResponse, incidentsResponse] = await Promise.all([
          api.get("/officer/stats"),
          api.get("/officer/incidents"),
        ]);
        const incidents = incidentsResponse.data || [];
        setSummary({
          total: incidents.length,
          open: incidents.filter((incident) => incident.status === "open").length,
          inProgress: incidents.filter((incident) => incident.status === "in_progress").length,
          resolved: incidents.filter((incident) => incident.status === "resolved").length,
          high: incidents.filter((incident) => severityValue(incident) === "HIGH").length,
          ppe: incidents.filter((incident) => (incident.incident_type || incident.violation_type) === "PPE_VIOLATION").length,
          zones: incidents.filter((incident) => (incident.incident_type || incident.violation_type) === "RESTRICTED_ZONE_VIOLATION").length,
          pendingActions: statsResponse.data?.pendingActions || 0,
        });
        setRecentIncidents(incidents.slice(0, 5));
      } catch (requestError) {
        setError(apiErrorMessage(requestError, "Failed to load the Officer dashboard.", navigate));
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [navigate]);

  const cards = [
    { label: "Total Incidents", value: summary.total, icon: "alert", tone: "blue" },
    { label: "Open Incidents", value: summary.open, icon: "bell", tone: "red" },
    { label: "In Progress", value: summary.inProgress, icon: "clock", tone: "amber" },
    { label: "Resolved", value: summary.resolved, icon: "check", tone: "green" },
    { label: "High Severity", value: summary.high, icon: "rules", tone: "red" },
  ];
  const workload = [
    { label: "PPE violations", value: summary.ppe, tone: "blue" },
    { label: "Restricted-zone violations", value: summary.zones, tone: "red" },
    { label: "Pending corrective actions", value: summary.pendingActions, tone: "amber" },
    { label: "Resolved incidents", value: summary.resolved, tone: "green" },
  ];
  const maxMetric = Math.max(...workload.map((item) => item.value), 1);

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">
        <div className="topbar">
          <div>
            <div className="topbar-title">Safety Officer Dashboard</div>
            <div className="dashboard-subtitle">Live incident response metrics from PostgreSQL</div>
          </div>
          <span className="topbar-badge"><Icon name="rules" size={16} /> Safety Officer</span>
        </div>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {loading ? <p className="loading-text">Loading dashboard...</p> : (
          <>
            <div className="stats-grid officer-stats-grid">
              {cards.map((card, index) => (
                <div key={card.label} className="stat-item" style={{ animationDelay: `${index * 0.06}s` }}>
                  <div className="stat-item-header">
                    <div className={`stat-icon tone-${card.tone}`}><Icon name={card.icon} /></div>
                    <span className="stat-label">{card.label}</span>
                  </div>
                  <div className={`stat-value tone-${card.tone}`}>{card.value}</div>
                </div>
              ))}
            </div>

            <div className="content-section analytics-panel" style={{ marginBottom: 28 }}>
              <div className="panel-heading">
                <div>
                  <h2 className="section-title">Incident Workload</h2>
                  <p>Counts are derived from the current incident and corrective-action APIs.</p>
                </div>
                <span className="live-chip">Database backed</span>
              </div>
              <div className="bar-stack">
                {workload.map((item) => (
                  <div key={item.label} className="bar-row">
                    <div className="bar-row-label"><span>{item.label}</span><strong>{item.value}</strong></div>
                    <div className="bar-track"><span className={`bar-fill ${item.tone}`} style={{ width: `${Math.max(6, (item.value / maxMetric) * 100)}%` }} /></div>
                  </div>
                ))}
              </div>
            </div>

            <div className="content-section" style={{ marginBottom: 28 }}>
              <h2 className="section-title">Quick Actions</h2>
              <div className="quick-actions-grid">
                {menuItems.slice(1).map((item) => (
                  <button key={item.label} className="btn btn-ghost quick-action-btn" onClick={() => navigate(item.path)}>
                    <span className="quick-action-icon">{item.icon}</span>
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="content-section">
              <div className="section-heading">
                <div>
                  <h2 className="section-title">Recent Incidents</h2>
                  <p>The five most recently detected safety events.</p>
                </div>
                <button className="btn btn-ghost btn-sm" onClick={() => navigate("/officer/incidents")}>View All <Icon name="chevronRight" size={14} /></button>
              </div>
              {recentIncidents.length === 0 ? (
                <div className="empty-state"><span className="empty-state-icon"><Icon name="check" size={24} /></span><strong>No incidents found</strong><span>New confirmed AI incidents will appear here.</span></div>
              ) : (
                <table>
                  <thead><tr><th>Type</th><th>Location</th><th>Severity</th><th>Status</th><th>Detected</th></tr></thead>
                  <tbody>
                    {recentIncidents.map((incident) => (
                      <tr key={incident.id}>
                        <td><span className="table-primary"><span className="table-icon"><Icon name="alert" size={16} /></span>{incidentTypeLabel(incident.incident_type || incident.violation_type)}</span></td>
                        <td>{incident.location || "Unknown"}</td>
                        <td><span className={`badge badge-${severityBadge(incident)}`}>{severityLabel(incident)}</span></td>
                        <td><span className={`badge badge-${statusBadge(incident.status)}`}>{statusLabel(incident.status)}</span></td>
                        <td className="table-secondary">{formatDateTime(incident.timestamp || incident.detected_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
