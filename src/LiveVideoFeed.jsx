import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems as menuItems } from "./roleMenuItems";

export default function LiveVideoFeed() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedCamera, setSelectedCamera] = useState(null);
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    if (!token) navigate("/login");
    const fetchData = async () => {
      try {
        const [camerasRes, alertsRes] = await Promise.all([
          axios.get("http://127.0.0.1:8001/officer/cameras", { headers: { Authorization: `Bearer ${token}` } }),
          axios.get("http://127.0.0.1:8001/officer/alerts",  { headers: { Authorization: `Bearer ${token}` } }),
        ]);
        setCameras(camerasRes.data || []);
        setAlerts(alertsRes.data || []);
        if (camerasRes.data?.length > 0) setSelectedCamera(camerasRes.data[0]);
      } catch (err) { console.error(err); }
      finally { setLoading(false); }
    };
    fetchData();
  }, [navigate]);

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Live Video Feed</div>
            <div className="dashboard-subtitle">Monitor active cameras and safety alerts in real time.</div>
          </div>
          <div className="live-pill">
            <span className="live-dot" />
            <span>LIVE</span>
          </div>
        </div>

        {loading ? <p className="loading-text">Loading cameras...</p> : (
          <>
            {selectedCamera ? (
              <div className="content-section" style={{padding:0,overflow:"hidden",marginBottom:28}}>
                <div className="video-stage">
                  <div style={{textAlign:"center"}}>
                    <span className="video-stage-icon"><Icon name="camera" size={58} /></span>
                    <p style={{color:"var(--video-stage-text)",fontSize:20,fontWeight:800,margin:"0 0 8px"}}>{selectedCamera.name}</p>
                    <p style={{color:"var(--video-stage-muted)",fontSize:14,margin:0}}>
                      <Icon name="location" size={14} /> {selectedCamera.location}
                    </p>
                  </div>
                </div>
                <div className="video-meta">
                  {[["Camera",selectedCamera.name],["Location",selectedCamera.location],["Status","Active"]].map(([label,val]) => (
                    <div key={label}>
                      <div style={{fontSize:11,color:"var(--text3)",fontWeight:700,textTransform:"uppercase",letterSpacing:"0.5px"}}>{label}</div>
                      <div style={{display:"flex",alignItems:"center",gap:8,fontSize:14,color:label==="Status"?"var(--tone-green)":"var(--text)",fontWeight:700,marginTop:4}}>
                        {label === "Status" && <span className="status-dot" />}
                        {val}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : <p className="loading-text">No cameras available.</p>}

            <div className="live-layout">
              {cameras.length > 0 && (
                <div className="content-section">
                  <h2 className="section-title">Available Cameras</h2>
                  <div className="camera-grid">
                    {cameras.map(camera => (
                      <div
                        key={camera.id}
                        onClick={() => setSelectedCamera(camera)}
                        className={`camera-tile${selectedCamera?.id===camera.id ? " selected" : ""}`}
                      >
                        <div className="camera-thumb">
                          <Icon name="camera" size={24} />
                          <div className="camera-live-tag">LIVE</div>
                        </div>
                        <div style={{padding:"8px 10px"}}>
                          <div style={{fontSize:12,fontWeight:700,color:"var(--text)"}}>{camera.name}</div>
                          <div style={{fontSize:11,color:"var(--text3)"}}>{camera.location}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {alerts.length > 0 && (
                <div className="content-section">
                  <h2 className="section-title">Live Alerts</h2>
                  <div>
                    {alerts.slice(0,5).map((alert, idx) => (
                      <div key={idx} className="alert-list-item">
                        <span className="table-icon"><Icon name="alert" size={16} /></span>
                        <div style={{flex:1}}>
                          <div style={{fontSize:13,fontWeight:700,color:"var(--text)"}}>{alert.type}</div>
                          <div style={{fontSize:11,color:"var(--text3)",marginTop:2}}>{new Date(alert.timestamp).toLocaleTimeString()}</div>
                        </div>
                        <span className={`badge badge-${alert.severity==="Critical"?"red":"yellow"}`}>{alert.severity}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
