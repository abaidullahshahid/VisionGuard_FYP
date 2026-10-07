import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API_BASE } from "./api";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import menuItems from "./adminMenuItems";
import SelectMenu from "./SelectMenu";

const roleClass = (r) => ({ admin:"red", officer:"blue", worker:"green" }[r] || "gray");
const ROLE_OPTIONS = [
  { value:"admin",   label:"Admin",          description:"Manages the whole system (no department)" },
  { value:"officer", label:"Safety Officer", description:"Reviews incidents and corrective actions" },
  { value:"worker",  label:"Worker",         description:"Works at assigned locations" },
];

export default function ManageUsers() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [form, setForm] = useState({ name:"", email:"", password:"", role:"worker", department:"" });
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");

  useEffect(() => { if (!token) navigate("/login"); fetchUsers(); }, []);

  const fetchUsers = async () => {
    try {
      const res = await axios.get(`${API_BASE}/admin/users`, { headers: { Authorization: `Bearer ${token}` } });
      setUsers(res.data);
    } catch { setError("Failed to fetch users."); }
    finally { setLoading(false); }
  };

  const handleAddUser = async (e) => {
    e.preventDefault(); setError(""); setSuccess("");
    try {
      // Admins oversee every department, so none is stored for them.
      const body = { ...form, department: form.role === "admin" ? null : form.department.trim() || null };
      await axios.post(`${API_BASE}/admin/users`, body, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("User added successfully!");
      setShowForm(false);
      setForm({ name:"", email:"", password:"", role:"worker", department:"" });
      fetchUsers();
    } catch (err) {
      if (err.response && err.response.data && err.response.data.detail) {
        setError(err.response.data.detail);
      } else {
        setError("Failed to add user.");
      }
    }
  };

  const handleStatusUpdate = async (id, status) => {
    try {
      await axios.patch(`${API_BASE}/admin/users/${id}`, { status }, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess("User status updated."); fetchUsers();
    } catch { setError("Failed to update status."); }
  };

  const handleResetPassword = async (user) => {
    const password = window.prompt(`Temporary password for ${user.name} (at least 6 characters). Give it to them and ask them to change it in their profile.`);
    if (password === null) return;
    setError(""); setSuccess("");
    try {
      await axios.patch(`${API_BASE}/admin/users/${user.id}`, { password }, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess(`Temporary password set for ${user.name}.`);
    } catch (err) { setError(err.response?.data?.detail || "Failed to reset password."); }
  };

  const handleDelete = async (user) => {
    const message = `Delete ${user.name} (${user.email})?\n\n`
      + "Their past corrective actions stay in the history. Any unfinished tasks become unassigned so an officer can reassign them.\n\n"
      + "To only block their login, use Deactivate instead.";
    if (!window.confirm(message)) return;
    setError(""); setSuccess("");
    try {
      const res = await axios.delete(`${API_BASE}/admin/users/${user.id}`, { headers: { Authorization: `Bearer ${token}` } });
      setSuccess(res.data?.detail || "User deleted."); fetchUsers();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to delete user. Check that the backend is running.");
    }
  };

  const roleName = { admin:"Admin", officer:"Safety Officer", worker:"Worker" };
  const query = search.trim().toLowerCase();
  const shownUsers = users.filter((u) => {
    if (roleFilter && u.role !== roleFilter) return false;
    if (!query) return true;
    const department = u.role === "admin" ? "All departments" : (u.department || "");
    return [u.name, u.email, department, u.role, roleName[u.role], u.status]
      .some((value) => String(value || "").toLowerCase().includes(query));
  });

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Manage Users</div>
            <div className="dashboard-subtitle">Create accounts, update access, and manage user status.</div>
          </div>
          <button className="btn btn-primary" onClick={() => { setShowForm(!showForm); setError(""); setSuccess(""); }}>
            {showForm ? <><Icon name="x" size={16} /> Cancel</> : <><Icon name="plus" size={16} /> Add New User</>}
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
                  <label className="form-label" htmlFor="user-role">Role</label>
                  <SelectMenu id="user-role" value={form.role} options={ROLE_OPTIONS} onChange={role => setForm({...form,role})} />
                </div>
                {form.role !== "admin" && (
                  <div className="form-group">
                    <label className="form-label" htmlFor="user-department">
                      Department{form.role === "officer" ? " (optional)" : ""}
                    </label>
                    <input
                      id="user-department"
                      className="form-input"
                      placeholder="e.g. Manufacturing"
                      value={form.department}
                      onChange={e => setForm({...form,department:e.target.value})}
                      required={form.role === "worker"}
                    />
                  </div>
                )}
              </div>
              <div style={{marginTop:20}}>
                <button type="submit" className="btn btn-primary"><Icon name="plus" size={16} /> Add User</button>
              </div>
            </form>
          </div>
        )}

        <div className="content-section">
          <h2 className="section-title">All Users</h2>
          <div className="user-search-row">
            <div className="search-panel">
              <span className="search-panel-icon"><Icon name="search" size={18} /></span>
              <input
                className="form-input"
                aria-label="Search users"
                placeholder="Search by name, email, department, role or status"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
            <SelectMenu
              ariaLabel="Filter by role"
              value={roleFilter}
              options={[{ value:"", label:"All roles" }, ...ROLE_OPTIONS.map(({ value, label }) => ({ value, label }))]}
              onChange={setRoleFilter}
            />
          </div>
          {!loading && users.length > 0 && (search || roleFilter) && (
            <p className="table-secondary" style={{margin:"0 0 12px"}}>{shownUsers.length} of {users.length} users match</p>
          )}
          {loading ? <p className="loading-text">Loading users...</p> :
           users.length === 0 ? <p className="loading-text">No users found.</p> :
           shownUsers.length === 0 ? <p className="loading-text">No users match your search.</p> : (
            <table>
              <thead><tr><th>#</th><th>Name</th><th>Email</th><th>Department</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {shownUsers.map((u, i) => (
                  <tr key={u.id}>
                    <td style={{color:"var(--text3)",fontSize:13}}>{i+1}</td>
                    <td style={{fontWeight:600}}>{u.name}</td>
                    <td style={{color:"var(--text2)"}}>{u.email}</td>
                    <td style={{color:"var(--text2)"}}>{u.role === "admin" ? "All departments" : (u.department || "Unassigned")}</td>
                    <td><span className={`badge badge-${roleClass(u.role)}`}>{u.role}</span></td>
                    <td><span className={`badge badge-${u.status==="active"?"green":"gray"}`}>
                      <span className={`status-dot ${u.status==="active" ? "" : "muted"}`} /> {u.status==="active"?"Active":"Inactive"}
                    </span></td>
                    <td>
                      <div style={{display:"flex",gap:8}}>
                        {u.status==="active"
                          ? <button className="btn btn-ghost btn-sm" onClick={() => handleStatusUpdate(u.id,"inactive")}>Deactivate</button>
                          : <button className="btn btn-ghost btn-sm" onClick={() => handleStatusUpdate(u.id,"active")}>Activate</button>}
                        <button className="btn btn-ghost btn-sm" onClick={() => handleResetPassword(u)}>Reset Password</button>
                        <button className="btn btn-danger btn-sm" onClick={() => handleDelete(u)}><Icon name="trash" size={14} /> Delete</button>
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
