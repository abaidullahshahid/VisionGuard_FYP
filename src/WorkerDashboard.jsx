import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API_BASE } from "./api";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { workerMenuItems as menuItems } from "./roleMenuItems";

export default function WorkerDashboard() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [stats, setStats] = useState({ availableLocations:0, assignedActions:0, completedActions:0, openIncidents:0 });
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) navigate("/login");
    const fetchData = async () => {
      try {
        const [statsRes, assignmentsRes] = await Promise.all([
          axios.get(`${API_BASE}/worker/stats`,       { headers: { Authorization: `Bearer ${token}` } }),
          axios.get(`${API_BASE}/worker/assignments`, { headers: { Authorization: `Bearer ${token}` } }),
        ]);
        setStats(statsRes.data || {});
        setAssignments(assignmentsRes.data || []);
      } catch (err) { console.error(err); }
      finally { setLoading(false); }
    };
    fetchData();
  }, [navigate]);

  const cards = [
    { label:"Assigned Locations", value:stats.assignedLocations ?? 0, icon:"location",  tone:"blue"  },
    { label:"Assigned Actions",    value:stats.assignedActions ?? 0,                           icon:"clipboard", tone:"amber" },
    { label:"Completed Actions",   value:stats.completedActions ?? 0,                          icon:"check",     tone:"green" },
    { label:"Open Incidents",      value:stats.openIncidents ?? 0,                             icon:"alert",     tone:"red"   },
  ];
  const maxMetric = Math.max(...cards.map(c => Number(c.value) || 0), 1);
  const totalRecords = cards.reduce((sum, c) => sum + (Number(c.value) || 0), 0);
  const availablePct = totalRecords ? ((Number(cards[0].value) || 0) / totalRecords) * 100 : 0;
  const assignedPct = totalRecords ? ((Number(cards[1].value) || 0) / totalRecords) * 100 : 0;
  const completedPct = totalRecords ? ((Number(cards[2].value) || 0) / totalRecords) * 100 : 0;
  const ringStyle = {
    background: totalRecords
      ? `conic-gradient(var(--tone-blue) 0 ${availablePct}%, var(--tone-amber) ${availablePct}% ${availablePct + assignedPct}%, var(--tone-green) ${availablePct + assignedPct}% ${availablePct + assignedPct + completedPct}%, var(--tone-red) ${availablePct + assignedPct + completedPct}% 100%)`
      : "conic-gradient(var(--chart-muted) 0 100%)",
  };

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="worker" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Worker Dashboard</div>
            <div className="dashboard-subtitle">Your safety overview and assigned workplaces</div>
          </div>
          <span className="topbar-badge"><Icon name="worker" size={16} /> Field Worker</span>
        </div>

        {loading ? <p className="loading-text">Loading dashboard...</p> : (
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
                    <h2 className="section-title">Work Overview</h2>
                    <p>All worker metrics are calculated from current database records.</p>
                  </div>
                  <span className="live-chip">Database backed</span>
                </div>
                <div className="donut-wrap">
                  <div className="donut-chart" style={ringStyle}>
                    <div>
                      <strong>{totalRecords}</strong>
                      <span>Total records</span>
                    </div>
                  </div>
                  <div className="chart-legend">
                    <div><span className="legend-dot blue" /><span>Assigned locations</span><strong>{stats.assignedLocations ?? 0}</strong></div>
                    <div><span className="legend-dot amber" /><span>Assigned actions</span><strong>{stats.assignedActions ?? 0}</strong></div>
                    <div><span className="legend-dot green" /><span>Completed actions</span><strong>{stats.completedActions ?? 0}</strong></div>
                    <div><span className="legend-dot red" /><span>Open incidents</span><strong>{stats.openIncidents ?? 0}</strong></div>
                  </div>
                </div>
              </section>

              <section className="content-section analytics-panel">
                <div className="panel-heading">
                  <div>
                    <h2 className="section-title">Operational Load</h2>
                    <p>Relative view of locations, corrective actions, and incident load.</p>
                  </div>
                </div>
                <div className="bar-stack">
                  {cards.map(item => {
                    const width = Math.max(6, ((Number(item.value) || 0) / maxMetric) * 100);
                    return (
                      <div key={item.label} className="bar-row">
                        <div className="bar-row-label"><span>{item.label}</span><strong>{item.value ?? 0}</strong></div>
                        <div className="bar-track"><span className={`bar-fill ${item.tone}`} style={{width:`${width}%`}} /></div>
                      </div>
                    );
                  })}
                </div>
              </section>
            </div>

            <div className="content-section" style={{marginBottom:28}}>
              <h2 className="section-title">Quick Access</h2>
              <div className="quick-actions-grid">
                {menuItems.slice(1).map(item => (
                  <button key={item.label} className="btn btn-ghost quick-action-btn" onClick={() => navigate(item.path)}>
                    <span className="quick-action-icon">{item.icon}</span>
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {assignments.length > 0 && (
              <div className="content-section" style={{marginBottom:28}}>
                <h2 className="section-title">Your Assignments</h2>
                <table>
                  <thead><tr><th>Location</th><th>Assigned Date</th></tr></thead>
                  <tbody>
                    {assignments.slice(0,5).map((a, idx) => (
                      <tr key={idx}>
                        <td style={{fontWeight:600}}><span className="table-icon"><Icon name="location" size={16} /></span>{a.location || "Location"}</td>
                        <td style={{color:"var(--text2)",fontSize:13}}>{new Date(a.date).toLocaleDateString()}</td>
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
