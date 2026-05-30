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

const roleClass = (r) => ({ admin:"red", officer:"blue", worker:"green" }[r] || "gray");

export default function ManageUsers() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [form, setForm] = useState({ name:"", email:"", password:"", role:"worker" });

  useEffect(() => { if (!token) navigate("/"); fetchUsers(); }, []);

  const fetchUsers = async () => {
    try {
      const res = await axios.get("http://localhost:8000/admin/users", { headers: { Authorization: `Bearer ${token}` } });
      setUsers(res.data);
    } catch { setError("Failed to fetch users."); }
    finally { setLoading(false); }
  };

  const handleAddUser = async (e) => {
    e.preventDefault(); setError(""); setSuccess("");
    try {
      await axios.post("http://localhost:8000/admin/users", form, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("User added successfully!");
      setShowForm(false);
      setForm({ name:"", email:"", password:"", role:"worker" });
      fetchUsers();
    } catch { setError("Failed to add user."); }
  };

  const handleStatusUpdate = async (id, status) => {
    try {
      await axios.patch(`http://localhost:8000/admin/users/${id}`, { status }, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("User status updated."); fetchUsers();
    } catch { setError("Failed to update status."); }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this user?")) return;
    try {
      await axios.delete(`http://localhost:8000/admin/users/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("User deleted."); fetchUsers();
    } catch { setError("Failed to delete user."); }
  };

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">

        <div className="topbar">
          <div className="topbar-title">Manage Users</div>
          <button className="btn btn-primary" onClick={() => { setShowForm(!showForm); setError(""); setSuccess(""); }}>
            {showForm ? "✕ Cancel" : "+ Add New User"}
          </button>
        </div>

        {error   && <div className="alert alert-error">{error}</div>}
        {success && <div className="alert alert-success">{success}</div>}

        {showForm && (
          <div className="content-section" style={{marginBottom:28}}>
            <h2 className="section-title">Add New User</h2>
            <form onSubmit={handleAddUser}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label">Full Name</label>
                  <input className="form-input" placeholder="Enter full name" value={form.name} onChange={e => setForm({...form,name:e.target.value})} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Email</label>
                  <input type="email" className="form-input" placeholder="Enter email" value={form.email} onChange={e => setForm({...form,email:e.target.value})} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Password</label>
                  <input type="password" className="form-input" placeholder="Enter password" value={form.password} onChange={e => setForm({...form,password:e.target.value})} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Role</label>
                  <select className="form-input" value={form.role} onChange={e => setForm({...form,role:e.target.value})}>
                    <option value="admin">Admin</option>
                    <option value="officer">Safety Officer</option>
                    <option value="worker">Worker</option>
                  </select>
                </div>
              </div>
              <div style={{marginTop:20}}>
                <button type="submit" className="btn btn-primary">Add User</button>
              </div>
            </form>
          </div>
        )}

        <div className="content-section">
          <h2 className="section-title">All Users</h2>
          {loading ? <p className="loading-text">Loading users…</p> :
           users.length === 0 ? <p className="loading-text">No users found.</p> : (
            <table>
              <thead><tr><th>#</th><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {users.map((u, i) => (
                  <tr key={u.id}>
                    <td style={{color:"var(--text3)",fontSize:13}}>{i+1}</td>
                    <td style={{fontWeight:600}}>{u.name}</td>
                    <td style={{color:"var(--text2)"}}>{u.email}</td>
                    <td><span className={`badge badge-${roleClass(u.role)}`}>{u.role}</span></td>
                    <td><span className={`badge badge-${u.status==="active"?"green":"gray"}`}>
                      {u.status==="active"?"● Active":"○ Inactive"}
                    </span></td>
                    <td>
                      <div style={{display:"flex",gap:8}}>
                        {u.status==="active"
                          ? <button className="btn btn-ghost btn-sm" onClick={() => handleStatusUpdate(u.id,"inactive")}>Deactivate</button>
                          : <button className="btn btn-ghost btn-sm" onClick={() => handleStatusUpdate(u.id,"active")}>Activate</button>}
                        <button className="btn btn-danger btn-sm" onClick={() => handleDelete(u.id)}>Delete</button>
                      </div>
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