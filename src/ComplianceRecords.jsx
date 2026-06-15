import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems as menuItems } from "./roleMenuItems";

const statusClass = (s) => ({ compliant:"green", "non-compliant":"red", pending:"yellow" }[s] || "gray");

export default function ComplianceRecords() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [stats, setStats]     = useState({ compliant:0, nonCompliant:0, pending:0, total:0 });
  const [filters, setFilters] = useState({ status:"", location:"", dateFrom:"", dateTo:"" });

  useEffect(() => { if (!token) navigate("/login"); fetchData(); }, []);

  const fetchData = async () => {
    try {
      const [recordsRes, statsRes] = await Promise.all([
        axios.get("http://127.0.0.1:8001/officer/compliance-records", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("http://127.0.0.1:8001/officer/compliance-stats",   { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      setRecords(recordsRes.data || []); setStats(statsRes.data || {});
    } catch { setError("Failed to load compliance records."); }
    finally { setLoading(false); }
  };

  const statCards = [
    { label:"Compliant",     value:stats.compliant,    icon:"check", tone:"green" },
    { label:"Non-Compliant", value:stats.nonCompliant, icon:"x",     tone:"red"   },
    { label:"Pending",       value:stats.pending,      icon:"clock", tone:"amber" },
    { label:"Total Records", value:stats.total,        icon:"chart", tone:"blue"  },
  ];
  const total = Math.max(stats.total || 0, 1);
  const compliantPct = ((stats.compliant || 0) / total) * 100;
  const pendingPct = ((stats.pending || 0) / total) * 100;
  const nonCompliantPct = Math.max(0, 100 - compliantPct - pendingPct);

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Compliance Records</div>
            <div className="dashboard-subtitle">Track location compliance, violations, and audit notes.</div>
          </div>
          <span className="topbar-badge"><Icon name="chart" size={16} /> Track compliance status</span>
        </div>

        {!loading && (
          <>
            <div className="stats-grid">
              {statCards.map((c, i) => {
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
                  <h2 className="section-title">Compliance Mix</h2>
                  <p>Visual breakdown from the current compliance summary.</p>
                </div>
                <span className="live-chip">Audit snapshot</span>
              </div>
              <div className="bar-track compliance-stack">
                <span className="bar-fill green" style={{width:`${compliantPct}%`}} />
                <span className="bar-fill amber" style={{width:`${pendingPct}%`}} />
                <span className="bar-fill red" style={{width:`${nonCompliantPct}%`}} />
              </div>
              <div className="chart-legend" style={{marginTop:18}}>
                <div><span className="legend-dot green" /><span>Compliant</span><strong>{stats.compliant ?? 0}</strong></div>
                <div><span className="legend-dot amber" /><span>Pending</span><strong>{stats.pending ?? 0}</strong></div>
                <div><span className="legend-dot red" /><span>Non-compliant</span><strong>{stats.nonCompliant ?? 0}</strong></div>
              </div>
            </div>
          </>
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
          {loading ? <p className="loading-text">Loading records...</p> :
           records.length === 0 ? <p className="loading-text">No compliance records found.</p> : (
            <table>
              <thead><tr><th>Location</th><th>Date</th><th>Violations</th><th>Status</th><th>Officer</th><th>Notes</th></tr></thead>
              <tbody>
                {records.map((record, idx) => (
                  <tr key={idx}>
                    <td style={{fontWeight:600}}><span className="table-icon"><Icon name="location" size={16} /></span>{record.location}</td>
                    <td style={{color:"var(--text2)"}}>{new Date(record.date).toLocaleDateString()}</td>
                    <td>{record.violations || 0}</td>
                    <td><span className={`badge badge-${statusClass(record.status)}`}>{record.status}</span></td>
                    <td style={{color:"var(--text2)"}}>{record.officer || "Unassigned"}</td>
                    <td style={{color:"var(--text3)",fontSize:13}}>{record.notes || "No notes"}</td>
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
