import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems as menuItems } from "./roleMenuItems";

const severityClass = (l) => ({ Critical:"red", High:"red", Medium:"yellow", Low:"green" }[l] || "gray");
const statusClass   = (s) => ({ resolved:"green", in_progress:"blue", open:"yellow" }[s] || "gray");

export default function OfficerDashboard() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [stats, setStats] = useState({ totalIncidents:0, pendingActions:0, resolvedToday:0, activeAlerts:0 });
  const [recentIncidents, setRecentIncidents] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) { navigate("/login"); return; }
    const fetchData = async () => {
      try {
        const [statsRes, incidentsRes] = await Promise.all([
          axios.get("http://127.0.0.1:8001/officer/stats",            { headers: { Authorization: `Bearer ${token}` } }),
          axios.get("http://127.0.0.1:8001/officer/incidents?limit=5", { headers: { Authorization: `Bearer ${token}` } }),
        ]);
        setStats(statsRes.data);
        setRecentIncidents(incidentsRes.data);
      } catch (err) { console.error(err); }
      finally { setLoading(false); }
    };
    fetchData();
  }, [navigate]);

  const cards = [
    { label:"Total Incidents", value:stats.totalIncidents, icon:"alert",     tone:"red"   },
    { label:"Pending Actions", value:stats.pendingActions, icon:"clipboard", tone:"amber" },
    { label:"Resolved Today",  value:stats.resolvedToday,  icon:"check",     tone:"green" },
    { label:"Active Alerts",   value:stats.activeAlerts,   icon:"bell",      tone:"blue"  },
  ];
  const maxMetric = Math.max(...cards.map(c => Number(c.value) || 0), 1);

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Safety Officer Dashboard</div>
            <div className="dashboard-subtitle">Monitor and respond to safety incidents</div>
          </div>
          <span className="topbar-badge"><Icon name="rules" size={16} /> Safety Officer</span>
        </div>

        {loading ? <p className="loading-text">Loading...</p> : (
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

            <div className="content-section analytics-panel" style={{marginBottom:28}}>
              <div className="panel-heading">
                <div>
                  <h2 className="section-title">Response Workload</h2>
                  <p>Live officer workload based on the latest stats response.</p>
                </div>
                <span className="live-chip">Live snapshot</span>
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
            </div>

            <div className="content-section" style={{marginBottom:28}}>
              <h2 className="section-title">Quick Actions</h2>
              <div className="quick-actions-grid">
                {menuItems.slice(1).map(item => (
                  <button key={item.label} className="btn btn-ghost quick-action-btn" onClick={() => navigate(item.path)}>
                    <span className="quick-action-icon">{item.icon}</span>
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {recentIncidents.length > 0 && (
              <div className="content-section">
                <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:24}}>
                  <h2 className="section-title" style={{margin:0}}>Recent Incidents</h2>
                  <button className="btn btn-ghost btn-sm" onClick={() => navigate("/officer/incidents")}>View All <Icon name="chevronRight" size={14} /></button>
                </div>
                <table>
                  <thead>
                    <tr><th>Type</th><th>Location</th><th>Severity</th><th>Status</th><th>Time</th></tr>
                  </thead>
                  <tbody>
                    {recentIncidents.slice(0,5).map(inc => (
                      <tr key={inc.id}>
                        <td style={{fontWeight:600}}><span className="table-icon"><Icon name="alert" size={16} /></span>{inc.violation_type}</td>
                        <td style={{color:"var(--text2)"}}>{inc.location}</td>
                        <td><span className={`badge badge-${severityClass(inc.severity_level)}`}>{inc.severity_level}</span></td>
                        <td><span className={`badge badge-${statusClass(inc.status)}`}>{inc.status}</span></td>
                        <td style={{color:"var(--text3)",fontSize:13}}>{new Date(inc.detected_at).toLocaleTimeString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
