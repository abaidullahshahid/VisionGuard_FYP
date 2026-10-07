import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems as menuItems } from "./roleMenuItems";
import { api, apiErrorMessage } from "./api";
import { incidentTypeLabel } from "./incidentUtils";
import { useNotificationRefresh } from "./NotificationBell";
import SelectMenu from "./SelectMenu";

const emptyForm = {
  incident_id: "",
  assigned_to: "",
  description: "",
  deadline: "",
  priority: "High",
};

const PRIORITY_OPTIONS = ["Low", "Medium", "High", "Critical"].map((priority) => ({ value: priority, label: priority }));
const STATUS_OPTIONS = ["Pending", "In Progress", "Resolved"].map((status) => ({ value: status, label: status }));

const priorityClass = (priority) => ({ Critical: "red", High: "red", Medium: "yellow", Low: "green" }[priority] || "gray");
const actionStatusClass = (status) => ({ Resolved: "green", "In Progress": "blue", Pending: "yellow" }[status] || "gray");

export default function CorrectiveActions() {
  const navigate = useNavigate();
  const routeLocation = useLocation();
  const preselectedIncident = routeLocation.state?.incidentId || "";
  const [actions, setActions] = useState([]);
  const [users, setUsers] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(Boolean(preselectedIncident));
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ ...emptyForm, incident_id: preselectedIncident });
  const [editingAction, setEditingAction] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [actionResponse, userResponse, incidentResponse] = await Promise.all([
        api.get("/officer/corrective-actions"),
        api.get("/officer/assignees"),
        api.get("/officer/incidents"),
      ]);
      setActions(actionResponse.data || []);
      setUsers(userResponse.data || []);
      setIncidents(incidentResponse.data || []);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to load corrective actions.", navigate));
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    if (!sessionStorage.getItem("token")) {
      navigate("/login", { replace: true });
      return;
    }
    fetchData();
  }, [fetchData, navigate]);

  useNotificationRefresh(["task_update", "incident"], fetchData);

  const handleAssign = async (event) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (!form.incident_id || !form.assigned_to) {
      setError("Select an incident and the person to assign.");
      return;
    }
    setSaving(true);
    try {
      await api.post("/officer/corrective-actions", {
        ...form,
        incident_id: Number(form.incident_id),
        assigned_to: Number(form.assigned_to),
      });
      setSuccess("Corrective action assigned successfully.");
      setShowForm(false);
      setForm(emptyForm);
      await fetchData();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to assign corrective action.", navigate));
    } finally {
      setSaving(false);
    }
  };

  const startEditing = (action) => {
    setEditingAction({
      id: action.id,
      assigned_to: action.assigned_to === null || action.assigned_to === undefined ? "" : String(action.assigned_to),
      former_assignee: action.assigned_to === null || action.assigned_to === undefined ? action.assignee_name : null,
      description: action.description || "",
      priority: action.priority || "High",
      deadline: action.deadline || "",
      status: action.status || "Pending",
    });
    setError("");
    setSuccess("");
  };

  const saveAction = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      await api.patch(`/officer/corrective-actions/${editingAction.id}`, {
        ...(editingAction.assigned_to ? { assigned_to: Number(editingAction.assigned_to) } : {}),
        description: editingAction.description,
        priority: editingAction.priority,
        deadline: editingAction.deadline || null,
        status: editingAction.status,
      });
      setSuccess("Corrective action updated successfully.");
      setEditingAction(null);
      await fetchData();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to update corrective action.", navigate));
    } finally {
      setSaving(false);
    }
  };

  const handleStatusUpdate = async (id, status) => {
    setError("");
    setSuccess("");
    try {
      await api.patch(`/officer/corrective-actions/${id}`, { status });
      setSuccess("Corrective-action status updated.");
      await fetchData();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to update corrective-action status.", navigate));
    }
  };

  const getUserName = (id, action) => {
    if (id === null || id === undefined) return action?.assignee_name || "Unassigned";
    return action?.assignee_name || users.find((user) => user.id === id)?.name || `User #${id}`;
  };
  const assigneeOptions = users.map((user) => ({ value: String(user.id), label: `${user.name} (${user.role})` }));
  const getIncident = (id) => incidents.find((incident) => incident.id === id);

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">
        <div className="topbar">
          <div>
            <div className="topbar-title">Corrective Actions</div>
            <div className="dashboard-subtitle">Assign, review, and complete incident response tasks.</div>
          </div>
          <button type="button" className="btn btn-primary" onClick={() => { setShowForm((visible) => !visible); setEditingAction(null); setError(""); setSuccess(""); }}>
            {showForm ? <><Icon name="x" size={16} /> Cancel</> : <><Icon name="plus" size={16} /> Assign Action</>}
          </button>
        </div>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {success && <div className="alert alert-success" role="status">{success}</div>}

        {showForm && (
          <section className="content-section" style={{ marginBottom: 28 }}>
            <h2 className="section-title">Assign Corrective Action</h2>
            <form onSubmit={handleAssign}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label" htmlFor="action-incident">Incident</label>
                  <SelectMenu
                    id="action-incident"
                    value={form.incident_id}
                    placeholder="Select Incident"
                    options={incidents.map((incident) => ({ value: String(incident.id), label: `#${incident.id} – ${incidentTypeLabel(incident.incident_type || incident.violation_type)} (${incident.location})` }))}
                    onChange={(value) => setForm({ ...form, incident_id: value })}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="action-user">Assign To</label>
                  <SelectMenu
                    id="action-user"
                    value={form.assigned_to}
                    placeholder="Select Personnel"
                    options={users.map((user) => ({ value: String(user.id), label: `${user.name} (${user.role})` }))}
                    onChange={(value) => setForm({ ...form, assigned_to: value })}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="action-priority">Priority</label>
                  <SelectMenu id="action-priority" value={form.priority} options={PRIORITY_OPTIONS} onChange={(value) => setForm({ ...form, priority: value })} />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="action-deadline">Deadline</label>
                  <input id="action-deadline" type="date" className="form-input" value={form.deadline} onChange={(event) => setForm({ ...form, deadline: event.target.value })} required />
                </div>
              </div>
              <div className="form-group" style={{ marginTop: 16 }}>
                <label className="form-label" htmlFor="action-description">Description</label>
                <textarea id="action-description" className="form-input" placeholder="Describe the corrective action required..." value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} required rows={3} />
              </div>
              <div className="form-actions"><button type="submit" className="btn btn-primary" disabled={saving}>{saving ? "Assigning..." : "Assign Action"}</button></div>
            </form>
          </section>
        )}

        {editingAction && (
          <section className="content-section action-edit-panel">
            <div className="section-heading">
              <div><h2 className="section-title">Edit Corrective Action #{editingAction.id}</h2><p>Update only fields supported by the existing API.</p></div>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditingAction(null)}>Cancel</button>
            </div>
            <form onSubmit={saveAction}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label" htmlFor="edit-assignee">Assign To</label>
                  <SelectMenu
                    id="edit-assignee"
                    value={editingAction.assigned_to}
                    placeholder={editingAction.former_assignee ? `Unassigned (was ${editingAction.former_assignee.replace(" (deleted user)", "")})` : "Unassigned"}
                    options={assigneeOptions}
                    onChange={(value) => setEditingAction({ ...editingAction, assigned_to: value })}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="edit-priority">Priority</label>
                  <SelectMenu id="edit-priority" value={editingAction.priority} options={PRIORITY_OPTIONS} onChange={(value) => setEditingAction({ ...editingAction, priority: value })} />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="edit-status">Status</label>
                  <SelectMenu id="edit-status" value={editingAction.status} options={STATUS_OPTIONS} onChange={(value) => setEditingAction({ ...editingAction, status: value })} />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="edit-deadline">Deadline</label>
                  <input id="edit-deadline" type="date" className="form-input" value={editingAction.deadline} onChange={(event) => setEditingAction({ ...editingAction, deadline: event.target.value })} />
                </div>
              </div>
              <div className="form-group" style={{ marginTop: 16 }}>
                <label className="form-label" htmlFor="edit-description">Description</label>
                <textarea id="edit-description" className="form-input" rows={3} value={editingAction.description} onChange={(event) => setEditingAction({ ...editingAction, description: event.target.value })} required />
              </div>
              <div className="form-actions"><button type="submit" className="btn btn-primary" disabled={saving}>{saving ? "Saving..." : "Save Changes"}</button></div>
            </form>
          </section>
        )}

        <section className="content-section">
          <div className="section-heading"><div><h2 className="section-title">All Corrective Actions</h2><p>{actions.length} action{actions.length === 1 ? "" : "s"} recorded</p></div></div>
          {loading ? <p className="loading-text">Loading corrective actions...</p> : actions.length === 0 ? (
            <div className="empty-state"><span className="empty-state-icon"><Icon name="clipboard" size={24} /></span><strong>No corrective actions found</strong><span>Assign an action from an incident or use the button above.</span></div>
          ) : (
            <table>
              <thead><tr><th>#</th><th>Incident</th><th>Assigned To</th><th>Description</th><th>Priority</th><th>Deadline</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {actions.map((action) => {
                  const incident = getIncident(action.incident_id);
                  return (
                    <tr key={action.id}>
                      <td className="table-index">#{action.id}</td>
                      <td><span className="table-primary"><span className="table-icon"><Icon name="clipboard" size={16} /></span>{incident ? incidentTypeLabel(incident.incident_type || incident.violation_type) : `Incident #${action.incident_id}`}</span></td>
                      <td>
                        {action.assigned_to === null || action.assigned_to === undefined ? (
                          <>
                            <span className="badge badge-yellow">Unassigned</span>
                            {action.assignee_name && <div className="compliance-meta">was {action.assignee_name.replace(" (deleted user)", "")}</div>}
                          </>
                        ) : getUserName(action.assigned_to, action)}
                      </td>
                      <td className="action-description-cell">{action.description || "—"}</td>
                      <td><span className={`badge badge-${priorityClass(action.priority)}`}>{action.priority}</span></td>
                      <td className="table-secondary">{action.deadline || "Not set"}</td>
                      <td>
                        <SelectMenu
                          ariaLabel={`Status for action ${action.id}`}
                          className="compact-select"
                          value={action.status}
                          options={STATUS_OPTIONS}
                          onChange={(value) => value !== action.status && handleStatusUpdate(action.id, value)}
                        />
                        <span className={`badge badge-${actionStatusClass(action.status)} action-status-badge`}>{action.status}</span>
                      </td>
                      <td><button type="button" className="btn btn-ghost btn-sm" onClick={() => startEditing(action)}>Edit</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      </main>
    </div>
  );
}
