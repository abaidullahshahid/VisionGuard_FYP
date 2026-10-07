import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems as menuItems } from "./roleMenuItems";
import { api, apiErrorMessage, apiUrl } from "./api";
import { incidentTypeLabel, severityBadge, severityLabel } from "./incidentUtils";
import { ZoneShapes, useContainedRect } from "./ZoneOverlay";
import SelectMenu from "./SelectMenu";

const DEFAULT_STREAM_ASPECT = 16 / 9;
const AI_POLL_MS = 1000;
const PPE_ITEMS = {
  helmet: { label: "Helmet", icon: "worker" },
  vest: { label: "Safety Vest", icon: "vest" },
  gloves: { label: "Gloves", icon: "glove" },
};
const PERSON_STATE = {
  violation: { label: "Violation", badge: "red" },
  checking: { label: "Checking", badge: "yellow" },
  ok: { label: "OK", badge: "green" },
};

const ppeLabel = (item) => PPE_ITEMS[item]?.label || item;

function violationText(person) {
  const parts = [];
  if (person.restricted_zones?.length) parts.push(`in ${person.restricted_zones.join(", ")}`);
  if (person.missing?.length) parts.push(`no ${person.missing.map(ppeLabel).join(", ")}`);
  return `Person ${person.track_id}: ${parts.join(" · ")}`;
}

function eventText(event) {
  if (event.type === "RESTRICTED_ZONE_VIOLATION") return `Entered ${event.zone_name || "restricted zone"}`;
  return `Missing ${(event.missing_items || []).map(ppeLabel).join(", ")}`;
}

function aiStateLabel(status) {
  if (!status || status.state === "starting") return "Starting AI detection...";
  if (status.state === "running") {
    // Video and AI run separately: smooth video, AI boxes refresh at their own rate.
    return status.video_fps !== undefined && status.video_fps !== null
      ? `AI detection live · Video ${status.video_fps} FPS · AI ${status.fps ?? 0} FPS`
      : `AI detection live · ${status.fps ?? 0} FPS`;
  }
  if (status.state === "error") return `AI stopped: ${status.error || "camera error"}`;
  return "AI detection stopped";
}

