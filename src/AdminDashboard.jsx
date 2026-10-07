import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API_BASE } from "./api";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import menuItems from "./adminMenuItems";

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState({ totalUsers:0, totalCameras:0, totalIncidents:0, totalLocations:0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = sessionStorage.getItem("token");
    if (!token) { navigate("/login"); return; }
    axios.get(`${API_BASE}/admin/stats`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => setStats(r.data))
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, [navigate]);

  const cards = [
    { label:"Total Users",     value:stats.totalUsers,     icon:"users",    tone:"blue"  },
    { label:"Active Cameras",  value:stats.totalCameras,   icon:"camera",   tone:"green" },
    { label:"Total Incidents", value:stats.totalIncidents, icon:"alert",    tone:"red"   },
    { label:"Locations",       value:stats.totalLocations, icon:"location", tone:"amber" },
  ];

  const quickActions = [
    { label:"Manage Users",   icon:"users",    path:"/admin/users",     meta:"Roles, status and access" },
    { label:"View Locations", icon:"location", path:"/admin/locations", meta:"Zones and departments" },
    { label:"Manage Cameras", icon:"camera",   path:"/admin/cameras",   meta:"Streams and assignments" },
    { label:"Safety Rules",   icon:"rules",    path:"/admin/rules",     meta:"PPE policies by site" },
  ];

  const distributionTotal = Math.max(
    (stats.totalUsers || 0) + (stats.totalCameras || 0) + (stats.totalIncidents || 0) + (stats.totalLocations || 0),
    1
  );
  const maxMetric = Math.max(...cards.map(c => Number(c.value) || 0), 1);
  const userPct = ((stats.totalUsers || 0) / distributionTotal) * 100;
  const cameraPct = ((stats.totalCameras || 0) / distributionTotal) * 100;
  const incidentPct = ((stats.totalIncidents || 0) / distributionTotal) * 100;
  const ringStyle = {
    background: `conic-gradient(var(--tone-blue) 0 ${userPct}%, var(--tone-green) ${userPct}% ${userPct + cameraPct}%, var(--tone-red) ${userPct + cameraPct}% ${userPct + cameraPct + incidentPct}%, var(--tone-amber) ${userPct + cameraPct + incidentPct}% 100%)`,
  };

  const statusRows = [
    ["Users", stats.totalUsers, "users"],
    ["Cameras", stats.totalCameras, "camera"],
    ["Incidents", stats.totalIncidents, "alert"],
    ["Locations", stats.totalLocations, "location"],
  ];

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Admin Dashboard</div>
            <div className="dashboard-subtitle">Live system overview for VisionGuard operations</div>
          </div>
          <span className="topbar-badge"><Icon name="rules" size={16} /> Administrator</span>
        </div>

        {loading ? <p className="loading-text">Loading stats...</p> : (
          <>
            <div className="stats-grid">
              {cards.map((c, i) => {
                return (
                  <div key={c.label} className="stat-item" style={{animationDelay:`${i*0.08}s`}}>
                    <div className="stat-item-header">
                      <div className={`stat-icon tone-${c.tone}`}><Icon name={c.icon} /></div>
                      <span className="stat-label">{c.label}</span>
                    </div>
                    <div className={`stat-value tone-${c.tone}`}>{c.value ?? 0}</div>
                  </div>
                );
              })}
            </div>

            <div className="admin-analytics-grid">
              <section className="content-section analytics-panel">
                <div className="panel-heading">
                  <div>
                    <h2 className="section-title">Live Operations Mix</h2>
                    <p>Current platform distribution from the latest admin stats response.</p>
                  </div>
                  <span className="live-chip">Live snapshot</span>
                </div>
                <div className="donut-wrap">
                  <div className="donut-chart" style={ringStyle}>
                    <div>
                      <strong>{distributionTotal}</strong>
                      <span>Total signals</span>
                    </div>
                  </div>
                  <div className="chart-legend">
                    {cards.map(c => (
                      <div key={c.label}>
                        <span className={`legend-dot ${c.tone}`} />
                        <span>{c.label}</span>
                        <strong>{c.value ?? 0}</strong>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              <section className="content-section analytics-panel">
                <div className="panel-heading">
                  <div>
                    <h2 className="section-title">Operational Load</h2>
                    <p>Relative workload across core safety resources.</p>
                  </div>
                </div>
                <div className="bar-stack">
                  {cards.map(c => {
                    const width = Math.max(6, ((Number(c.value) || 0) / maxMetric) * 100);
                    return (
                      <div key={c.label} className="bar-row">
                        <div className="bar-row-label">
                          <span>{c.label}</span>
                          <strong>{c.value ?? 0}</strong>
                        </div>
                        <div className="bar-track">
                          <span className={`bar-fill ${c.tone}`} style={{width:`${width}%`}} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>

            <div className="content-section">
              <h2 className="section-title">Quick Actions</h2>
              <div className="quick-actions-grid">
                {quickActions.map(a => (
                  <button key={a.label} className="btn btn-ghost quick-action-btn" onClick={() => navigate(a.path)}>
                    <span className="quick-action-icon"><Icon name={a.icon} size={24} /></span>
                    <span>{a.label}</span>
                    <small>{a.meta}</small>
                  </button>
                ))}
              </div>
            </div>

            <div className="content-section">
              <h2 className="section-title">Database Records</h2>
              <table>
                <thead>
                  <tr><th>Dataset</th><th>Records</th><th>Source</th></tr>
                </thead>
                <tbody>
                  {statusRows.map(([label, count, icon]) => (
                    <tr key={label}>
                      <td style={{fontWeight:600}}>
                        <span className="table-icon"><Icon name={icon} size={16} /></span>
                        {label}
                      </td>
                      <td><span className="badge badge-blue">{count ?? 0}</span></td>
                      <td style={{color:"var(--text3)",fontSize:13}}>/admin/stats</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
