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

const statusClass = (s) => ({ compliant:"green", "non-compliant":"red", pending:"yellow" }[s] || "gray");

export default function ComplianceRecords() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [stats, setStats]     = useState({ compliant:0, nonCompliant:0, pending:0, total:0 });
  const [filters, setFilters] = useState({ status:"", location:"", dateFrom:"", dateTo:"" });

  useEffect(() => { if (!token) navigate("/"); fetchData(); }, []);

  const fetchData = async () => {
    try {
      const [recordsRes, statsRes] = await Promise.all([
        axios.get("http://localhost:8000/officer/compliance-records", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("http://localhost:8000/officer/compliance-stats",   { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      setRecords(recordsRes.data || []); setStats(statsRes.data || {});
    } catch { setError("Failed to load compliance records."); }
    finally { setLoading(false); }
  };

  const statCards = [
    { label:"Compliant",     value:stats.compliant,    icon:"✓", accentColor:"var(--success)" },
    { label:"Non-Compliant", value:stats.nonCompliant, icon:"✗", accentColor:"var(--danger)"  },
    { label:"Pending",       value:stats.pending,      icon:"⏱", accentColor:"var(--warning)" },
    { label:"Total Records", value:stats.total,        icon:"📊", accentColor:"var(--accent)"  },
  ];

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">

        <div className="topbar">
          <div className="topbar-title">Compliance Records</div>
          <span className="topbar-badge">📊 Track compliance status</span>
        </div>

        {!loading && (
          <div className="stats-grid">
            {statCards.map((c, i) => (
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
        )}

        <div className="content-section" style={{marginBottom:28}}>
          <h2 className="section-title">Filters</h2>
          <div className="form-grid">
            <div className="form-group">
              <label className="form-label">Status</label>
              <select className="form-input" value={filters.status} onChange={e => setFilters({...filters,status:e.target.value})}>
                <option value="">All</option>
                <option value="compliant">Compliant</option>
                <option value="non-compliant">Non-Compliant</option>
                <option value="pending">Pending</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Location</label>
              <input className="form-input" placeholder="Enter location" value={filters.location} onChange={e => setFilters({...filters,location:e.target.value})} />
            </div>
            <div className="form-group">
              <label className="form-label">From Date</label>
              <input type="date" className="form-input" value={filters.dateFrom} onChange={e => setFilters({...filters,dateFrom:e.target.value})} />
            </div>
            <div className="form-group">
              <label className="form-label">To Date</label>
              <input type="date" className="form-input" value={filters.dateTo} onChange={e => setFilters({...filters,dateTo:e.target.value})} />
            </div>
          </div>
          <div style={{marginTop:16}}>
            <button className="btn btn-ghost btn-sm" onClick={() => setFilters({status:"",location:"",dateFrom:"",dateTo:""})}>Clear Filters</button>
          </div>
        </div>

        {error && <div className="alert alert-error">{error}</div>}

        <div className="content-section">
          <h2 className="section-title">Records</h2>
          {loading ? <p className="loading-text">Loading records…</p> :
           records.length === 0 ? <p className="loading-text">No compliance records found.</p> : (
            <table>
              <thead><tr><th>Location</th><th>Date</th><th>Violations</th><th>Status</th><th>Officer</th><th>Notes</th></tr></thead>
              <tbody>
                {records.map((record, idx) => (
                  <tr key={idx}>
                    <td style={{fontWeight:600}}>{record.location}</td>
                    <td style={{color:"var(--text2)"}}>{new Date(record.date).toLocaleDateString()}</td>
                    <td>{record.violations || 0}</td>
                    <td><span className={`badge badge-${statusClass(record.status)}`}>{record.status}</span></td>
                    <td style={{color:"var(--text2)"}}>{record.officer || "—"}</td>
                    <td style={{color:"var(--text3)",fontSize:13}}>{record.notes || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>
    </div>
  );
}
