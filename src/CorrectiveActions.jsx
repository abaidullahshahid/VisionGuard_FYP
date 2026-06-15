import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems as menuItems } from "./roleMenuItems";

const priorityClass = (p) => ({ Critical:"red", High:"red", Medium:"yellow", Low:"green" }[p] || "gray");
const statusClass   = (s) => ({ Resolved:"green", "In Progress":"blue", Pending:"yellow" }[s] || "gray");

export default function CorrectiveActions() {
  const navigate  = useNavigate();
  const routeLoc  = useLocation();
  const token     = sessionStorage.getItem("token");
  const [actions, setActions]     = useState([]);
  const [users, setUsers]         = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [showForm, setShowForm]   = useState(false);
  const [error, setError]         = useState("");
  const [success, setSuccess]     = useState("");
  const [form, setForm] = useState({ incident_id:routeLoc.state?.incidentId||"", assigned_to:"", description:"", deadline:"", priority:"High" });

  useEffect(() => {
    if (!token) navigate("/login");
    fetchData();
    if (routeLoc.state?.incidentId) setShowForm(true);
  }, []);

  const fetchData = async () => {
    try {
      const [actRes, userRes, incRes] = await Promise.all([
        axios.get("http://127.0.0.1:8001/officer/corrective-actions", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("http://127.0.0.1:8001/admin/users",                { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("http://127.0.0.1:8001/officer/incidents",          { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      setActions(actRes.data);
      setUsers(userRes.data.filter(u => u.status === "active"));
      setIncidents(incRes.data);
    } catch { setError("Failed to load data."); }
    finally { setLoading(false); }
  };

  const handleAssign = async (e) => {
    e.preventDefault(); setError(""); setSuccess("");
    try {
      await axios.post("http://127.0.0.1:8001/officer/corrective-actions", form, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("Corrective action assigned!");
      setShowForm(false);
      setForm({ incident_id:"", assigned_to:"", description:"", deadline:"", priority:"High" });
      fetchData();
    } catch { setError("Failed to assign corrective action."); }
  };

  const handleStatusUpdate = async (id, status) => {
    try {
      await axios.patch(`http://127.0.0.1:8001/officer/corrective-actions/${id}`, { status }, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("Status updated."); fetchData();
    } catch { setError("Failed to update status."); }
  };

  const getUserName     = (id) => users.find(u => u.id === id)?.name || "Unassigned";
  const getIncidentType = (id) => { const inc = incidents.find(i => i.id === id); return inc ? inc.violation_type : `#${id}`; };

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Corrective Actions</div>
            <div className="dashboard-subtitle">Assign, monitor, and close incident response tasks.</div>
          </div>
          <button className="btn btn-primary" onClick={() => { setShowForm(!showForm); setError(""); setSuccess(""); }}>
            {showForm ? <><Icon name="x" size={16} /> Cancel</> : <><Icon name="plus" size={16} /> Assign Action</>}
          </button>
        </div>

        {error   && <div className="alert alert-error">{error}</div>}
        {success && <div className="alert alert-success">{success}</div>}

        {showForm && (
          <div className="content-section" style={{marginBottom:28}}>
            <h2 className="section-title">Assign Corrective Action</h2>
            <form onSubmit={handleAssign}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label">Incident</label>
                  <select className="form-input" value={form.incident_id} onChange={e => setForm({...form,incident_id:e.target.value})} required>
                    <option value="">Select Incident</option>
                    {incidents.map(inc => <option key={inc.id} value={inc.id}>#{inc.id} - {inc.violation_type} ({inc.location})</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Assign To</label>
                  <select className="form-input" value={form.assigned_to} onChange={e => setForm({...form,assigned_to:e.target.value})} required>
                    <option value="">Select Personnel</option>
                    {users.map(u => <option key={u.id} value={u.id}>{u.name} ({u.role})</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Priority</label>
                  <select className="form-input" value={form.priority} onChange={e => setForm({...form,priority:e.target.value})}>
                    {["Low","Medium","High","Critical"].map(p => <option key={p} value={p}>{p}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Deadline</label>
                  <input type="date" className="form-input" value={form.deadline} onChange={e => setForm({...form,deadline:e.target.value})} required />
                </div>
              </div>
              <div className="form-group" style={{marginTop:16}}>
                <label className="form-label">Description</label>
                <textarea className="form-input" placeholder="Describe the corrective action required..." value={form.description} onChange={e => setForm({...form,description:e.target.value})} required rows={3} style={{resize:"vertical"}} />
              </div>
              <div style={{marginTop:20}}>
                <button type="submit" className="btn btn-primary"><Icon name="clipboard" size={16} /> Assign Action</button>
              </div>
            </form>
          </div>
        )}

        <div className="content-section">
          <h2 className="section-title">All Corrective Actions</h2>
          {loading ? <p className="loading-text">Loading actions...</p> :
           actions.length === 0 ? <p className="loading-text">No corrective actions found.</p> : (
            <table>
              <thead><tr><th>#</th><th>Incident</th><th>Assigned To</th><th>Priority</th><th>Deadline</th><th>Status</th><th>Update</th></tr></thead>
              <tbody>
                {actions.map((action, idx) => (
                  <tr key={action.id}>
                    <td style={{color:"var(--text3)",fontSize:13}}>{idx+1}</td>
                    <td style={{fontWeight:600}}><span className="table-icon"><Icon name="clipboard" size={16} /></span>{getIncidentType(action.incident_id)}</td>
                    <td style={{color:"var(--text2)"}}>{getUserName(action.assigned_to)}</td>
                    <td><span className={`badge badge-${priorityClass(action.priority)}`}>{action.priority}</span></td>
                    <td style={{color:"var(--text2)",fontSize:13}}>{action.deadline}</td>
                    <td><span className={`badge badge-${statusClass(action.status)}`}>{action.status}</span></td>
                    <td>
                      <select className="form-input" style={{padding:"6px 10px",fontSize:12}} value={action.status} onChange={e => handleStatusUpdate(action.id, e.target.value)}>
                        <option value="Pending">Pending</option>
                        <option value="In Progress">In Progress</option>
                        <option value="Resolved">Resolved</option>
                      </select>
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
