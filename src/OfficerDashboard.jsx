import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";

const menuItems = [
  { label:"Dashboard",          icon:"🏠", path:"/officer"            },
  { label:"View Incidents",     icon:"⚠️", path:"/officer/incidents"  },
  { label:"Corrective Actions", icon:"📋", path:"/officer/actions"    },
  { label:"Live Video Feed",    icon:"📹", path:"/officer/live"       },
  { label:"Compliance Records", icon:"📊", path:"/officer/compliance" },
];

const severityClass = (l) => ({ Critical:"red", High:"red", Medium:"yellow", Low:"green" }[l] || "gray");
const statusClass   = (s) => ({ resolved:"green", in_progress:"blue", open:"yellow" }[s] || "gray");

export default function OfficerDashboard() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [stats, setStats] = useState({ totalIncidents:0, pendingActions:0, resolvedToday:0, activeAlerts:0 });
  const [recentIncidents, setRecentIncidents] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) { navigate("/"); return; }
    const fetchData = async () => {
      try {
        const [statsRes, incidentsRes] = await Promise.all([
          axios.get("http://localhost:8000/officer/stats",           { headers: { Authorization: `Bearer ${token}` } }),
          axios.get("http://localhost:8000/officer/incidents?limit=5", { headers: { Authorization: `Bearer ${token}` } }),
        ]);
        setStats(statsRes.data);
        setRecentIncidents(incidentsRes.data);
      } catch (err) { console.error(err); }
      finally { setLoading(false); }
    };
    fetchData();
  }, [navigate]);

  const cards = [
    { label:"Total Incidents", value:stats.totalIncidents, icon:"⚠️", accentColor:"var(--danger)"  },
    { label:"Pending Actions", value:stats.pendingActions, icon:"📋", accentColor:"var(--warning)" },
    { label:"Resolved Today",  value:stats.resolvedToday,  icon:"✅", accentColor:"var(--success)" },
    { label:"Active Alerts",   value:stats.activeAlerts,   icon:"🔔", accentColor:"var(--accent)"  },
  ];

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Safety Officer Dashboard</div>
            <div style={{color:"var(--text2)",fontSize:14,marginTop:4}}>Monitor and respond to safety incidents</div>
          </div>
          <span className="topbar-badge">🛡️ Safety Officer</span>
        </div>

        {loading ? <p className="loading-text">Loading…</p> : (
          <>
            <div className="stats-grid">
              {cards.map((c, i) => (
                <div key={c.label} className="stat-item" style={{animationDelay:`${i*0.08}s`}}>
                  <div className="stat-item-header">
                    <div className="stat-icon">{c.icon}</div>
                    <span className="stat-label">{c.label}</span>
                  </div>
                  <div className="stat-value" style={{
                    background:`linear-gradient(135deg, ${c.accentColor}, var(--text2))`,
                    WebkitBackgroundClip:"text", WebkitTextFillColor:"transparent", backgroundClip:"text"
                  }}>{c.value ?? 0}</div>
                </div>
              ))}
            </div>

            {/* Quick Actions */}
            <div className="content-section" style={{marginBottom:28}}>
              <h2 className="section-title">Quick Actions</h2>
              <div style={{display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:16}}>
                {menuItems.slice(1).map(item => (
                  <button key={item.label} className="btn btn-ghost"
                    style={{padding:"20px 16px", flexDirection:"column", gap:"12px", height:"auto", borderRadius:"12px"}}
                    onClick={() => navigate(item.path)}>
                    <span style={{fontSize:"28px"}}>{item.icon}</span>
                    <span style={{fontSize:13}}>{item.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Recent Incidents */}
            {recentIncidents.length > 0 && (
              <div className="content-section">
                <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:24}}>
                  <h2 className="section-title" style={{margin:0}}>Recent Incidents</h2>
                  <button className="btn btn-ghost btn-sm" onClick={() => navigate("/officer/incidents")}>View All →</button>
                </div>
                <table>
                  <thead>
                    <tr><th>Type</th><th>Location</th><th>Severity</th><th>Status</th><th>Time</th></tr>
                  </thead>
                  <tbody>
                    {recentIncidents.slice(0,5).map(inc => (
                      <tr key={inc.id}>
                        <td style={{fontWeight:600}}>{inc.violation_type}</td>
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