import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { workerMenuItems as menuItems } from "./roleMenuItems";

const riskClass = (l) => ({ High:"red", Medium:"yellow", Low:"green" }[l] || "gray");
const riskLabel = (l) => l || "Unrated";

export default function WorkerLocations() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedLocation, setSelectedLocation] = useState(null);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    if (!token) navigate("/login");
    axios.get("http://127.0.0.1:8001/worker/locations", { headers: { Authorization: `Bearer ${token}` } })
      .then(r => setLocations(r.data || []))
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, [navigate]);

  const filtered = locations.filter(loc => loc.name?.toLowerCase().includes(searchTerm.toLowerCase()));
  const requirements = [
    ["worker", "Hard hat required"],
    ["vest", "Safety vest mandatory"],
    ["boot", "Steel-toe shoes required"],
    ["glove", "Gloves when handling materials"],
  ];

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="worker" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Assigned Locations</div>
            <div className="dashboard-subtitle">Review your assigned workplaces, risk levels, and safety requirements.</div>
          </div>
          <span className="topbar-badge"><Icon name="location" size={16} /> {locations.length} locations</span>
        </div>

        <div className="content-section search-panel" style={{marginBottom:24,padding:20}}>
          <span className="search-panel-icon"><Icon name="search" size={18} /></span>
          <input className="form-input" placeholder="Search locations..." value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)} style={{width:"100%"}} />
        </div>

        {loading ? <p className="loading-text">Loading locations...</p> :
         filtered.length === 0 ? <p className="loading-text">No locations found.</p> : (
          <div className="split-grid">
            <div>
              <h2 className="section-title" style={{marginBottom:16}}>Locations List</h2>
              <div style={{display:"flex",flexDirection:"column",gap:10}}>
                {filtered.map(loc => (
                  <div
                    key={loc.id}
                    onClick={() => setSelectedLocation(loc)}
                    className={`location-list-card${selectedLocation?.id===loc.id ? " selected" : ""}`}
                  >
                    <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:8}}>
                      <h3 style={{margin:0,fontSize:14,fontWeight:800,color:"var(--text)"}}><span className="table-icon"><Icon name="location" size={16} /></span>{loc.name}</h3>
                      <span className={`badge badge-${riskClass(loc.riskLevel)}`}>{riskLabel(loc.riskLevel)}</span>
                    </div>
                    <div className="location-meta">Zone: {loc.zone || "N/A"} | Department: {loc.department || "N/A"}</div>
                  </div>
                ))}
              </div>
            </div>

            {selectedLocation && (
              <div>
                <h2 className="section-title" style={{marginBottom:16}}>Location Details</h2>
                <div className="content-section">
                  <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:20,paddingBottom:16,borderBottom:"1px solid var(--border)"}}>
                    <h3 style={{margin:0,fontSize:18,fontWeight:800,color:"var(--text)"}}>{selectedLocation.name}</h3>
                    <span className={`badge badge-${riskClass(selectedLocation.riskLevel)}`}>{riskLabel(selectedLocation.riskLevel)} Risk</span>
                  </div>

                  <div className="detail-grid">
                    {[
                      ["Zone",           selectedLocation.zone || "N/A"],
                      ["Department",     selectedLocation.department || "N/A"],
                      ["Active Cameras", selectedLocation.cameras || 0],
                      ["Safety Rules",   selectedLocation.rules || 0],
                      ["Open Incidents", selectedLocation.openIncidents || 0],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <div style={{fontSize:11,color:"var(--text3)",fontWeight:700,textTransform:"uppercase",letterSpacing:"0.5px",marginBottom:4}}>{label}</div>
                        <div style={{fontSize:15,fontWeight:800,color:"var(--text)"}}>{value}</div>
                      </div>
                    ))}
                  </div>

                  <div className="safety-requirements">
                    <h4 style={{margin:"0 0 12px",fontSize:13,fontWeight:800,color:"var(--tone-blue)"}}>Safety Requirements</h4>
                    <div className="requirements-grid">
                      {requirements.map(([icon,text]) => (
                        <div key={text} className="requirement-item"><Icon name={icon} size={16} /><span>{text}</span></div>
                      ))}
                    </div>
                  </div>

                  <button className="btn btn-primary" style={{width:"100%",justifyContent:"center"}} onClick={() => navigate("/worker/instructions")}>
                    <Icon name="clipboard" size={16} /> View Full Safety Instructions
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
