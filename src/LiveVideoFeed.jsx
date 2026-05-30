import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";

const menuItems = [
  { label:"Dashboard",          icon:"🏠", path:"/officer"            },
  { label:"View Incidents",     icon:"⚠️", path:"/officer/incidents"  },
  { label:"Corrective Actions", icon:"📋", path:"/officer/actions"    },
  { label:"Live Video Feed",    icon:"📹", path:"/officer/live"       },
  { label:"Compliance Records", icon:"📊", path:"/officer/compliance" },
];

export default function LiveVideoFeed() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedCamera, setSelectedCamera] = useState(null);
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    if (!token) navigate("/");
    const fetchData = async () => {
      try {
        const [camerasRes, alertsRes] = await Promise.all([
          axios.get("http://localhost:8000/officer/cameras", { headers: { Authorization: `Bearer ${token}` } }),
          axios.get("http://localhost:8000/officer/alerts",  { headers: { Authorization: `Bearer ${token}` } }),
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
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">

        <div className="topbar">
          <div className="topbar-title">Live Video Feed</div>
          <div style={{display:"flex",alignItems:"center",gap:8,padding:"8px 18px",background:"rgba(244,63,94,0.1)",border:"1px solid rgba(244,63,94,0.25)",borderRadius:"99px"}}>
            <span style={{width:8,height:8,borderRadius:"50%",background:"var(--danger)",display:"inline-block",animation:"pulse-glow 1.5s infinite"}} />
            <span style={{fontSize:13,fontWeight:600,color:"var(--danger)"}}>LIVE</span>
          </div>
        </div>

        {loading ? <p className="loading-text">Loading cameras…</p> : (
          <>
            {/* Main video player */}
            {selectedCamera ? (
              <div className="content-section" style={{padding:0,overflow:"hidden",marginBottom:28}}>
                <div style={{background:"#000",aspectRatio:"16/9",display:"flex",alignItems:"center",justifyContent:"center",minHeight:300}}>
                  <div style={{textAlign:"center"}}>
                    <span style={{fontSize:64,display:"block",marginBottom:16,animation:"float 3s ease-in-out infinite"}}>📹</span>
                    <p style={{color:"var(--text)",fontSize:20,fontWeight:700,margin:"0 0 8px"}}>{selectedCamera.name}</p>
                    <p style={{color:"var(--text3)",fontSize:14,margin:0}}>📍 {selectedCamera.location}</p>
                  </div>
                </div>
                <div style={{padding:"16px 24px",display:"flex",gap:32,borderTop:"1px solid var(--border)"}}>
                  {[["Camera",selectedCamera.name],["Location",selectedCamera.location],["Status","● Active"]].map(([label,val]) => (
                    <div key={label}>
                      <div style={{fontSize:11,color:"var(--text3)",fontWeight:700,textTransform:"uppercase",letterSpacing:"0.5px"}}>{label}</div>
                      <div style={{fontSize:14,color:label==="Status"?"var(--success)":"var(--text)",fontWeight:600,marginTop:4}}>{val}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : <p className="loading-text">No cameras available.</p>}

            <div style={{display:"grid", gridTemplateColumns:"2fr 1fr", gap:24}}>
              {/* Camera grid */}
              {cameras.length > 0 && (
                <div className="content-section">
                  <h2 className="section-title">Available Cameras</h2>
                  <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(130px,1fr))",gap:12}}>
                    {cameras.map(camera => (
                      <div key={camera.id} onClick={() => setSelectedCamera(camera)} style={{
                        cursor:"pointer", borderRadius:10, overflow:"hidden",
                        border:`2px solid ${selectedCamera?.id===camera.id?"var(--accent)":"var(--border)"}`,
                        background:"var(--bg-elevated)", transition:"all 0.25s ease",
                        boxShadow:selectedCamera?.id===camera.id?"0 0 16px var(--accent-glow)":"none"
                      }}>
                        <div style={{background:"#000",aspectRatio:"1",display:"flex",alignItems:"center",justifyContent:"center",position:"relative"}}>
                          <span style={{fontSize:24}}>📷</span>
                          <div style={{position:"absolute",top:4,right:4,background:"var(--danger)",color:"#fff",padding:"2px 6px",borderRadius:4,fontSize:9,fontWeight:700}}>LIVE</div>
                        </div>
                        <div style={{padding:"8px 10px"}}>
                          <div style={{fontSize:12,fontWeight:600,color:"var(--text)"}}>{camera.name}</div>
                          <div style={{fontSize:11,color:"var(--text3)"}}>{camera.location}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Live alerts */}
              {alerts.length > 0 && (
                <div className="content-section">
                  <h2 className="section-title">Live Alerts</h2>
                  <div>
                    {alerts.slice(0,5).map((alert, idx) => (
                      <div key={idx} style={{display:"flex",alignItems:"center",gap:12,padding:"14px 0",borderBottom:"1px solid var(--border)"}}>
                        <span style={{fontSize:20}}>⚠️</span>
                        <div style={{flex:1}}>
                          <div style={{fontSize:13,fontWeight:600,color:"var(--text)"}}>{alert.type}</div>
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
