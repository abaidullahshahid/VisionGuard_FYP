import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, apiErrorMessage } from "./api";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import menuItems from "./adminMenuItems";
import RestrictedZoneManager from "./RestrictedZoneManager";
import SelectMenu from "./SelectMenu";

const SOURCE_TYPES = [
  { value: "WEBCAM", label: "WEBCAM", placeholder: "0" },
  { value: "RTSP", label: "RTSP/IP", placeholder: "rtsp://192.168.1.100:554/stream" },
  { value: "FILE", label: "FILE", placeholder: "videos/test.mp4" },
];

// Cameras created before source types existed were stored as "IP" or "USB".
const LEGACY_SOURCE_TYPES = { IP: "RTSP", USB: "WEBCAM" };

const normalizeSourceType = (type) => {
  const value = String(type || "").trim().toUpperCase();
  if (LEGACY_SOURCE_TYPES[value]) return LEGACY_SOURCE_TYPES[value];
  return SOURCE_TYPES.some((sourceType) => sourceType.value === value) ? value : null;
};

const sourceTypeLabel = (type) => (
  SOURCE_TYPES.find((sourceType) => sourceType.value === normalizeSourceType(type))?.label || type || "Unknown"
);

const emptyForm = {
  name: "",
  type: "RTSP",
  stream_url: "",
  location_id: "",
  status: "active",
};

