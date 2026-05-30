import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";

const menuItems = [
  { label:"Dashboard",           icon:"🏠", path:"/worker"              },
  { label:"Locations",           icon:"📍", path:"/worker/locations"    },
  { label:"Safety Instructions", icon:"📖", path:"/worker/instructions" },
];

export default function WorkerDashboard() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [stats, setStats] = useState({ assignedLocations:0, safetyScore:0, tasksCompleted:0, activeAlerts:0 });
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) navigate("/");
    const fetchData = async () => {
      try {
        const [statsRes, assignmentsRes] = await Promise.all([
          axios.get("http://localhost:8000/worker/stats",       { headers: { Authorization: `Bearer ${token}` } }),
          axios.get("http://localhost:8000/worker/assignments", { headers: { Authorization: `Bearer ${token}` } }),
        ]);
        setStats(statsRes.data || {});
        setAssignments(assignmentsRes.data || []);
      } catch (err) { console.error(err); }
      finally { setLoading(false); }
    };
    fetchData();
  }, [navigate]);

  const cards = [
    { label:"Assigned Locations", value:stats.assignedLocations,      icon:"📍", accentColor:"var(--accent)"  },
    { label:"Safety Score",       value:`${stats.safetyScore || 0}%`, icon:"⭐", accentColor:"var(--success)" },
    { label:"Tasks Completed",    value:stats.tasksCompleted,          icon:"✓",  accentColor:"var(--success)" },
    { label:"Active Alerts",      value:stats.activeAlerts,            icon:"🔔", accentColor:"var(--danger)"  },
  ];

  const tips = [
    { icon:"👷", text:"Always wear your safety gear at all times"          },
    { icon:"👁️", text:"Report any hazards immediately to your supervisor"  },
    { icon:"📋", text:"Follow all workplace safety rules and procedures"   },
    { icon:"🤝", text:"Help your colleagues stay safe and aware"           },
  ];

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="worker" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Worker Dashboard</div>
            <div style={{color:"var(--text2)",fontSize:14,marginTop:4}}>Your safety overview and assignments</div>
          </div>
          <span className="topbar-badge">👷 Field Worker</span>
        </div>

        {loading ? <p className="loading-text">Loading dashboard…</p> : (
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

            <div className="content-section" style={{marginBottom:28}}>
              <h2 className="section-title">Quick Access</h2>
              <div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:16}}>
                {menuItems.slice(1).map(item => (
                  <button key={item.label} className="btn btn-ghost"
                    style={{padding:"24px", flexDirection:"column", gap:"12px", height:"auto", borderRadius:"12px"}}
                    onClick={() => navigate(item.path)}>
                    <span style={{fontSize:"32px"}}>{item.icon}</span>
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {assignments.length > 0 && (
              <div className="content-section" style={{marginBottom:28}}>
                <h2 className="section-title">Your Assignments</h2>
                <table>
                  <thead><tr><th>Location</th><th>Shift</th><th>Date</th><th>Status</th></tr></thead>
                  <tbody>
                    {assignments.slice(0,5).map((a, idx) => (
                      <tr key={idx}>
                        <td style={{fontWeight:600}}>{a.location || "Location"}</td>
                        <td style={{color:"var(--text2)"}}>{a.shift || "Full Shift"}</td>
                        <td style={{color:"var(--text2)",fontSize:13}}>{new Date(a.date).toLocaleDateString()}</td>
                        <td><span className={`badge badge-${a.status==="active"?"green":"yellow"}`}>{a.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="content-section">
              <h2 className="section-title">Daily Safety Tips</h2>
              <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(220px,1fr))",gap:16}}>
                {tips.map((tip, i) => (
                  <div key={i} style={{
                    padding:"20px", borderRadius:"12px",
                    background:"rgba(255,255,255,0.03)",
                    border:"1px solid var(--border)",
                    display:"flex", alignItems:"flex-start", gap:14,
                    transition:"all 0.25s ease"
                  }}>
                    <span style={{fontSize:28,flexShrink:0}}>{tip.icon}</span>
                    <p style={{margin:0,fontSize:13,color:"var(--text2)",fontWeight:500,lineHeight:1.5}}>{tip.text}</p>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
