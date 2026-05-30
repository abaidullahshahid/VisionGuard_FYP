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

const sevClass = (l) => ({ Critical:"red", High:"red", Medium:"yellow", Low:"green" }[l] || "gray");
const stsClass = (s) => ({ resolved:"green", in_progress:"blue", open:"yellow" }[s] || "gray");

export default function ViewIncidents() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState({ status:"", severity:"", location:"" });

  useEffect(() => {
    if (!token) navigate("/");
    fetchIncidents();
  }, []);

  const fetchIncidents = async () => {
    try {
      const params = new URLSearchParams();
      if (filters.status)   params.append("status", filters.status);
      if (filters.severity) params.append("severity", filters.severity);
      if (filters.location) params.append("location", filters.location);
      const res = await axios.get(`http://localhost:8000/officer/incidents?${params}`, { headers: { Authorization: `Bearer ${token}` } });
      setIncidents(res.data);
    } catch { setError("Failed to load incidents."); }
    finally { setLoading(false); }
  };

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">

        <div className="topbar">
          <div className="topbar-title">View Incidents</div>
          <span className="topbar-badge">⚠️ {incidents.length} incidents</span>
        </div>

        {error && <div className="alert alert-error">{error}</div>}

        {/* Filters */}
        <div className="content-section" style={{marginBottom:28}}>
          <h2 className="section-title">Filters</h2>
          <div className="form-grid">
            <div className="form-group">
              <label className="form-label">Status</label>
              <select className="form-input" value={filters.status} onChange={e => setFilters({...filters,status:e.target.value})}>
                <option value="">All Statuses</option>
                <option value="open">Open</option>
                <option value="in_progress">In Progress</option>
                <option value="resolved">Resolved</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Severity</label>
              <select className="form-input" value={filters.severity} onChange={e => setFilters({...filters,severity:e.target.value})}>
                <option value="">All Severities</option>
                <option value="Critical">Critical</option>
                <option value="High">High</option>
                <option value="Medium">Medium</option>
                <option value="Low">Low</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Location</label>
              <input className="form-input" placeholder="Filter by location…" value={filters.location} onChange={e => setFilters({...filters,location:e.target.value})} />
            </div>
            <div className="form-group" style={{justifyContent:"flex-end"}}>
              <button className="btn btn-primary" style={{marginTop:"auto"}} onClick={fetchIncidents}>Apply Filters</button>
            </div>
          </div>
        </div>

        <div className="content-section">
          <h2 className="section-title">Incidents Log</h2>
          {loading ? <p className="loading-text">Loading incidents…</p> :
           incidents.length === 0 ? <p className="loading-text">No incidents found.</p> : (
            <table>
              <thead><tr><th>#</th><th>Type</th><th>Location</th><th>Severity</th><th>Status</th><th>Detected</th><th>Action</th></tr></thead>
              <tbody>
                {incidents.map((inc, idx) => (
                  <tr key={inc.id}>
                    <td style={{color:"var(--text3)",fontSize:13}}>{idx+1}</td>
                    <td style={{fontWeight:600}}>{inc.violation_type}</td>
                    <td style={{color:"var(--text2)"}}>{inc.location}</td>
                    <td><span className={`badge badge-${sevClass(inc.severity_level)}`}>{inc.severity_level}</span></td>
                    <td><span className={`badge badge-${stsClass(inc.status)}`}>{inc.status}</span></td>
                    <td style={{color:"var(--text3)",fontSize:13}}>{new Date(inc.detected_at).toLocaleString()}</td>
                    <td>
                      <button className="btn btn-ghost btn-sm"
                        onClick={() => navigate("/officer/actions", { state:{ incidentId: inc.id } })}>
                        Assign →
                      </button>
                    </td>
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