function AIDetectionPanel({ status }) {
  const people = status?.people || [];
  const requiredPpe = status?.required_ppe || [];
  const restrictedLocation = Boolean(status?.restricted_location);
  const zoneCount = status?.zones?.length || 0;
  const events = (status?.recent_events || []).slice(0, 6);
  const state = status?.state || "starting";

  return (
    <div className="ai-panel" data-testid="ai-panel">
      <div className="ai-panel-head">
        <span className={`ai-state ai-state-${state}`} role="status">
          <span className="ai-state-dot" />{aiStateLabel(status)}
        </span>
        {state === "running" && (
          <div className="ai-checks">
            <span className="ai-checks-label">Checking</span>
            {restrictedLocation ? (
              <span className="ai-chip ai-chip-danger"><Icon name="alert" size={14} /> Restricted area: anyone seen is a violation</span>
            ) : requiredPpe.length > 0 ? requiredPpe.map((item) => (
              <span key={item} className="ai-chip"><Icon name={PPE_ITEMS[item]?.icon || "check"} size={14} /> {ppeLabel(item)}</span>
            )) : (
              <span className="ai-chip">No PPE required</span>
            )}
            {!restrictedLocation && zoneCount > 0 && (
              <span className="ai-chip ai-chip-danger"><Icon name="alert" size={14} /> {zoneCount} restricted zone{zoneCount === 1 ? "" : "s"}</span>
            )}
          </div>
        )}
      </div>

      <div className="ai-panel-body">
        <div className="ai-column">
          <h3 className="ai-column-title">People in view <span>{people.length}</span></h3>
          {people.length === 0 ? (
            <p className="ai-empty">{state === "running" ? "No one detected right now." : "Waiting for the first analysed frame..."}</p>
          ) : (
            <div className="ai-people">
              {people.map((person) => {
                const personState = PERSON_STATE[person.state] || PERSON_STATE.ok;
                const zones = [...(person.restricted_zones || []), ...(person.entering_zones || [])];
                return (
                  <div key={person.track_id} className={`ai-person ai-person-${person.state}`}>
                    <div className="ai-person-head">
                      <strong>Person {person.track_id}</strong>
                      <span className={`badge badge-${personState.badge}`}>{personState.label}</span>
                    </div>
                    <div className="ai-person-items">
                      {!restrictedLocation && requiredPpe.map((item) => {
                        const worn = Boolean(person.wearing?.[item]);
                        if (!worn && person.not_visible?.includes(item)) {
                          return (
                            <span key={item} className="ai-item ai-item-unknown" title="Out of view, so not checked">
                              <Icon name="search" size={12} /> {ppeLabel(item)}: not in view
                            </span>
                          );
                        }
                        return (
                          <span key={item} className={`ai-item ${worn ? "ai-item-ok" : "ai-item-missing"}`}>
                            <Icon name={worn ? "check" : "x"} size={12} /> {ppeLabel(item)}
                          </span>
                        );
                      })}
                      {zones.map((zone) => (
                        <span key={zone} className="ai-item ai-item-missing"><Icon name="alert" size={12} /> {zone}</span>
                      ))}
                      {restrictedLocation && zones.length === 0 && <span className="ai-item">Detected</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="ai-column">
          <h3 className="ai-column-title">Confirmed violations <span>{status?.events_total || 0}</span></h3>
          {events.length === 0 ? (
            <p className="ai-empty">None in this session. Confirmed violations are saved as incidents.</p>
          ) : (
            <ul className="ai-events">
              {events.map((event, index) => (
                <li key={`${event.time}-${event.track_id}-${index}`}>
                  <span className={`table-icon ${event.type === "RESTRICTED_ZONE_VIOLATION" ? "tone-red" : "tone-amber"}`}><Icon name="alert" size={14} /></span>
                  <div><strong>Person {event.track_id} · {eventText(event)}</strong><span>{new Date(event.time).toLocaleTimeString()}</span></div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

// Browsers can keep an MJPEG request open after its <img> is removed from the
// DOM, so drop the src on unmount to close the connection immediately.
function LiveStreamImage({ src, ...imageProps }) {
  const imageRef = useRef(null);

  useEffect(() => {
    const image = imageRef.current;
    // StrictMode replays effects in development; restore the src it cleared.
    if (image && !image.getAttribute("src")) image.setAttribute("src", src);
    return () => {
      if (image) image.removeAttribute("src");
    };
  }, [src]);

  // eslint-disable-next-line jsx-a11y/alt-text -- alt is passed through imageProps.
  return <img ref={imageRef} className="live-video-image" src={src} {...imageProps} />;
}

export default function LiveVideoFeed() {
  const navigate = useNavigate();
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedCameraId, setSelectedCameraId] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [error, setError] = useState("");
  const [streamUrl, setStreamUrl] = useState("");
  const [streamState, setStreamState] = useState("idle");
  const [streamError, setStreamError] = useState("");
  const [streamRetry, setStreamRetry] = useState(0);
  const [streamAspect, setStreamAspect] = useState(DEFAULT_STREAM_ASPECT);
  const [zones, setZones] = useState([]);
  const [aiStatus, setAiStatus] = useState(null);
  const stageRef = useRef(null);

  const fetchData = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    setError("");
    try {
      const [cameraResponse, locationResponse, alertResponse] = await Promise.all([
        api.get("/officer/cameras"),
        api.get("/officer/locations"),
        api.get("/officer/alerts"),
      ]);
      const locations = new Map((locationResponse.data || []).map((location) => [String(location.id), location.name]));
      const resolvedCameras = (cameraResponse.data || []).map((camera) => ({
        ...camera,
        locationName: locations.get(String(camera.location_id)) || `Location #${camera.location_id}`,
      }));
      setCameras(resolvedCameras);
      setAlerts(alertResponse.data || []);
      // Keep the officer's selection by ID across refreshes; never auto-select.
      setSelectedCameraId((currentId) => (
        resolvedCameras.some((camera) => camera.id === currentId) ? currentId : null
      ));
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to load cameras and alerts.", navigate));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [navigate]);

  useEffect(() => {
    if (!sessionStorage.getItem("token")) {
      navigate("/login", { replace: true });
      return undefined;
    }
    fetchData(true);
    const refreshTimer = window.setInterval(() => fetchData(false), 30000);
    return () => window.clearInterval(refreshTimer);
  }, [fetchData, navigate]);

  const selectedCamera = cameras.find((camera) => camera.id === selectedCameraId) || null;
  const selectedCameraStatus = selectedCamera ? String(selectedCamera.status || "active").toLowerCase() : "";

  useEffect(() => {
    let cancelled = false;
    setStreamUrl("");
    setStreamError("");
    setStreamAspect(DEFAULT_STREAM_ASPECT);

    if (selectedCameraId === null) {
      setStreamState("idle");
      return () => { cancelled = true; };
    }
    if (selectedCameraStatus !== "active") {
      setStreamState("offline");
      return () => { cancelled = true; };
    }

    setStreamState("loading");
    api.get(`/officer/cameras/${selectedCameraId}/stream-url`)
      .then((response) => {
        if (!cancelled) setStreamUrl(apiUrl(response.data?.stream_url));
      })
      .catch((requestError) => {
        if (cancelled) return;
        setStreamState("unavailable");
        setStreamError(apiErrorMessage(requestError, "Stream unavailable.", navigate));
      });

    return () => { cancelled = true; };
  }, [navigate, selectedCameraId, selectedCameraStatus, streamRetry]);

  // Enabled restricted zones for the selected camera (read-only overlay),
  // re-fetched every 30 s so Admin changes appear without a page reload.
  useEffect(() => {
    setZones([]);
    if (selectedCameraId === null) return undefined;
    let cancelled = false;
    const loadZones = () => {
      api.get(`/officer/cameras/${selectedCameraId}/restricted-zones`)
        .then((response) => {
          if (!cancelled) setZones(response.data || []);
        })
        .catch(() => {
          // The overlay is informational; streaming continues without it.
          if (!cancelled) setZones([]);
        });
    };
    loadZones();
    const zoneTimer = window.setInterval(loadZones, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(zoneTimer);
    };
  }, [selectedCameraId]);

  // Live AI state for the watched camera; the backend runs detection only
  // while this stream is open.
  useEffect(() => {
    setAiStatus(null);
    if (selectedCameraId === null || !streamUrl) return undefined;
    let cancelled = false;
    const poll = () => {
      api.get(`/officer/cameras/${selectedCameraId}/ai-status`)
        .then((response) => {
          if (!cancelled) setAiStatus(response.data || null);
        })
        .catch(() => {
          // Keep the last status; the video itself reports stream failures.
        });
    };
    poll();
    const aiTimer = window.setInterval(poll, AI_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(aiTimer);
    };
  }, [selectedCameraId, streamUrl]);

  // Each confirmed violation is saved as an incident: refresh the alert list.
  const confirmedEvents = aiStatus?.events_total || 0;
  useEffect(() => {
    if (confirmedEvents > 0) fetchData(false);
  }, [confirmedEvents, fetchData]);

  const activeViolators = (aiStatus?.people || []).filter((person) => person.state === "violation");
  const showZoneOverlay = streamState === "playing" && zones.length > 0;
  // Align with the painted video, not the stage box, in case of letterboxing.
  const zoneOverlayRect = useContainedRect(stageRef, streamAspect, showZoneOverlay);

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">
        <div className="topbar">
          <div>
            <div className="topbar-title">Live Video Feed</div>
            <div className="dashboard-subtitle">Monitor active cameras and open AI safety alerts.</div>
          </div>
          <div className="topbar-actions">
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => fetchData(false)} disabled={refreshing}>{refreshing ? "Refreshing..." : "Refresh"}</button>
            <div className="live-pill"><span className="live-dot" /><span>LIVE</span></div>
          </div>
        </div>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {loading ? <p className="loading-text">Loading cameras...</p> : (
          <>
            {cameras.length === 0 ? (
              <div className="content-section empty-state"><span className="empty-state-icon"><Icon name="camera" size={24} /></span><strong>No active cameras available</strong><span>Add or activate a camera from Camera Management.</span></div>
            ) : (
              <section className="content-section live-player">
                <div className="live-player-toolbar">
                  <div className="live-player-select">
                    <label className="form-label" htmlFor="live-camera-select">Camera</label>
                    <SelectMenu
                      id="live-camera-select"
                      value={selectedCameraId ?? ""}
                      placeholder="Select a camera"
                      options={cameras.map((camera) => ({ value: camera.id, label: `${camera.name} | ${camera.locationName}` }))}
                      onChange={(cameraId) => setSelectedCameraId(Number(cameraId))}
                    />
                  </div>
                  {/* In the toolbar, not over the video, so it never hides AI labels. */}
                  {streamState === "playing" && activeViolators.length > 0 && (
                    <div className="ai-violation-banner" role="alert">
                      <Icon name="alert" size={18} />
                      <div>
                        <strong>Violation detected</strong>
                        {activeViolators.slice(0, 3).map((person) => (
                          <span key={person.track_id}>{violationText(person)}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  {selectedCamera && (
                    <button type="button" className="btn btn-danger btn-sm" onClick={() => setSelectedCameraId(null)}>
                      <Icon name="x" size={14} /> Stop Streaming
                    </button>
                  )}
                </div>
                <div className="live-player-viewport">
                  <div ref={stageRef} className="video-stage" style={{ "--stream-aspect": String(streamAspect) }}>
                    {selectedCamera ? (
                      <>
                        {streamUrl && (
                          <LiveStreamImage
                            key={streamUrl}
                            src={streamUrl}
                            alt={`Live feed from ${selectedCamera.name}`}
                            onLoad={(event) => {
                              const { naturalWidth, naturalHeight } = event.currentTarget;
                              if (naturalWidth > 0 && naturalHeight > 0) setStreamAspect(naturalWidth / naturalHeight);
                              setStreamState("playing");
                            }}
                            onError={() => {
                              setStreamState("unavailable");
                              setStreamError("The camera stream stopped or could not be displayed.");
                            }}
                          />
                        )}
                        {showZoneOverlay && zoneOverlayRect && (
                          <div
                            className="zone-overlay-box"
                            data-testid="restricted-zone-overlay"
                            style={{
                              left: zoneOverlayRect.left,
                              top: zoneOverlayRect.top,
                              width: zoneOverlayRect.width,
                              height: zoneOverlayRect.height,
                            }}
                          >
                            <ZoneShapes
                              labelPrefix="RESTRICTED"
                              zones={zones.map((zone) => ({
                                key: zone.id,
                                name: zone.name,
                                points: zone.polygon_points,
                                variant: "restricted",
                              }))}
                            />
                          </div>
                        )}
                        {streamState !== "playing" && (
                          <div className="video-stream-state" role="status">
                            <span className="video-stage-icon"><Icon name="camera" size={58} /></span>
                            <p className="video-stage-title">
                              {streamState === "offline" ? "Camera offline" : streamState === "unavailable" ? "Stream unavailable" : "Starting camera and AI detection..."}
                            </p>
                            <p className="video-stage-location">
                              {streamError || `${selectedCamera.name} | ${selectedCamera.locationName}`}
                            </p>
                            {streamState === "unavailable" && (
                              <button type="button" className="btn btn-primary btn-sm stream-retry" onClick={() => setStreamRetry((value) => value + 1)}>Retry</button>
                            )}
                          </div>
                        )}
                        <div className="video-stage-caption" aria-hidden="true">
                          <strong>{selectedCamera.name}</strong>
                          <span><Icon name="location" size={13} /> {selectedCamera.locationName}</span>
                        </div>
                      </>
                    ) : (
                      <div className="video-stream-state" role="status">
                        <span className="video-stage-icon"><Icon name="camera" size={58} /></span>
                        <p className="video-stage-title">Select a camera to start live monitoring</p>
                        <p className="video-stage-location">Choose a camera above or from Available Cameras below.</p>
                      </div>
                    )}
                  </div>
                </div>
                {selectedCamera && (
                  <div className="video-meta">
                    {[["Camera", selectedCamera.name], ["Location", selectedCamera.locationName], ["Status", selectedCamera.status || "Active"]].map(([label, value]) => (
                      <div key={label}>
                        <div className="video-meta-label">{label}</div>
                        <div className={`video-meta-value${label === "Status" ? " active" : ""}`}>
                          {label === "Status" && <span className="status-dot" />}{value}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {selectedCamera && streamUrl && <AIDetectionPanel status={aiStatus} />}
              </section>
            )}

            <div className="live-layout">
              <div className="content-section">
                <div className="section-heading"><div><h2 className="section-title">Available Cameras</h2><p>{cameras.length} active camera{cameras.length === 1 ? "" : "s"}</p></div></div>
                {cameras.length === 0 ? <p className="loading-text">No cameras available.</p> : (
                  <div className="camera-grid">
                    {cameras.map((camera) => (
                      <button type="button" key={camera.id} onClick={() => setSelectedCameraId(camera.id)} className={`camera-tile${selectedCameraId === camera.id ? " selected" : ""}`}>
                        <div className="camera-thumb"><Icon name="camera" size={24} /><div className="camera-live-tag">LIVE</div></div>
                        <div className="camera-tile-copy"><strong>{camera.name}</strong><span>{camera.locationName}</span></div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="content-section">
                <div className="section-heading"><div><h2 className="section-title">Open Incident Alerts</h2><p>Derived from open database incidents</p></div></div>
                {alerts.length === 0 ? (
                  <div className="empty-state compact-empty"><span className="empty-state-icon"><Icon name="check" size={22} /></span><strong>No active alerts</strong><span>New open incidents will appear automatically.</span></div>
                ) : alerts.slice(0, 8).map((alert) => (
                  <button type="button" key={alert.id} className="alert-list-item alert-list-button" onClick={() => navigate("/officer/incidents")}>
                    <span className="table-icon tone-red"><Icon name="alert" size={16} /></span>
                    <div className="alert-list-copy"><strong>{incidentTypeLabel(alert.type)}</strong><span>{new Date(alert.timestamp).toLocaleString()}</span></div>
                    <span className={`badge badge-${severityBadge(alert.severity)}`}>{severityLabel(alert.severity)}</span>
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
