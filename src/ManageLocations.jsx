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

export default function ManageLocations() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [form, setForm] = useState({ name:"", zone:"", department:"" });

  useEffect(() => { if (!token) navigate("/"); fetchLocations(); }, []);

  const fetchLocations = async () => {
    try {
      const res = await axios.get("http://localhost:8000/admin/locations", { headers: { Authorization: `Bearer ${token}` } });
      setLocations(res.data);
    } catch { setError("Failed to load locations."); }
    finally { setLoading(false); }
  };

  const handleAdd = async (e) => {
    e.preventDefault(); setError(""); setSuccess("");
    try {
      await axios.post("http://localhost:8000/admin/locations", form, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("Location added!"); setShowForm(false);
      setForm({ name:"", zone:"", department:"" }); fetchLocations();
    } catch { setError("Failed to add location."); }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this location?")) return;
    try {
      await axios.delete(`http://localhost:8000/admin/locations/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("Location deleted."); fetchLocations();
    } catch { setError("Cannot delete — location may have active cameras or incidents."); }
  };

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">

        <div className="topbar">
          <div className="topbar-title">Manage Locations</div>
          <button className="btn btn-primary" onClick={() => { setShowForm(!showForm); setError(""); setSuccess(""); }}>
            {showForm ? "✕ Cancel" : "+ Add Location"}
          </button>
        </div>

        {error   && <div className="alert alert-error">{error}</div>}
        {success && <div className="alert alert-success">{success}</div>}

        {showForm && (
          <div className="content-section" style={{marginBottom:28}}>
            <h2 className="section-title">Add New Location</h2>
            <form onSubmit={handleAdd}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label">Location Name</label>
                  <input className="form-input" placeholder="e.g. Warehouse Block A" value={form.name} onChange={e => setForm({...form,name:e.target.value})} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Zone</label>
                  <input className="form-input" placeholder="e.g. Zone 1" value={form.zone} onChange={e => setForm({...form,zone:e.target.value})} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Department</label>
                  <input className="form-input" placeholder="e.g. Manufacturing" value={form.department} onChange={e => setForm({...form,department:e.target.value})} required />
                </div>
              </div>
              <div style={{marginTop:20}}>
                <button type="submit" className="btn btn-primary">Add Location</button>
              </div>
            </form>
          </div>
        )}

        <div className="content-section">
          <h2 className="section-title">All Locations</h2>
          {loading ? <p className="loading-text">Loading locations…</p> :
           locations.length === 0 ? <p className="loading-text">No locations found. Add one above.</p> : (
            <table>
              <thead><tr><th>#</th><th>Location Name</th><th>Zone</th><th>Department</th><th>Action</th></tr></thead>
              <tbody>
                {locations.map((loc, idx) => (
                  <tr key={loc.id}>
                    <td style={{color:"var(--text3)",fontSize:13}}>{idx+1}</td>
                    <td style={{fontWeight:600}}>{loc.name}</td>
                    <td><span className="badge badge-blue">{loc.zone}</span></td>
                    <td style={{color:"var(--text2)"}}>{loc.department}</td>
                    <td><button className="btn btn-danger btn-sm" onClick={() => handleDelete(loc.id)}>Delete</button></td>
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