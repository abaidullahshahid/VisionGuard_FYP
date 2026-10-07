import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { workerMenuItems as menuItems } from "./roleMenuItems";
import { api, apiErrorMessage } from "./api";
import { formatDateTime, incidentTypeLabel } from "./incidentUtils";
import { useNotificationRefresh } from "./NotificationBell";

const STATUS_BADGE = { Pending: "yellow", "In Progress": "blue", Resolved: "green" };
const PRIORITY_BADGE = { Critical: "red", High: "red", Medium: "yellow", Low: "green" };
const FILTERS = ["Open", "Resolved", "All"];

function incidentSummary(incident) {
  if (!incident) return "";
  if (incident.type === "RESTRICTED_ZONE_VIOLATION") return incident.zone_name || "Restricted zone";
  return incident.missing_items?.length ? `Missing ${incident.missing_items.join(", ")}` : "";
}

export default function WorkerTasks() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("Open");
  const [savingId, setSavingId] = useState(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    try {
      const response = await api.get("/worker/corrective-actions");
      setTasks(response.data || []);
      setError("");
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to load your tasks.", navigate));
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    if (!sessionStorage.getItem("token")) {
      navigate("/login", { replace: true });
      return;
    }
    load();
  }, [load, navigate]);

  useNotificationRefresh(["task", "task_update"], load);

  const updateStatus = async (task, status) => {
    setSavingId(task.id);
    setError("");
    setSuccess("");
    try {
      const response = await api.patch(`/worker/corrective-actions/${task.id}`, { status });
      setTasks((current) => current.map((item) => item.id === task.id ? response.data : item));
      setSuccess(status === "Resolved" ? "Task marked as done. The safety officer has been notified." : `Task updated: ${status}.`);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to update the task.", navigate));
    } finally {
      setSavingId(null);
    }
  };

  const visible = tasks.filter((task) => (
    filter === "All" ? true : filter === "Resolved" ? task.status === "Resolved" : task.status !== "Resolved"
  ));
  const openCount = tasks.filter((task) => task.status !== "Resolved").length;

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="worker" />
      <main className="main-content">
        <div className="topbar">
          <div>
            <div className="topbar-title">My Tasks</div>
            <div className="dashboard-subtitle">Corrective actions the safety officer assigned to you.</div>
          </div>
          <span className="topbar-badge"><Icon name="clipboard" size={16} /> {openCount} open</span>
        </div>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {success && <div className="alert alert-success" role="status">{success}</div>}

        <div className="segmented-toolbar">
          {FILTERS.map((name) => (
            <button key={name} type="button" className={filter === name ? "btn btn-primary" : "btn btn-ghost"} onClick={() => setFilter(name)}>
              {name}
            </button>
          ))}
        </div>

        <section className="content-section">
          {loading ? <p className="loading-text">Loading tasks...</p> : visible.length === 0 ? (
            <div className="empty-state">
              <span className="empty-state-icon"><Icon name="check" size={24} /></span>
              <strong>{filter === "Resolved" ? "No completed tasks yet" : "No open tasks"}</strong>
              <span>New corrective actions assigned to you will appear here and in your notifications.</span>
            </div>
          ) : (
            <div className="task-list">
              {visible.map((task) => (
                <article key={task.id} className={`task-card status-${task.status.toLowerCase().replace(" ", "-")}`}>
                  <div className="task-card-head">
                    <strong>{task.description || "Corrective action"}</strong>
                    <span style={{ display: "flex", gap: 6 }}>
                      <span className={`badge badge-${PRIORITY_BADGE[task.priority] || "gray"}`}>{task.priority} priority</span>
                      <span className={`badge badge-${STATUS_BADGE[task.status] || "gray"}`}>{task.status}</span>
                    </span>
                  </div>
                  {task.incident && (
                    <div className="task-meta">
                      <span><Icon name="alert" size={14} /> {incidentTypeLabel(task.incident.type)} #{task.incident.id}{incidentSummary(task.incident) ? ` · ${incidentSummary(task.incident)}` : ""}</span>
                      <span><Icon name="location" size={14} /> {task.incident.location}</span>
                      <span><Icon name="clock" size={14} /> Detected {formatDateTime(task.incident.detected_at)}</span>
                    </div>
                  )}
                  <div className="task-meta">
                    <span><Icon name="clock" size={14} /> Due {task.deadline || "not set"}</span>
                  </div>
                  {task.status !== "Resolved" ? (
                    <div className="task-actions">
                      {task.status === "Pending" && (
                        <button type="button" className="btn btn-ghost btn-sm" disabled={savingId === task.id} onClick={() => updateStatus(task, "In Progress")}>
                          Start working
                        </button>
                      )}
                      <button type="button" className="btn btn-primary btn-sm" disabled={savingId === task.id} onClick={() => updateStatus(task, "Resolved")}>
                        <Icon name="check" size={14} /> Mark as done
                      </button>
                    </div>
                  ) : (
                    <div className="task-actions">
                      <button type="button" className="btn btn-ghost btn-sm" disabled={savingId === task.id} onClick={() => updateStatus(task, "In Progress")}>
                        Reopen
                      </button>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
