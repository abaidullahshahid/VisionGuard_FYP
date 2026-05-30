import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";

const menuItems = [
  { label:"Dashboard",           icon:"🏠", path:"/worker"              },
  { label:"Locations",           icon:"📍", path:"/worker/locations"    },
  { label:"Safety Instructions", icon:"📖", path:"/worker/instructions" },
];

const riskClass = (l) => ({ High:"red", Medium:"yellow", Low:"green" }[l] || "gray");

export default function WorkerLocations() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedLocation, setSelectedLocation] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    if (!token) navigate("/");
    axios.get("http://localhost:8000/worker/locations", { headers: { Authorization: `Bearer ${token}` } })
      .then(r => setLocations(r.data || []))
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, [navigate]);

  const filtered = locations.filter(loc => loc.name?.toLowerCase().includes(searchTerm.toLowerCase()));

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="worker" />
      <main className="main-content">

        <div className="topbar">
          <div className="topbar-title">Assigned Locations</div>
          <span className="topbar-badge">📍 {locations.length} locations</span>
        </div>

        <div className="content-section" style={{marginBottom:24,padding:20}}>
          <input className="form-input" placeholder="🔍 Search locations…" value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)} style={{width:"100%"}} />
        </div>

        {loading ? <p className="loading-text">Loading locations…</p> :
         filtered.length === 0 ? <p className="loading-text">No locations found.</p> : (
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:24}}>
            <div>
              <h2 className="section-title" style={{marginBottom:16}}>Locations List</h2>
              <div style={{display:"flex",flexDirection:"column",gap:10}}>
                {filtered.map(loc => (
                  <div key={loc.id} onClick={() => setSelectedLocation(loc)} style={{
                    cursor:"pointer", padding:20, borderRadius:12,
                    border:`1.5px solid ${selectedLocation?.id===loc.id?"var(--accent)":"var(--border)"}`,
                    background:selectedLocation?.id===loc.id?"rgba(99,102,241,0.08)":"rgba(255,255,255,0.02)",
                    transition:"all 0.25s ease",
                    boxShadow:selectedLocation?.id===loc.id?"0 0 20px var(--accent-glow)":"none"
                  }}>
                    <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:8}}>
                      <h3 style={{margin:0,fontSize:14,fontWeight:700,color:"var(--text)"}}>{loc.name}</h3>
                      <span className={`badge badge-${riskClass(loc.riskLevel)}`}>{loc.riskLevel}</span>
                    </div>
                    <div style={{fontSize:12,color:"var(--text3)"}}>Floor: {loc.floor || "N/A"} · Capacity: {loc.capacity || "N/A"} workers</div>
                  </div>
                ))}
              </div>
            </div>

            {selectedLocation && (
              <div>
                <h2 className="section-title" style={{marginBottom:16}}>Location Details</h2>
                <div className="content-section">
                  <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:20,paddingBottom:16,borderBottom:"1px solid var(--border)"}}>
                    <h3 style={{margin:0,fontSize:18,fontWeight:700,color:"var(--text)"}}>{selectedLocation.name}</h3>
                    <span className={`badge badge-${riskClass(selectedLocation.riskLevel)}`}>{selectedLocation.riskLevel} Risk</span>
                  </div>

                  <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:20,marginBottom:20}}>
                    {[
                      ["Floor Level",    selectedLocation.floor || "N/A"],
                      ["Capacity",       `${selectedLocation.capacity || "N/A"} workers`],
                      ["Active Cameras", selectedLocation.cameras || 0],
                      ["Last Audit",     selectedLocation.lastAudit ? new Date(selectedLocation.lastAudit).toLocaleDateString() : "N/A"],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <div style={{fontSize:11,color:"var(--text3)",fontWeight:700,textTransform:"uppercase",letterSpacing:"0.5px",marginBottom:4}}>{label}</div>
                        <div style={{fontSize:15,fontWeight:700,color:"var(--text)"}}>{value}</div>
                      </div>
                    ))}
                  </div>

                  <div style={{background:"rgba(99,102,241,0.07)",border:"1px solid rgba(99,102,241,0.15)",borderRadius:10,padding:16,marginBottom:16}}>
                    <h4 style={{margin:"0 0 12px",fontSize:13,fontWeight:700,color:"var(--accent)"}}>Safety Requirements</h4>
                    <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
                      {[["👷","Hard hat required"],["🦺","Safety vest mandatory"],["👞","Steel-toe shoes required"],["🧤","Gloves when handling materials"]].map(([icon,text]) => (
                        <div key={text} style={{display:"flex",alignItems:"center",gap:8,fontSize:12,color:"var(--text2)"}}><span>{icon}</span><span>{text}</span></div>
                      ))}
                    </div>
                  </div>

                  <button className="btn btn-primary" style={{width:"100%",justifyContent:"center"}} onClick={() => navigate("/worker/instructions")}>
                    📋 View Full Safety Instructions
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
