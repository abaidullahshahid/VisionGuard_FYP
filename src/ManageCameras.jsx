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

export default function ManageCameras() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [cameras, setCameras]     = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading]     = useState(true);
  const [showForm, setShowForm]   = useState(false);
  const [error, setError]         = useState("");
  const [success, setSuccess]     = useState("");
  const [form, setForm] = useState({ name:"", type:"IP", stream_url:"", location_id:"" });

  useEffect(() => { if (!token) navigate("/"); fetchData(); }, []);

  const fetchData = async () => {
    try {
      const [camRes, locRes] = await Promise.all([
        axios.get("http://localhost:8000/admin/cameras",   { headers: { Authorization: `Bearer ${token}` } }),
        axios.get("http://localhost:8000/admin/locations", { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      setCameras(camRes.data); setLocations(locRes.data);
    } catch { setError("Failed to load data."); }
    finally { setLoading(false); }
  };

  const handleAdd = async (e) => {
    e.preventDefault(); setError(""); setSuccess("");
    try {
      await axios.post("http://localhost:8000/admin/cameras", form, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("Camera added!"); setShowForm(false);
      setForm({ name:"", type:"IP", stream_url:"", location_id:"" }); fetchData();
    } catch { setError("Failed to add camera."); }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this camera?")) return;
    try {
      await axios.delete(`http://localhost:8000/admin/cameras/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("Camera deleted."); fetchData();
    } catch { setError("Failed to delete camera."); }
  };

  const getLocationName = (id) => locations.find(l => l.id === id)?.name || "—";

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">

        <div className="topbar">
          <div className="topbar-title">Manage Cameras</div>
          <button className="btn btn-primary" onClick={() => { setShowForm(!showForm); setError(""); setSuccess(""); }}>
            {showForm ? "✕ Cancel" : "+ Add Camera"}
          </button>
        </div>

        {error   && <div className="alert alert-error">{error}</div>}
        {success && <div className="alert alert-success">{success}</div>}

        {showForm && (
          <div className="content-section" style={{marginBottom:28}}>
            <h2 className="section-title">Add New Camera</h2>
            <form onSubmit={handleAdd}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label">Camera Name</label>
                  <input className="form-input" placeholder="e.g. Gate Camera 1" value={form.name} onChange={e => setForm({...form,name:e.target.value})} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Camera Type</label>
                  <select className="form-input" value={form.type} onChange={e => setForm({...form,type:e.target.value})}>
                    <option value="IP">IP Camera</option>
                    <option value="USB">USB Camera</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Assign Location</label>
                  <select className="form-input" value={form.location_id} onChange={e => setForm({...form,location_id:e.target.value})} required>
                    <option value="">-- Select Location --</option>
                    {locations.map(loc => <option key={loc.id} value={loc.id}>{loc.name}</option>)}
                  </select>
                </div>
              </div>
              <div className="form-group" style={{marginTop:16}}>
                <label className="form-label">Stream URL (RTSP)</label>
                <input className="form-input" placeholder="rtsp://192.168.1.100:554/stream" value={form.stream_url} onChange={e => setForm({...form,stream_url:e.target.value})} required />
              </div>
              <div style={{marginTop:20}}>
                <button type="submit" className="btn btn-primary">Add Camera</button>
              </div>
            </form>
          </div>
        )}

        <div className="content-section">
          <h2 className="section-title">All Cameras</h2>
          {loading ? <p className="loading-text">Loading cameras…</p> :
           cameras.length === 0 ? <p className="loading-text">No cameras found. Add one above.</p> : (
            <table>
              <thead><tr><th>#</th><th>Camera Name</th><th>Type</th><th>Location</th><th>Stream URL</th><th>Status</th><th>Action</th></tr></thead>
              <tbody>
                {cameras.map((cam, idx) => (
                  <tr key={cam.id}>
                    <td style={{color:"var(--text3)",fontSize:13}}>{idx+1}</td>
                    <td style={{fontWeight:600}}>{cam.name}</td>
                    <td><span className="badge badge-blue">{cam.type}</span></td>
                    <td style={{color:"var(--text2)"}}>{getLocationName(cam.location_id)}</td>
                    <td><span style={{fontSize:12,color:"var(--text3)",fontFamily:"monospace"}}>{cam.stream_url}</span></td>
                    <td><span className={`badge badge-${cam.status==="active"?"green":"red"}`}>{cam.status}</span></td>
                    <td><button className="btn btn-danger btn-sm" onClick={() => handleDelete(cam.id)}>Delete</button></td>
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