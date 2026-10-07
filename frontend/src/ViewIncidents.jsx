import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems } from "./roleMenuItems";
import { api, apiErrorMessage, apiUrl } from "./api";
import { useNotificationRefresh } from "./NotificationBell";
import SelectMenu from "./SelectMenu";
import {
  cameraLabel,
  formatDateTime,
  incidentTypeLabel,
  severityBadge,
  severityLabel,
  statusBadge,
  statusLabel,
} from "./incidentUtils";

const emptyFilters = {
  severity: "",
  status: "",
  incidentType: "",
  camera: "",
  dateFrom: "",
  dateTo: "",
};

function toBoundary(dateValue, endOfDay = false) {
  if (!dateValue) return undefined;
  const date = new Date(`${dateValue}T${endOfDay ? "23:59:59.999" : "00:00:00"}`);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

function incidentIdentifier(incident) {
  return incident.incident_id || incident.id;
}

function EvidenceImage({ incident, thumbnail = false }) {
  const source = apiUrl(incident?.snapshot_url);
  const [state, setState] = useState(source ? "loading" : "unavailable");

  useEffect(() => {
    setState(source ? "loading" : "unavailable");
  }, [source]);

  if (!source || state === "unavailable") {
    return (
      <div className={thumbnail ? "evidence-thumbnail evidence-unavailable" : "evidence-empty"}>
        <Icon name="camera" size={thumbnail ? 17 : 28} />
        {!thumbnail && <span>Evidence unavailable</span>}
      </div>
    );
  }

  return (
    <div className={thumbnail ? "evidence-thumbnail" : "evidence-image-wrap"}>
      {state === "loading" && <span className="evidence-loading">Loading...</span>}
      <img
        src={source}
        alt={`Evidence for incident ${incident.id}`}
        onLoad={() => setState("loaded")}
        onError={() => setState("unavailable")}
      />
    </div>
  );
}

function IncidentActions({ actions }) {
  if (!actions?.length) {
    return <p className="detail-empty">No corrective actions have been assigned.</p>;
  }
  return (
    <div className="incident-action-list">
      {actions.map((action) => (
        <div key={action.id} className="incident-action-item">
          <div>
            <strong>{action.description || "Corrective action"}</strong>
            <span>
              {action.assigned_to === null || action.assigned_to === undefined
                ? `Unassigned${action.assignee_name ? ` (was ${action.assignee_name.replace(" (deleted user)", "")})` : ""}`
                : `Assigned to ${action.assignee_name || `user #${action.assigned_to}`}`}
              {action.deadline ? ` · Due ${action.deadline}` : ""}
            </span>
          </div>
          <span className={`badge badge-${action.status === "Resolved" ? "green" : action.status === "In Progress" ? "blue" : "yellow"}`}>
            {action.status}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function ViewIncidents() {
  const navigate = useNavigate();
  const [incidents, setIncidents] = useState([]);
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [filters, setFilters] = useState(emptyFilters);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [detailSuccess, setDetailSuccess] = useState("");
  const [notes, setNotes] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const fetchIncidents = useCallback(async (nextFilters, showLoading = true) => {
    if (showLoading) setLoading(true);
    setError("");
    try {
      const params = {};
      if (nextFilters.severity) params.severity = nextFilters.severity;
      if (nextFilters.status) params.status = nextFilters.status;
      if (nextFilters.incidentType) params.incident_type = nextFilters.incidentType;
      if (nextFilters.camera) params.camera = nextFilters.camera;
      if (nextFilters.dateFrom) params.date_from = toBoundary(nextFilters.dateFrom);
      if (nextFilters.dateTo) params.date_to = toBoundary(nextFilters.dateTo, true);
      const response = await api.get("/officer/incidents", { params });
      setIncidents(response.data || []);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to load incidents.", navigate));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    if (!sessionStorage.getItem("token")) {
      navigate("/login", { replace: true });
      return;
    }
    const loadPage = async () => {
      setLoading(true);
      try {
        const [incidentResponse, cameraResponse] = await Promise.all([
          api.get("/officer/incidents"),
          api.get("/officer/cameras"),
        ]);
        setIncidents(incidentResponse.data || []);
        setCameras(cameraResponse.data || []);
      } catch (requestError) {
        setError(apiErrorMessage(requestError, "Failed to load incidents.", navigate));
      } finally {
        setLoading(false);
      }
    };
    loadPage();
  }, [navigate]);

  useEffect(() => {
    if (!selectedIncident) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") setSelectedIncident(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [selectedIncident]);

  const handleFilterChange = (field, value) => {
    const nextFilters = { ...filters, [field]: value };
    setFilters(nextFilters);
    fetchIncidents(nextFilters);
  };

  const clearFilters = () => {
    setFilters(emptyFilters);
    fetchIncidents(emptyFilters);
  };

  const filtersActive = Object.values(filters).some(Boolean);

  const runDelete = async (request, fallback, deletedIds) => {
    setDeleting(true);
    setError("");
    setSuccess("");
    try {
      const response = await request();
      setSuccess(response.data?.detail || "Deleted.");
      if (selectedIncident && (deletedIds === "all" || deletedIds.includes(selectedIncident.id))) {
        setSelectedIncident(null);
      }
      await fetchIncidents(filters, false);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, fallback, navigate));
    } finally {
      setDeleting(false);
    }
  };

  const deleteIncident = (incident) => {
    const message = `Delete incident #${incident.id} (${incidentTypeLabel(incident.incident_type || incident.violation_type)})?\n\n`
      + "Its snapshot and corrective actions are deleted too. This cannot be undone.";
    if (!window.confirm(message)) return;
    runDelete(() => api.delete(`/officer/incidents/${incident.id}`), "Could not delete the incident.", [incident.id]);
  };

  const deleteListed = () => {
    const count = incidents.length;
    const what = filtersActive
      ? `Delete the ${count} incident${count === 1 ? "" : "s"} shown by the current filters?`
      : `Delete ALL ${count} incident${count === 1 ? "" : "s"}?`;
    if (!window.confirm(`${what}\n\nTheir snapshots and corrective actions are deleted too. This cannot be undone.`)) return;
    const ids = incidents.map((incident) => incident.id);
    runDelete(
      () => api.post("/officer/incidents/delete", filtersActive ? { ids } : { all: true }),
      "Could not delete the incidents.",
      filtersActive ? ids : "all",
    );
  };

  const openIncident = async (incident) => {
    setSelectedIncident(incident);
    setNotes(incident.officer_notes || "");
    setDetailLoading(true);
    setDetailError("");
    setDetailSuccess("");
    try {
      const response = await api.get(`/officer/incidents/${encodeURIComponent(incidentIdentifier(incident))}`);
      setSelectedIncident(response.data);
      setNotes(response.data.officer_notes || "");
    } catch (requestError) {
      setDetailError(apiErrorMessage(requestError, "Failed to load incident details.", navigate));
    } finally {
      setDetailLoading(false);
    }
  };

  // A new AI incident alert refreshes the register with the current filters.
  useNotificationRefresh(["incident"], () => fetchIncidents(filters, false));

  // Notification links open an incident directly: /officer/incidents?incident=12
  const routeLocation = useLocation();
  const linkedIncident = new URLSearchParams(routeLocation.search).get("incident");
  const openIncidentRef = useRef(openIncident);
  openIncidentRef.current = openIncident;
  useEffect(() => {
    if (!linkedIncident) return;
    openIncidentRef.current({ id: Number(linkedIncident) || linkedIncident });
    // Drop the parameter so the same alert can be opened again later.
    navigate(routeLocation.pathname, { replace: true });
  }, [linkedIncident, navigate, routeLocation.pathname]);

  const mergeUpdatedIncident = (updated) => {
    setIncidents((current) => current.map((item) => item.id === updated.id ? { ...item, ...updated } : item));
    setSelectedIncident((current) => ({
      ...current,
      ...updated,
      corrective_actions: current?.corrective_actions || [],
    }));
  };

  const saveNotes = async () => {
    setSavingNotes(true);
    setDetailError("");
    setDetailSuccess("");
    try {
      const response = await api.patch(
        `/officer/incidents/${encodeURIComponent(incidentIdentifier(selectedIncident))}`,
        { officer_notes: notes },
      );
      mergeUpdatedIncident(response.data);
      setDetailSuccess("Officer notes saved.");
      setSuccess("Incident notes updated successfully.");
    } catch (requestError) {
      setDetailError(apiErrorMessage(requestError, "Failed to update incident notes.", navigate));
    } finally {
      setSavingNotes(false);
    }
  };

  const updateStatus = async (status) => {
    setUpdatingStatus(true);
    setDetailError("");
    setDetailSuccess("");
    try {
      const response = await api.patch(
        `/officer/incidents/${encodeURIComponent(incidentIdentifier(selectedIncident))}`,
        { status },
      );
      mergeUpdatedIncident(response.data);
      setDetailSuccess(status === "resolved" ? "Incident resolved." : "Incident review started.");
      setSuccess("Incident status updated successfully.");
    } catch (requestError) {
      setDetailError(apiErrorMessage(requestError, "Failed to update incident status.", navigate));
    } finally {
      setUpdatingStatus(false);
    }
  };

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={officerMenuItems} role="officer" />
      <main className="main-content">
        <div className="topbar">
          <div>
            <div className="topbar-title">Safety Incidents</div>
            <div className="dashboard-subtitle">Review AI detections, evidence, and incident response progress.</div>
          </div>
          <span className="topbar-badge"><Icon name="alert" size={16} /> Incident register</span>
        </div>

        <section className="content-section filter-section">
          <div className="section-heading">
            <div>
              <h2 className="section-title">Filter Incidents</h2>
              <p>Filter the live incident register using backend-supported fields.</p>
            </div>
          </div>
          <div className="filter-grid incident-filter-grid">
            <div className="form-group">
              <label className="form-label" htmlFor="incident-status">Status</label>
              <SelectMenu
                id="incident-status"
                value={filters.status}
                options={[
                  { value: "", label: "All statuses" },
                  { value: "open", label: "Open" },
                  { value: "in_progress", label: "In Progress" },
                  { value: "resolved", label: "Resolved" },
                ]}
                onChange={(value) => handleFilterChange("status", value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="incident-severity">Severity</label>
              <SelectMenu
                id="incident-severity"
                value={filters.severity}
                options={[
                  { value: "", label: "All severities" },
                  { value: "LOW", label: "Low" },
                  { value: "MEDIUM", label: "Medium" },
                  { value: "HIGH", label: "High" },
                  { value: "CRITICAL", label: "Critical" },
                ]}
                onChange={(value) => handleFilterChange("severity", value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="incident-type">Type</label>
              <SelectMenu
                id="incident-type"
                value={filters.incidentType}
                options={[
                  { value: "", label: "All types" },
                  { value: "PPE_VIOLATION", label: "PPE Violation" },
                  { value: "RESTRICTED_ZONE_VIOLATION", label: "Restricted Zone Violation" },
                ]}
                onChange={(value) => handleFilterChange("incidentType", value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="incident-camera">Camera</label>
              <SelectMenu
                id="incident-camera"
                value={filters.camera}
                options={[{ value: "", label: "All cameras" }, ...cameras.map((camera) => ({ value: String(camera.id), label: camera.name }))]}
                onChange={(value) => handleFilterChange("camera", value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="incident-from">From</label>
              <input id="incident-from" type="date" className="form-input" value={filters.dateFrom} onChange={(event) => handleFilterChange("dateFrom", event.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="incident-to">To</label>
              <input id="incident-to" type="date" className="form-input" value={filters.dateTo} onChange={(event) => handleFilterChange("dateTo", event.target.value)} />
            </div>
            <button type="button" className="btn btn-ghost filter-clear" onClick={clearFilters}>
              <Icon name="x" size={15} /> Clear Filters
            </button>
          </div>
        </section>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {success && <div className="alert alert-success" role="status">{success}</div>}

        <section className="content-section">
          <div className="section-heading">
            <div>
              <h2 className="section-title">Incident Register</h2>
              <p>{incidents.length} incident{incidents.length === 1 ? "" : "s"} match the current filters</p>
            </div>
            {incidents.length > 0 && (
              <button type="button" className="btn btn-danger btn-sm" onClick={deleteListed} disabled={deleting || loading}>
                <Icon name="trash" size={14} /> {deleting ? "Deleting..." : filtersActive ? `Delete ${incidents.length} Shown` : "Delete All"}
              </button>
            )}
          </div>

          {loading ? (
            <p className="loading-text">Loading incidents...</p>
          ) : incidents.length === 0 ? (
            <div className="empty-state">
              <span className="empty-state-icon"><Icon name="check" size={24} /></span>
              <strong>No incidents found</strong>
              <span>Try clearing the filters to view the complete register.</span>
            </div>
          ) : (
            <table className="incident-table">
              <thead>
                <tr>
                  <th>Incident ID</th>
                  <th>Evidence</th>
                  <th>Violation</th>
                  <th>Camera / Location</th>
                  <th>Violation Detail</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Detected</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map((incident) => (
                  <tr key={incident.id}>
                    <td>
                      <span className="incident-id" title={incident.incident_id || `Database ID ${incident.id}`}>
                        {incident.incident_id ? incident.incident_id.slice(0, 8) : `#${incident.id}`}
                      </span>
                    </td>
                    <td><EvidenceImage incident={incident} thumbnail /></td>
                    <td>
                      <span className="table-primary">
                        <span className="table-icon tone-red"><Icon name="alert" size={16} /></span>
                        {incidentTypeLabel(incident.incident_type || incident.violation_type)}
                      </span>
                    </td>
                    <td>
                      <div className="table-stack">
                        <strong>{cameraLabel(incident, cameras)}</strong>
                        <span>{incident.location || "Location unavailable"}</span>
                      </div>
                    </td>
                    <td>
                      {incident.missing_items?.length
                        ? <span>{incident.missing_items.join(", ")}</span>
                        : incident.zone_name || incident.zone_id || "—"}
                    </td>
                    <td><span className={`badge badge-${severityBadge(incident)}`}>{severityLabel(incident)}</span></td>
                    <td><span className={`badge badge-${statusBadge(incident.status)}`}>{statusLabel(incident.status)}</span></td>
                    <td className="table-secondary">{formatDateTime(incident.timestamp || incident.detected_at)}</td>
                    <td>
                      <div className="incident-row-actions">
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => openIncident(incident)}>View Details</button>
                        <button
                          type="button"
                          className="btn btn-danger btn-sm btn-icon"
                          onClick={() => deleteIncident(incident)}
                          disabled={deleting}
                          aria-label={`Delete incident #${incident.id}`}
                          title="Delete incident"
                        >
                          <Icon name="trash" size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {selectedIncident && (
          <div className="modal-backdrop" onMouseDown={() => setSelectedIncident(null)}>
            <section className="modal-card incident-modal-card" role="dialog" aria-modal="true" aria-labelledby="incident-modal-title" onMouseDown={(event) => event.stopPropagation()}>
              <div className="modal-header">
                <div>
                  <span className="modal-eyebrow">Incident #{selectedIncident.id}</span>
                  <h2 id="incident-modal-title">{incidentTypeLabel(selectedIncident.incident_type || selectedIncident.violation_type)}</h2>
                </div>
                <button type="button" className="modal-close" onClick={() => setSelectedIncident(null)} aria-label="Close incident details"><Icon name="x" size={18} /></button>
              </div>

              {detailError && <div className="alert alert-error" role="alert">{detailError}</div>}
              {detailSuccess && <div className="alert alert-success" role="status">{detailSuccess}</div>}
              {detailLoading ? <p className="loading-text">Loading incident details...</p> : (
                <>
                  <div className="evidence-preview"><EvidenceImage incident={selectedIncident} /></div>
                  <div className="incident-detail-grid">
                    <div><span>Incident ID</span><strong className="break-value">{selectedIncident.incident_id || `#${selectedIncident.id}`}</strong></div>
                    <div><span>Tracking ID</span><strong>{selectedIncident.track_id ?? "Not available"}</strong></div>
                    <div><span>Camera</span><strong>{cameraLabel(selectedIncident, cameras)}</strong></div>
                    <div><span>Location</span><strong>{selectedIncident.location || "Unknown"}</strong></div>
                    <div><span>Severity</span><strong><span className={`badge badge-${severityBadge(selectedIncident)}`}>{severityLabel(selectedIncident)}</span></strong></div>
                    <div><span>Status</span><strong><span className={`badge badge-${statusBadge(selectedIncident.status)}`}>{statusLabel(selectedIncident.status)}</span></strong></div>
                    <div><span>Missing PPE</span><strong>{selectedIncident.missing_items?.length ? selectedIncident.missing_items.join(", ") : "Not applicable"}</strong></div>
                    <div><span>Restricted Zone</span><strong>{selectedIncident.zone_name || selectedIncident.zone_id || "Not applicable"}</strong></div>
                    <div className="detail-span"><span>Detected</span><strong>{formatDateTime(selectedIncident.timestamp || selectedIncident.detected_at)}</strong></div>
                  </div>

                  <div className="detail-section">
                    <div className="detail-section-heading">
                      <h3>Officer Notes</h3>
                      <span>Saved with this incident</span>
                    </div>
                    <textarea className="form-input notes-input" rows={4} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Add review notes, observations, or resolution details..." />
                    <button type="button" className="btn btn-ghost btn-sm" onClick={saveNotes} disabled={savingNotes}>{savingNotes ? "Saving..." : "Save Notes"}</button>
                  </div>

                  <div className="detail-section">
                    <div className="detail-section-heading">
                      <h3>Corrective Actions</h3>
                      <span>{selectedIncident.corrective_actions?.length || 0} linked</span>
                    </div>
                    <IncidentActions actions={selectedIncident.corrective_actions} />
                  </div>

                  <div className="modal-actions incident-workflow-actions">
                    <button type="button" className="btn btn-danger" onClick={() => deleteIncident(selectedIncident)} disabled={deleting}><Icon name="trash" size={16} /> Delete</button>
                    <button type="button" className="btn btn-ghost" onClick={() => navigate("/officer/actions", { state: { incidentId: selectedIncident.id } })}><Icon name="clipboard" size={16} /> Assign Corrective Action</button>
                    {selectedIncident.status === "open" && <button type="button" className="btn btn-primary" onClick={() => updateStatus("in_progress")} disabled={updatingStatus}>{updatingStatus ? "Updating..." : "Start Review"}</button>}
                    {selectedIncident.status === "in_progress" && <button type="button" className="btn btn-primary" onClick={() => updateStatus("resolved")} disabled={updatingStatus}>{updatingStatus ? "Updating..." : "Resolve Incident"}</button>}
                    {selectedIncident.status === "resolved" && <span className="workflow-complete"><Icon name="check" size={16} /> Incident resolved</span>}
                  </div>
                </>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
