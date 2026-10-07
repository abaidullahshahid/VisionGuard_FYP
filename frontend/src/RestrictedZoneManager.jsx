import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, apiErrorMessage } from "./api";
import { Icon } from "./Icons";
import { ZoneShapes } from "./ZoneOverlay";
import { MIN_ZONE_POINTS, toNormalizedPoint } from "./zoneGeometry";

const DEFAULT_FRAME_ASPECT = 16 / 9;

// The snapshot is requested as a Blob, so a JSON error body arrives as a Blob too.
async function snapshotErrorMessage(requestError, navigate) {
  const fallback = "Could not load a frame from this camera.";
  const response = requestError?.response;
  if (!response || response.status === 401 || response.status === 403) {
    return apiErrorMessage(requestError, fallback, navigate);
  }
  try {
    const detail = JSON.parse(await response.data.text()).detail;
    return typeof detail === "string" && detail ? detail : fallback;
  } catch {
    return fallback;
  }
}

export default function RestrictedZoneManager({ camera, locationName, onClose }) {
  const navigate = useNavigate();
  const sectionRef = useRef(null);
  const frameRef = useRef(null);
  const zonesPath = `/admin/cameras/${camera.id}/restricted-zones`;
  const [zones, setZones] = useState([]);
  const [loadingZones, setLoadingZones] = useState(true);
  const [snapshotUrl, setSnapshotUrl] = useState("");
  const [snapshotState, setSnapshotState] = useState("loading");
  const [snapshotError, setSnapshotError] = useState("");
  const [snapshotRequest, setSnapshotRequest] = useState(0);
  const [frameAspect, setFrameAspect] = useState(DEFAULT_FRAME_ASPECT);
  const [draft, setDraft] = useState([]);
  const [zoneName, setZoneName] = useState("");
  const [editingZoneId, setEditingZoneId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const loadZones = useCallback(async () => {
    try {
      const response = await api.get(zonesPath);
      setZones(response.data || []);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to load restricted zones.", navigate));
    } finally {
      setLoadingZones(false);
    }
  }, [navigate, zonesPath]);

  useEffect(() => {
    loadZones();
  }, [loadZones]);

  useEffect(() => {
    sectionRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, []);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    setSnapshotUrl("");
    setSnapshotState("loading");
    setSnapshotError("");
    api.get(`/admin/cameras/${camera.id}/snapshot`, { responseType: "blob", timeout: 30000 })
      .then((response) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(response.data);
        setSnapshotUrl(objectUrl);
      })
      .catch(async (requestError) => {
        const message = await snapshotErrorMessage(requestError, navigate);
        if (cancelled) return;
        setSnapshotState("error");
        setSnapshotError(message);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [camera.id, navigate, snapshotRequest]);

  const resetDraft = () => {
    setDraft([]);
    setZoneName("");
    setEditingZoneId(null);
  };

  const handleFrameClick = (event) => {
    if (snapshotState !== "ready" || !frameRef.current) return;
    // The frame box has the snapshot's exact aspect ratio, so it is the
    // displayed image content and maps 1:1 onto normalized coordinates.
    const point = toNormalizedPoint(event.clientX, event.clientY, frameRef.current.getBoundingClientRect());
    if (point) setDraft((points) => [...points, point]);
  };

  const startEditing = (zone) => {
    setEditingZoneId(zone.id);
    setZoneName(zone.name);
    setDraft(zone.polygon_points.map(([x, y]) => [x, y]));
    setError("");
    setSuccess("");
  };

  const saveZone = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    const body = { name: zoneName.trim(), polygon_points: draft };
    try {
      if (editingZoneId !== null) {
        await api.patch(`${zonesPath}/${editingZoneId}`, body);
        setSuccess(`Zone "${body.name}" updated.`);
      } else {
        await api.post(zonesPath, body);
        setSuccess(`Zone "${body.name}" saved.`);
      }
      resetDraft();
      await loadZones();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to save restricted zone.", navigate));
    } finally {
      setSaving(false);
    }
  };

  const toggleZone = async (zone) => {
    setError("");
    setSuccess("");
    try {
      await api.patch(`${zonesPath}/${zone.id}`, { enabled: !zone.enabled });
      setSuccess(`Zone "${zone.name}" ${zone.enabled ? "disabled" : "enabled"}.`);
      await loadZones();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to update restricted zone.", navigate));
    }
  };

  const deleteZone = async (zone) => {
    if (!window.confirm(`Delete restricted zone "${zone.name}"?`)) return;
    setError("");
    setSuccess("");
    try {
      await api.delete(`${zonesPath}/${zone.id}`);
      if (editingZoneId === zone.id) resetDraft();
      setSuccess(`Zone "${zone.name}" deleted.`);
      await loadZones();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to delete restricted zone.", navigate));
    }
  };

  const savedShapes = zones
    .filter((zone) => zone.id !== editingZoneId)
    .map((zone) => ({
      key: zone.id,
      name: zone.name,
      points: zone.polygon_points,
      variant: zone.enabled ? "restricted" : "disabled",
    }));
  const draftShape = draft.length ? [{ key: "draft", name: zoneName.trim(), points: draft, variant: "draft" }] : [];
  const canSave = !saving && zoneName.trim() !== "" && draft.length >= MIN_ZONE_POINTS;
  const drawingHint = draft.length >= MIN_ZONE_POINTS
    ? "Polygon closed. Keep clicking to add points, or name and save it."
    : `Click at least ${MIN_ZONE_POINTS - draft.length} more point${MIN_ZONE_POINTS - draft.length === 1 ? "" : "s"} on the frame.`;

  return (
    <section className="content-section zone-manager" ref={sectionRef}>
      <div className="section-heading">
        <div>
          <h2 className="section-title">Restricted Zones · {camera.name}</h2>
          <p>{locationName ? `${locationName} · ` : ""}Click on the camera frame to outline an area people must not enter.</p>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
          <Icon name="x" size={14} /> Close
        </button>
      </div>

      {error && <div className="alert alert-error" role="alert">{error}</div>}
      {success && <div className="alert alert-success" role="status">{success}</div>}

      <div className="zone-manager-layout">
        <div className="zone-manager-canvas">
          <div
            ref={frameRef}
            className={`zone-editor-frame${snapshotState === "ready" ? " ready" : ""}`}
            style={{ "--frame-aspect": String(frameAspect) }}
            onClick={handleFrameClick}
            data-testid="zone-drawing-surface"
          >
            {snapshotUrl && (
              <img
                className="zone-editor-image"
                src={snapshotUrl}
                alt={`Current frame from ${camera.name}`}
                draggable={false}
                onLoad={(event) => {
                  const { naturalWidth, naturalHeight } = event.currentTarget;
                  if (naturalWidth > 0 && naturalHeight > 0) setFrameAspect(naturalWidth / naturalHeight);
                  setSnapshotState("ready");
                }}
                onError={() => {
                  setSnapshotState("error");
                  setSnapshotError("The camera frame could not be displayed.");
                }}
              />
            )}
            {snapshotState === "ready" ? (
              <>
                <ZoneShapes zones={[...savedShapes, ...draftShape]} />
                {draft.map(([x, y], index) => (
                  <span
                    key={`${index}-${x}-${y}`}
                    className={`zone-vertex${index === 0 ? " zone-vertex--first" : ""}`}
                    style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
                  />
                ))}
              </>
            ) : (
              <div className="zone-editor-state" role="status">
                <span>{snapshotState === "error" ? snapshotError : "Loading camera frame..."}</span>
                {snapshotState === "error" && (
                  <button type="button" className="btn btn-primary btn-sm" onClick={() => setSnapshotRequest((value) => value + 1)}>Retry</button>
                )}
              </div>
            )}
          </div>
          <p className="zone-editor-hint">
            {draft.length} point{draft.length === 1 ? "" : "s"} · {drawingHint}
          </p>
        </div>

        <div className="zone-manager-side">
          <form onSubmit={saveZone}>
            <div className="form-group">
              <label className="form-label" htmlFor="zone-name">Zone Name</label>
              <input
                id="zone-name"
                className="form-input"
                placeholder="e.g. Heavy Machinery Area"
                maxLength={150}
                value={zoneName}
                onChange={(event) => setZoneName(event.target.value)}
              />
            </div>
            <div className="zone-draw-actions">
              <button type="submit" className="btn btn-primary btn-sm" disabled={!canSave}>
                {saving ? "Saving..." : editingZoneId !== null ? "Update Zone" : "Save Zone"}
              </button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDraft((points) => points.slice(0, -1))} disabled={!draft.length}>
                Undo Last Point
              </button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDraft([])} disabled={!draft.length}>
                Clear Drawing
              </button>
              {editingZoneId !== null && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={resetDraft}>Cancel Edit</button>
              )}
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSnapshotRequest((value) => value + 1)} disabled={snapshotState === "loading"}>
                Refresh Frame
              </button>
            </div>
          </form>

          <h3 className="section-title zone-list-title">Saved zones ({zones.length})</h3>
          {loadingZones ? (
            <p className="loading-text">Loading zones...</p>
          ) : zones.length === 0 ? (
            <p className="zone-list-empty">No restricted zones for this camera. Zone checks are skipped until one is added.</p>
          ) : (
            <ul className="zone-list">
              {zones.map((zone) => (
                <li key={zone.id} className={`zone-list-item${zone.id === editingZoneId ? " editing" : ""}`}>
                  <div className="zone-list-copy">
                    <strong>{zone.name}</strong>
                    <span className={`badge badge-${zone.enabled ? "green" : "gray"}`}>{zone.enabled ? "Enabled" : "Disabled"}</span>
                  </div>
                  <div className="zone-list-actions">
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => startEditing(zone)}>Edit</button>
                    <button type="button" className="btn btn-ghost btn-sm" onClick={() => toggleZone(zone)}>{zone.enabled ? "Disable" : "Enable"}</button>
                    <button type="button" className="btn btn-danger btn-sm" onClick={() => deleteZone(zone)}>
                      <Icon name="trash" size={14} /> Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
