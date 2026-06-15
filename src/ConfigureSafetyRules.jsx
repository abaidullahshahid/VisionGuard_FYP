import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import menuItems from "./adminMenuItems";

const severityClass = (l) => ({ Critical:"red", High:"red", Medium:"yellow", Low:"green" }[l] || "gray");

export default function ConfigureSafetyRules() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [rules, setRules]         = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [showForm, setShowForm]   = useState(false);
  const [error, setError]         = useState("");
  const [success, setSuccess]     = useState("");
  const [form, setForm] = useState({ location_id:"", ppe_type:"Helmet", is_restricted_area:false, severity_level:"High" });

  useEffect(() => { if (!token) navigate("/login"); fetchData(); }, []);

  const fetchData = async () => {
    try {
      const [rulesRes, locRes] = await Promise.all([
        axios.get("http://127.0.0.1:8001/admin/safety-rules", { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("http://127.0.0.1:8001/admin/locations",    { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      setRules(rulesRes.data); setLocations(locRes.data);
    } catch { setError("Failed to load data."); }
    finally { setLoading(false); }
  };

  const handleAdd = async (e) => {
    e.preventDefault(); setError(""); setSuccess("");
    try {
      await axios.post("http://127.0.0.1:8001/admin/safety-rules", {
        ...form,
        ppe_type: form.is_restricted_area ? null : form.ppe_type,
      }, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess(form.is_restricted_area ? "Restricted zone added!" : "Safety rule added!");
      setShowForm(false);
      setForm({ location_id:"", ppe_type:"Helmet", is_restricted_area:false, severity_level:"High" });
      fetchData();
    } catch (err) { setError(err.response?.data?.detail || "Failed to add safety rule."); }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this rule?")) return;
    try {
      await axios.delete(`http://127.0.0.1:8001/admin/safety-rules/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("Rule deleted."); fetchData();
    } catch { setError("Failed to delete rule."); }
  };

  const getLocationName = (id) => locations.find(l => l.id === id)?.name || "Unassigned";

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Configure Safety Rules</div>
            <div className="dashboard-subtitle">Define PPE and restricted-area policies by location.</div>
          </div>
          <button className="btn btn-primary" onClick={() => { setShowForm(!showForm); setError(""); setSuccess(""); }}>
            {showForm ? <><Icon name="x" size={16} /> Cancel</> : <><Icon name="plus" size={16} /> Add Rule</>}
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
                {!form.is_restricted_area && (
                  <div className="form-group">
                    <label className="form-label">PPE Type</label>
                    <select className="form-input" value={form.ppe_type} onChange={e => setForm({...form,ppe_type:e.target.value})}>
                      {["Helmet","Safety Vest","Goggles","Gloves","Safety Boots","Ear Protection","Mask"].map(p => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                  </div>
                )}
                <div className="form-group">
                  <label className="form-label">Severity Level</label>
                  <select className="form-input" value={form.severity_level} onChange={e => setForm({...form,severity_level:e.target.value})}>
                    {["Low","Medium","High","Critical"].map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>
              <div className="form-group" style={{marginTop:16}}>
                <label style={{display:"flex", alignItems:"center", gap:10, cursor:"pointer"}}>
                  <input type="checkbox" checked={form.is_restricted_area} onChange={e => setForm({...form,is_restricted_area:e.target.checked, ppe_type:e.target.checked ? "" : "Helmet", severity_level:e.target.checked ? "Critical" : form.severity_level})}
                    style={{width:16, height:16, accentColor:"var(--accent)"}} />
                  <span className="form-label" style={{margin:0}}>Mark as Restricted Area - no worker should enter</span>
                </label>
              </div>
              {form.is_restricted_area && (
                <div className="instruction-callout danger" style={{marginTop:14}}>
                  <h4><Icon name="alert" size={15} /> Restricted zone</h4>
                  <ul><li>No PPE or equipment is selected because workers must not enter this location.</li></ul>
                </div>
              )}
              <div style={{marginTop:20}}>
                <button type="submit" className="btn btn-primary"><Icon name="plus" size={16} /> Add Safety Rule</button>
              </div>
            </form>
          </div>
        )}

        <div className="content-section">
          <h2 className="section-title">All Safety Rules</h2>
          {loading ? <p className="loading-text">Loading rules...</p> :
           rules.length === 0 ? <p className="loading-text">No rules configured. Add one above.</p> : (
            <table>
              <thead><tr><th>#</th><th>Location</th><th>PPE Type</th><th>Severity</th><th>Restricted</th><th>Action</th></tr></thead>
              <tbody>
                {rules.map((rule, idx) => (
                  <tr key={rule.id}>
                    <td style={{color:"var(--text3)",fontSize:13}}>{idx+1}</td>
                    <td style={{fontWeight:600}}><span className="table-icon"><Icon name="rules" size={16} /></span>{getLocationName(rule.location_id)}</td>
                    <td><span className={`badge badge-${rule.is_restricted_area?"red":"blue"}`}>{rule.is_restricted_area ? "No entry" : rule.ppe_type}</span></td>
                    <td><span className={`badge badge-${severityClass(rule.severity_level)}`}>{rule.severity_level}</span></td>
                    <td><span className={`badge badge-${rule.is_restricted_area?"red":"gray"}`}>{rule.is_restricted_area?"Yes":"No"}</span></td>
                    <td><button className="btn btn-danger btn-sm" onClick={() => handleDelete(rule.id)}><Icon name="trash" size={14} /> Delete</button></td>
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
