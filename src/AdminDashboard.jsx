import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";

const menuItems = [
  { label:"Dashboard",    icon:"🏠", path:"/admin"           },
  { label:"Manage Users", icon:"👥", path:"/admin/users"     },
  { label:"Locations",    icon:"📍", path:"/admin/locations" },
  { label:"Cameras",      icon:"📷", path:"/admin/cameras"   },
  { label:"Safety Rules", icon:"⚙️", path:"/admin/rules"     },
];

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState({ totalUsers:0, totalCameras:0, totalIncidents:0, totalLocations:0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) { navigate("/"); return; }
    axios.get("http://localhost:8000/admin/stats", { headers: { Authorization: `Bearer ${token}` } })
      .then(r => setStats(r.data))
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, [navigate]);

  const cards = [
    { label:"Total Users",     value:stats.totalUsers,     icon:"👥", accent:"var(--accent)"   },
    { label:"Active Cameras",  value:stats.totalCameras,   icon:"📷", accent:"var(--success)"  },
    { label:"Total Incidents", value:stats.totalIncidents, icon:"⚠️", accent:"var(--danger)"   },
    { label:"Locations",       value:stats.totalLocations, icon:"📍", accent:"var(--warning)"  },
  ];

  const quickActions = [
    { label:"Manage Users",   icon:"👥", path:"/admin/users"     },
    { label:"View Locations", icon:"📍", path:"/admin/locations" },
    { label:"Manage Cameras", icon:"📷", path:"/admin/cameras"   },
    { label:"Safety Rules",   icon:"⚙️", path:"/admin/rules"     },
  ];

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Admin Dashboard</div>
            <div style={{color:"var(--text2)",fontSize:14,marginTop:4}}>Welcome back — here's your system overview</div>
          </div>
          <span className="topbar-badge">🛡️ Administrator</span>
        </div>

        {loading ? <p className="loading-text">Loading stats…</p> : (
          <>
            <div className="stats-grid">
              {cards.map((c, i) => (
                <div key={c.label} className="stat-item" style={{animationDelay:`${i*0.08}s`}}>
                  <div className="stat-item-header">
                    <div className="stat-icon" style={{background:`rgba(${c.accent.includes("accent")?"99,102,241":c.accent.includes("success")?"16,185,129":c.accent.includes("danger")?"244,63,94":"245,158,11"},0.12)`}}>{c.icon}</div>
                    <span className="stat-label">{c.label}</span>
                  </div>
                  <div className="stat-value" style={{
                    background:`linear-gradient(135deg, ${c.accent}, var(--text2))`,
                    WebkitBackgroundClip:"text", WebkitTextFillColor:"transparent", backgroundClip:"text"
                  }}>{c.value ?? 0}</div>
                </div>
              ))}
            </div>

            <div className="content-section">
              <h2 className="section-title">Quick Actions</h2>
              <div style={{display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(200px, 1fr))", gap:"16px"}}>
                {quickActions.map(a => (
                  <button key={a.label} className="btn btn-ghost"
                    style={{padding:"20px", flexDirection:"column", gap:"12px", height:"auto", borderRadius:"12px"}}
                    onClick={() => navigate(a.path)}>
                    <span style={{fontSize:"28px"}}>{a.icon}</span>
                    <span>{a.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="content-section">
              <h2 className="section-title">System Status</h2>
              <table>
                <thead>
                  <tr><th>Component</th><th>Status</th><th>Uptime</th><th>Last Check</th></tr>
                </thead>
                <tbody>
                  {[
                    ["Database Server", "Operational", "99.9%", "Just now"],
                    ["Camera API",      "Operational", "99.7%", "1 min ago"],
                    ["AI Safety Engine","Operational", "98.5%", "2 mins ago"],
                    ["Alert Service",   "Operational", "99.9%", "Just now"],
                  ].map(([comp, status, uptime, check]) => (
                    <tr key={comp}>
                      <td style={{fontWeight:600}}>{comp}</td>
                      <td><span className="badge badge-green">● {status}</span></td>
                      <td style={{color:"var(--text2)"}}>{uptime}</td>
                      <td style={{color:"var(--text3)",fontSize:13}}>{check}</td>
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