export default function ManageCameras() {
  const navigate = useNavigate();
  const formRef = useRef(null);
  const [cameras, setCameras] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [zoneCamera, setZoneCamera] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [cameraResponse, locationResponse] = await Promise.all([
        api.get("/admin/cameras"),
        api.get("/admin/locations"),
      ]);
      setCameras(cameraResponse.data || []);
      setLocations(locationResponse.data || []);
      setError("");
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to load cameras and locations.", navigate));
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

  useEffect(() => {
    if (editingId !== null) formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [editingId]);

  const closeForm = () => {
    setShowForm(false);
    setEditingId(null);
    setForm(emptyForm);
  };

  const startEditing = (camera) => {
    setZoneCamera(null);
    setEditingId(camera.id);
    setForm({
      name: camera.name || "",
      type: normalizeSourceType(camera.type) || "RTSP",
      stream_url: camera.stream_url || "",
      location_id: String(camera.location_id ?? ""),
      status: camera.status === "inactive" ? "inactive" : "active",
    });
    setShowForm(true);
    setError("");
    setSuccess("");
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (!form.location_id) {
      setError("Select a location for this camera.");
      return;
    }
    setSaving(true);

    const body = {
      name: form.name.trim(),
      type: form.type,
      stream_url: form.stream_url.trim(),
      location_id: Number(form.location_id),
    };

    try {
      if (editingId !== null) {
        await api.patch(`/admin/cameras/${editingId}`, { ...body, status: form.status });
        setSuccess("Camera updated successfully.");
      } else {
        await api.post("/admin/cameras", body);
        setSuccess("Camera added successfully.");
      }
      closeForm();
      await fetchData();
    } catch (requestError) {
      setError(apiErrorMessage(
        requestError,
        editingId !== null ? "Failed to update camera." : "Failed to add camera.",
        navigate,
      ));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this camera?")) return;

    setError("");
    setSuccess("");
    try {
      await api.delete(`/admin/cameras/${id}`);
      if (editingId === id) closeForm();
      if (zoneCamera?.id === id) setZoneCamera(null);
      setSuccess("Camera deleted successfully.");
      await fetchData();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to delete camera.", navigate));
    }
  };

  const getLocationName = (locationId) => {
    const location = locations.find((item) => String(item.id) === String(locationId));
    return location?.name || "Unassigned";
  };

  const isEditing = editingId !== null;
  const streamPlaceholder = SOURCE_TYPES.find((sourceType) => sourceType.value === form.type)?.placeholder || "";

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">
        <div className="topbar">
          <div>
            <div className="topbar-title">Manage Cameras</div>
            <div className="dashboard-subtitle">
              Configure video sources and connect each camera to a monitored location.
            </div>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              if (showForm) closeForm();
              else {
                setZoneCamera(null);
                setShowForm(true);
              }
              setError("");
              setSuccess("");
            }}
          >
            <Icon name={showForm ? "x" : "plus"} size={16} />
            {showForm ? "Cancel" : "Add Camera"}
          </button>
        </div>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {success && <div className="alert alert-success" role="status">{success}</div>}

        {showForm && (
          <section className="content-section" ref={formRef}>
            <h2 className="section-title">{isEditing ? "Edit Camera" : "Add New Camera"}</h2>
            <form onSubmit={handleSubmit}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label" htmlFor="camera-name">Camera Name</label>
                  <input
                    id="camera-name"
                    className="form-input"
                    placeholder="e.g. Main Gate Camera"
                    value={form.name}
                    onChange={(event) => setForm({ ...form, name: event.target.value })}
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="camera-type">Source Type</label>
                  <SelectMenu
                    id="camera-type"
                    value={form.type}
                    options={SOURCE_TYPES.map((sourceType) => ({ value: sourceType.value, label: sourceType.label }))}
                    onChange={(type) => setForm({ ...form, type })}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="camera-location">Location</label>
                  <SelectMenu
                    id="camera-location"
                    value={form.location_id}
                    placeholder="Select a location"
                    options={locations.map((location) => ({ value: String(location.id), label: location.name }))}
                    onChange={(locationId) => setForm({ ...form, location_id: locationId })}
                  />
                </div>
                {isEditing && (
                  <div className="form-group">
                    <label className="form-label" htmlFor="camera-status">Status</label>
                    <SelectMenu
                      id="camera-status"
                      value={form.status}
                      options={[{ value: "active", label: "Active" }, { value: "inactive", label: "Inactive" }]}
                      onChange={(status) => setForm({ ...form, status })}
                    />
                  </div>
                )}
                <div className="form-group form-grid-span">
                  <label className="form-label" htmlFor="camera-stream">Stream URL</label>
                  <input
                    id="camera-stream"
                    className="form-input"
                    placeholder={streamPlaceholder}
                    value={form.stream_url}
                    onChange={(event) => setForm({ ...form, stream_url: event.target.value })}
                    required
                  />
                </div>
              </div>
              <div className="form-actions">
                <button type="submit" className="btn btn-primary" disabled={saving || locations.length === 0}>
                  {isEditing
                    ? (saving ? "Saving..." : "Save Changes")
                    : <><Icon name="plus" size={16} /> {saving ? "Adding..." : "Add Camera"}</>}
                </button>
                {locations.length === 0 && (
                  <span className="form-hint">Create a location before adding a camera.</span>
                )}
              </div>
            </form>
          </section>
        )}

        {zoneCamera && (
          <RestrictedZoneManager
            key={zoneCamera.id}
            camera={zoneCamera}
            locationName={getLocationName(zoneCamera.location_id)}
            onClose={() => setZoneCamera(null)}
          />
        )}

        <section className="content-section">
          <div className="section-heading">
            <div>
              <h2 className="section-title">All Cameras</h2>
              <p>{cameras.length} camera{cameras.length === 1 ? "" : "s"} configured</p>
            </div>
            <span className="topbar-badge"><Icon name="camera" size={16} /> Camera registry</span>
          </div>

          {loading ? (
            <p className="loading-text">Loading cameras...</p>
          ) : cameras.length === 0 ? (
            <div className="empty-state">
              <span className="empty-state-icon"><Icon name="camera" size={24} /></span>
              <strong>No cameras configured</strong>
              <span>Add a camera to begin monitoring a location.</span>
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Camera</th>
                  <th>Source Type</th>
                  <th>Location</th>
                  <th>Stream URL</th>
                  <th>Status</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {cameras.map((camera, index) => (
                  <tr key={camera.id}>
                    <td className="table-index">{index + 1}</td>
                    <td>
                      <span className="table-primary">
                        <span className="table-icon"><Icon name="camera" size={16} /></span>
                        {camera.name}
                      </span>
                    </td>
                    <td><span className="badge badge-blue">{sourceTypeLabel(camera.type)}</span></td>
                    <td>{getLocationName(camera.location_id)}</td>
                    <td><code className="table-code">{camera.stream_url}</code></td>
                    <td>
                      <span className={`badge badge-${camera.status === "active" ? "green" : "gray"}`}>
                        <span className={`status-dot ${camera.status === "active" ? "" : "muted"}`} />
                        {camera.status || "unknown"}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 8 }}>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => startEditing(camera)}>
                          Edit
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => {
                            closeForm();
                            setError("");
                            setSuccess("");
                            setZoneCamera(camera);
                          }}
                        >
                          Configure Zones
                        </button>
                        <button type="button" className="btn btn-danger btn-sm" onClick={() => handleDelete(camera.id)}>
                          <Icon name="trash" size={14} /> Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </main>
    </div>
  );
}
