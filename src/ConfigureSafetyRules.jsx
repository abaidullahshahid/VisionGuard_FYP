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

const severityClass = (l) => ({ Critical:"red", High:"red", Medium:"yellow", Low:"green" }[l] || "gray");

export default function ConfigureSafetyRules() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [rules, setRules]         = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [showForm, setShowForm]   = useState(false);
  const [error, setError]         = useState("");
  const [success, setSuccess]     = useState("");
  const [form, setForm] = useState({ location_id:"", ppe_type:"Helmet", is_restricted_area:false, severity_level:"High" });

  useEffect(() => { if (!token) navigate("/"); fetchData(); }, []);

  const fetchData = async () => {
    try {
      const [rulesRes, locRes] = await Promise.all([
        axios.get("http://localhost:8000/admin/safety-rules", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("http://localhost:8000/admin/locations",    { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      setRules(rulesRes.data); setLocations(locRes.data);
    } catch { setError("Failed to load data."); }
    finally { setLoading(false); }
  };

  const handleAdd = async (e) => {
    e.preventDefault(); setError(""); setSuccess("");
    try {
      await axios.post("http://localhost:8000/admin/safety-rules", form, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("Safety rule added!");
      setShowForm(false);
      setForm({ location_id:"", ppe_type:"Helmet", is_restricted_area:false, severity_level:"High" });
      fetchData();
    } catch { setError("Failed to add safety rule."); }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this rule?")) return;
    try {
      await axios.delete(`http://localhost:8000/admin/safety-rules/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("Rule deleted."); fetchData();
    } catch { setError("Failed to delete rule."); }
  };

  const getLocationName = (id) => locations.find(l => l.id === id)?.name || "—";

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">

        <div className="topbar">
          <div className="topbar-title">Configure Safety Rules</div>
          <button className="btn btn-primary" onClick={() => { setShowForm(!showForm); setError(""); setSuccess(""); }}>
            {showForm ? "✕ Cancel" : "+ Add Rule"}
          </button>
        </div>

        {error   && <div className="alert alert-error">{error}</div>}
        {success && <div className="alert alert-success">{success}</div>}

        {showForm && (
          <div className="content-section" style={{marginBottom:28}}>
            <h2 className="section-title">Add New Safety Rule</h2>
            <form onSubmit={handleAdd}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label">Location</label>
                  <select className="form-input" value={form.location_id} onChange={e => setForm({...form,location_id:e.target.value})} required>
                    <option value="">-- Select Location --</option>
                    {locations.map(loc => <option key={loc.id} value={loc.id}>{loc.name}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">PPE Type</label>
                  <select className="form-input" value={form.ppe_type} onChange={e => setForm({...form,ppe_type:e.target.value})}>
                    {["Helmet","Safety Vest","Goggles","Gloves","Safety Boots","Ear Protection","Mask"].map(p => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Severity Level</label>
                  <select className="form-input" value={form.severity_level} onChange={e => setForm({...form,severity_level:e.target.value})}>
                    {["Low","Medium","High","Critical"].map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>
              <div className="form-group" style={{marginTop:16}}>
                <label style={{display:"flex", alignItems:"center", gap:10, cursor:"pointer"}}>
                  <input type="checkbox" checked={form.is_restricted_area} onChange={e => setForm({...form,is_restricted_area:e.target.checked})}
                    style={{width:16, height:16, accentColor:"var(--accent)"}} />
                  <span className="form-label" style={{margin:0}}>Mark as Restricted Area</span>
                </label>
              </div>
              <div style={{marginTop:20}}>
                <button type="submit" className="btn btn-primary">Add Safety Rule</button>
              </div>
            </form>
          </div>
        )}

        <div className="content-section">
          <h2 className="section-title">All Safety Rules</h2>
          {loading ? <p className="loading-text">Loading rules…</p> :
           rules.length === 0 ? <p className="loading-text">No rules configured. Add one above.</p> : (
            <table>
              <thead><tr><th>#</th><th>Location</th><th>PPE Type</th><th>Severity</th><th>Restricted</th><th>Action</th></tr></thead>
              <tbody>
                {rules.map((rule, idx) => (
                  <tr key={rule.id}>
                    <td style={{color:"var(--text3)",fontSize:13}}>{idx+1}</td>
                    <td style={{fontWeight:600}}>{getLocationName(rule.location_id)}</td>
                    <td><span className="badge badge-blue">{rule.ppe_type}</span></td>
                    <td><span className={`badge badge-${severityClass(rule.severity_level)}`}>{rule.severity_level}</span></td>
                    <td><span className={`badge badge-${rule.is_restricted_area?"red":"gray"}`}>{rule.is_restricted_area?"Yes":"No"}</span></td>
                    <td><button className="btn btn-danger btn-sm" onClick={() => handleDelete(rule.id)}>Delete</button></td>
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