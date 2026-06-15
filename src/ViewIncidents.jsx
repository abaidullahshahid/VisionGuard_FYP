import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems as menuItems } from "./roleMenuItems";

const sevClass = (l) => ({ Critical:"red", High:"red", Medium:"yellow", Low:"green" }[l] || "gray");
const stsClass = (s) => ({ resolved:"green", in_progress:"blue", open:"yellow" }[s] || "gray");

export default function ViewIncidents() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [incidents, setIncidents] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState({ status:"", severity:"", location:"" });

  const [showModal, setShowModal] = useState(false);
  const [newInc, setNewInc] = useState({ violation_type:"", severity_level:"Medium", location_id:"" });
  const [reportSubmitting, setReportSubmitting] = useState(false);

  useEffect(() => {
    if (!token) navigate("/login");
    fetchIncidents();
    fetchLocations();
  }, []);

  const fetchIncidents = async () => {
    try {
      const params = new URLSearchParams();
      if (filters.status)   params.append("status", filters.status);
      if (filters.severity) params.append("severity", filters.severity);
      if (filters.location) params.append("location", filters.location);
      const res = await axios.get(`http://127.0.0.1:8001/officer/incidents?${params}`, { headers: { Authorization: `Bearer ${token}` } });
      setIncidents(res.data);
    } catch { setError("Failed to load incidents."); }
    finally { setLoading(false); }
  };

  const fetchLocations = async () => {
    try {
      const res = await axios.get("http://127.0.0.1:8001/officer/locations", { headers: { Authorization: `Bearer ${token}` } });
      setLocations(res.data);
      if (res.data.length > 0) setNewInc(prev => ({ ...prev, location_id: res.data[0].id }));
    } catch (err) { console.error("Failed to fetch locations", err); }
  };

  const handleReport = async (e) => {
    e.preventDefault();
    if (!newInc.violation_type || !newInc.location_id) return;
    setReportSubmitting(true);
    try {
      await axios.post("http://127.0.0.1:8001/officer/incidents", {
        violation_type: newInc.violation_type,
        severity_level: newInc.severity_level,
        location_id: parseInt(newInc.location_id)
      }, { headers: { Authorization: `Bearer ${token}` } });
      setShowModal(false);
      setNewInc({ violation_type:"", severity_level:"Medium", location_id: locations[0]?.id || "" });
      fetchIncidents();
    } catch (err) {
      setError("Failed to report incident.");
    } finally {
      setReportSubmitting(false);
    }
  };

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">View Incidents</div>
            <span className="topbar-badge"><Icon name="alert" size={16} /> {incidents.length} incidents</span>
          </div>
          <button className="btn btn-primary" onClick={() => setShowModal(!showModal)}>
            {showModal ? <><Icon name="x" size={16} /> Cancel</> : <><Icon name="plus" size={16} /> Report Incident</>}
          </button>
        </div>

        {error && <div className="alert alert-error">{error}</div>}

        {showModal && (
          <div className="content-section" style={{marginBottom:28}}>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:16}}>
              <h2 className="section-title" style={{margin:0}}>Report New Incident</h2>
            </div>
            <form onSubmit={handleReport}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label">Violation Type</label>
                  <input className="form-input" placeholder="e.g. Missing Hard Hat" required
                    value={newInc.violation_type} onChange={e => setNewInc({...newInc, violation_type: e.target.value})} />
                </div>
                <div className="form-group">
                  <label className="form-label">Location</label>
                  <select className="form-input" required value={newInc.location_id} onChange={e => setNewInc({...newInc, location_id: e.target.value})}>
                    <option value="" disabled>Select Location</option>
                    {locations.map(loc => <option key={loc.id} value={loc.id}>{loc.name}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Severity Level</label>
                  <select className="form-input" value={newInc.severity_level} onChange={e => setNewInc({...newInc, severity_level: e.target.value})}>
                    <option value="Critical">Critical</option>
                    <option value="High">High</option>
                    <option value="Medium">Medium</option>
                    <option value="Low">Low</option>
                  </select>
                </div>
                <div className="form-group" style={{justifyContent:"flex-end"}}>
                  <button type="submit" className="btn btn-primary" style={{marginTop:"auto"}} disabled={reportSubmitting}>
                    {reportSubmitting ? "Reporting..." : "Submit Report"}
                  </button>
                </div>
              </div>
            </form>
          </div>
        )}

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
              <input className="form-input" placeholder="Filter by location..." value={filters.location} onChange={e => setFilters({...filters,location:e.target.value})} />
            </div>
            <div className="form-group" style={{justifyContent:"flex-end"}}>
              <button className="btn btn-ghost" style={{marginTop:"auto"}} onClick={fetchIncidents}>Apply Filters</button>
            </div>
          </div>
        </div>

        <div className="content-section">
          <h2 className="section-title">Incidents Log</h2>
          {loading ? <p className="loading-text">Loading incidents...</p> :
           incidents.length === 0 ? <p className="loading-text">No incidents found.</p> : (
            <table>
              <thead><tr><th>#</th><th>Type</th><th>Location</th><th>Severity</th><th>Status</th><th>Detected</th><th>Action</th></tr></thead>
              <tbody>
                {incidents.map((inc, idx) => (
                  <tr key={inc.id}>
                    <td style={{color:"var(--text3)",fontSize:13}}>{idx+1}</td>
                    <td style={{fontWeight:600}}><span className="table-icon"><Icon name="alert" size={16} /></span>{inc.violation_type}</td>
                    <td style={{color:"var(--text2)"}}>{inc.location}</td>
                    <td><span className={`badge badge-${sevClass(inc.severity_level)}`}>{inc.severity_level}</span></td>
                    <td><span className={`badge badge-${stsClass(inc.status)}`}>{inc.status}</span></td>
                    <td style={{color:"var(--text3)",fontSize:13}}>{new Date(inc.detected_at).toLocaleString()}</td>
                    <td>
                      <button className="btn btn-ghost btn-sm"
                        onClick={() => navigate("/officer/actions", { state:{ incidentId: inc.id } })}>
                        Assign <Icon name="chevronRight" size={14} />
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
