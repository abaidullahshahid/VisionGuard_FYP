import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API_BASE } from "./api";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import menuItems from "./adminMenuItems";
import SelectMenu from "./SelectMenu";

export default function ManageLocations() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [locations, setLocations] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [form, setForm] = useState({ name:"", zone:"", department:"" });
  const [assignForm, setAssignForm] = useState({ worker_id:"", location_id:"" });
  const [showWorkerForm, setShowWorkerForm] = useState(false);
  const [workerForm, setWorkerForm] = useState({ name:"", email:"", password:"", department:"" });
  const [workerSearch, setWorkerSearch] = useState("");
  const [assignmentSearch, setAssignmentSearch] = useState("");
  const [locationSearch, setLocationSearch] = useState("");

  useEffect(() => { if (!token) navigate("/login"); fetchData(); }, []);

  const authHeaders = { headers: { Authorization: `Bearer ${token}` } };

  const fetchData = async () => {
    try {
      const [locRes, userRes, assignmentRes] = await Promise.all([
        axios.get(`${API_BASE}/admin/locations`, authHeaders),
        axios.get(`${API_BASE}/admin/users`, authHeaders),
        axios.get(`${API_BASE}/admin/worker-locations`, authHeaders),
      ]);
      const activeWorkers = (userRes.data || []).filter(u => u.role === "worker" && u.status === "active");
      setLocations(locRes.data || []);
      setWorkers(activeWorkers);
      setAssignments(assignmentRes.data || []);
    } catch { setError("Failed to load location data."); }
    finally { setLoading(false); }
  };

  const handleAdd = async (e) => {
    e.preventDefault(); setError(""); setSuccess("");
    try {
      await axios.post(`${API_BASE}/admin/locations`, {
        name: form.name.trim(),
        zone: form.zone.trim(),
        department: form.department.trim(),
      }, authHeaders);
      setSuccess("Location added!"); setShowForm(false);
      setForm({ name:"", zone:"", department:"" }); fetchData();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to add location.");
    }
  };

  const handleAssign = async (e) => {
    e.preventDefault(); setError(""); setSuccess("");
    if (!assignForm.worker_id || !assignForm.location_id) {
      setError("Select a worker and location first.");
      return;
    }
    try {
      await axios.post(`${API_BASE}/admin/worker-locations`, {
        worker_id: Number(assignForm.worker_id),
        location_id: Number(assignForm.location_id),
      }, authHeaders);
      setSuccess("Worker assigned to location.");
      setAssignForm({ worker_id:"", location_id:"" });
      setWorkerSearch("");
      fetchData();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to assign worker.");
    }
  };

  const handleAddWorker = async (e) => {
    e.preventDefault(); setError(""); setSuccess("");
    try {
      const res = await axios.post(`${API_BASE}/admin/users`, {
        name: workerForm.name.trim(),
        email: workerForm.email.trim().toLowerCase(),
        password: workerForm.password,
        department: workerForm.department.trim(),
        role: "worker",
      }, authHeaders);
      setWorkers(prev => [res.data, ...prev]);
      setAssignForm(prev => ({ ...prev, worker_id: res.data.id }));
      setWorkerSearch(res.data.name);
      setWorkerForm({ name:"", email:"", password:"", department:"" });
      setShowWorkerForm(false);
      setSuccess("Worker added. Select a location and assign them.");
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to add worker.");
    }
  };

  const handleRemoveAssignment = async (id) => {
    if (!window.confirm("Remove this worker from the location?")) return;
    try {
      await axios.delete(`${API_BASE}/admin/worker-locations/${id}`, authHeaders);
      setSuccess("Worker assignment removed.");
      fetchData();
    } catch { setError("Failed to remove assignment."); }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this location?")) return;
    try {
      await axios.delete(`${API_BASE}/admin/locations/${id}`, authHeaders);
      setSuccess("Location deleted."); fetchData();
    } catch (err) { setError(err.response?.data?.detail || "Cannot delete this location."); }
  };

  const filteredWorkers = workers.filter(worker =>
    `${worker.name} ${worker.email} ${worker.department || ""}`.toLowerCase().includes(workerSearch.toLowerCase())
  );
  const showWorkerResults = workerSearch.trim().length > 0;
  const selectedWorker = workers.find(worker => String(worker.id) === String(assignForm.worker_id));
  const filteredAssignments = assignments.filter(assignment =>
    `${assignment.worker_name} ${assignment.worker_email} ${assignment.worker_department || ""} ${assignment.location_name}`.toLowerCase().includes(assignmentSearch.toLowerCase())
  );
  const filteredLocations = locations.filter(loc =>
    `${loc.name} ${loc.zone} ${loc.department}`.toLowerCase().includes(locationSearch.toLowerCase())
  );

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Manage Locations</div>
            <div className="dashboard-subtitle">Organize monitored zones and assign workers to workplaces.</div>
          </div>
          <button className="btn btn-primary" onClick={() => { setShowForm(!showForm); setError(""); setSuccess(""); }}>
            {showForm ? <><Icon name="x" size={16} /> Cancel</> : <><Icon name="plus" size={16} /> Add Location</>}
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
                <button type="submit" className="btn btn-primary"><Icon name="plus" size={16} /> Add Location</button>
              </div>
            </form>
          </div>
        )}

        <div className="content-section" style={{marginBottom:28}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:12,marginBottom:18,flexWrap:"wrap"}}>
            <h2 className="section-title" style={{margin:0}}>Assign Workers To Locations</h2>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowWorkerForm(!showWorkerForm)}>
              {showWorkerForm ? <><Icon name="x" size={14} /> Cancel Worker</> : <><Icon name="plus" size={14} /> Add Worker</>}
            </button>
          </div>

          {showWorkerForm && (
            <form onSubmit={handleAddWorker} style={{marginBottom:22}}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label">Worker Name</label>
                  <input className="form-input" placeholder="Enter worker name" value={workerForm.name} onChange={e => setWorkerForm({...workerForm,name:e.target.value})} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Worker Email</label>
                  <input type="email" className="form-input" placeholder="worker@visionguard.com" value={workerForm.email} onChange={e => setWorkerForm({...workerForm,email:e.target.value})} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Password</label>
                  <input type="password" className="form-input" placeholder="Create password" value={workerForm.password} onChange={e => setWorkerForm({...workerForm,password:e.target.value})} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Department</label>
                  <input className="form-input" placeholder="e.g. Manufacturing" value={workerForm.department} onChange={e => setWorkerForm({...workerForm,department:e.target.value})} required />
                </div>
                <div className="form-group" style={{justifyContent:"flex-end"}}>
                  <button type="submit" className="btn btn-primary" style={{marginTop:"auto"}}>
                    <Icon name="plus" size={16} /> Save Worker
                  </button>
                </div>
              </div>
            </form>
          )}

          <form onSubmit={handleAssign}>
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">Search Worker</label>
                <input className="form-input" placeholder="Search by worker name, email, or department" value={workerSearch} onChange={e => setWorkerSearch(e.target.value)} />
                {showWorkerResults && (
                  <div className="worker-picker-list">
                    {filteredWorkers.length === 0 ? (
                      <div className="worker-picker-empty">No workers match your search.</div>
                    ) : filteredWorkers.map(worker => (
                      <button
                        key={worker.id}
                        type="button"
                        className={`worker-picker-item${String(assignForm.worker_id) === String(worker.id) ? " selected" : ""}`}
                        onClick={() => {
                          setAssignForm({...assignForm, worker_id: worker.id});
                          setWorkerSearch(worker.name);
                        }}
                      >
                        <span className="table-icon"><Icon name="worker" size={16} /></span>
                        <span>
                          <strong>{worker.name}</strong>
                          <small>{worker.email}</small>
                          <small>Department: {worker.department || "No department set"}</small>
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="form-group">
                <label className="form-label">Worker Department</label>
                <div className="form-input readonly-input">
                  {selectedWorker?.department || "No department set"}
                </div>
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="assign-location">Workplace Location</label>
                <SelectMenu
                  id="assign-location"
                  value={assignForm.location_id}
                  placeholder="Select location"
                  options={locations.map(loc => ({ value: String(loc.id), label: `${loc.name} - ${loc.zone}` }))}
                  onChange={location_id => setAssignForm({...assignForm, location_id})}
                />
              </div>
              <div className="form-group" style={{justifyContent:"flex-end"}}>
                <button type="submit" className="btn btn-primary" style={{marginTop:"auto"}}>
                  <Icon name="plus" size={16} /> Assign Worker
                </button>
              </div>
            </div>
          </form>
        </div>

        <div className="content-section" style={{marginBottom:28}}>
          <h2 className="section-title">Worker Assignments</h2>
          <div className="search-panel" style={{margin:"0 0 18px"}}>
            <span className="search-panel-icon"><Icon name="search" size={18} /></span>
            <input className="form-input" placeholder="Search assignments by worker, email, or location" value={assignmentSearch} onChange={e => setAssignmentSearch(e.target.value)} />
          </div>
          {loading ? <p className="loading-text">Loading assignments...</p> :
           assignments.length === 0 ? <p className="loading-text">No workers assigned yet.</p> :
           filteredAssignments.length === 0 ? <p className="loading-text">No assignments match your search.</p> : (
            <table>
              <thead><tr><th>#</th><th>Worker</th><th>Email</th><th>Department</th><th>Location</th><th>Assigned</th><th>Action</th></tr></thead>
              <tbody>
                {filteredAssignments.map((assignment, idx) => (
                  <tr key={assignment.id}>
                    <td style={{color:"var(--text3)",fontSize:13}}>{idx+1}</td>
                    <td style={{fontWeight:600}}><span className="table-icon"><Icon name="worker" size={16} /></span>{assignment.worker_name}</td>
                    <td style={{color:"var(--text2)"}}>{assignment.worker_email}</td>
                    <td style={{color:"var(--text2)"}}>{assignment.worker_department || "Unassigned"}</td>
                    <td><span className="badge badge-blue">{assignment.location_name}</span></td>
                    <td style={{color:"var(--text3)",fontSize:13}}>{assignment.assigned_at ? new Date(assignment.assigned_at).toLocaleDateString() : "N/A"}</td>
                    <td><button className="btn btn-danger btn-sm" onClick={() => handleRemoveAssignment(assignment.id)}><Icon name="trash" size={14} /> Remove</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="content-section">
          <h2 className="section-title">All Locations</h2>
          <div className="search-panel" style={{margin:"0 0 18px"}}>
            <span className="search-panel-icon"><Icon name="search" size={18} /></span>
            <input className="form-input" placeholder="Search locations by name, zone, or department" value={locationSearch} onChange={e => setLocationSearch(e.target.value)} />
          </div>
          {loading ? <p className="loading-text">Loading locations...</p> :
           locations.length === 0 ? <p className="loading-text">No locations found. Add one above.</p> :
           filteredLocations.length === 0 ? <p className="loading-text">No locations match your search.</p> : (
            <table>
              <thead><tr><th>#</th><th>Location Name</th><th>Zone</th><th>Department</th><th>Assigned Workers</th><th>Action</th></tr></thead>
              <tbody>
                {filteredLocations.map((loc, idx) => {
                  const assignedCount = assignments.filter(a => a.location_id === loc.id).length;
                  return (
                    <tr key={loc.id}>
                      <td style={{color:"var(--text3)",fontSize:13}}>{idx+1}</td>
                      <td style={{fontWeight:600}}><span className="table-icon"><Icon name="location" size={16} /></span>{loc.name}</td>
                      <td><span className="badge badge-blue">{loc.zone}</span></td>
                      <td style={{color:"var(--text2)"}}>{loc.department}</td>
                      <td><span className="badge badge-green">{assignedCount}</span></td>
                      <td><button className="btn btn-danger btn-sm" onClick={() => handleDelete(loc.id)}><Icon name="trash" size={14} /> Delete</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </main>
    </div>
  );
}
