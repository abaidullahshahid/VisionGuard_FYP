import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";

const menuItems = [
  { label:"Dashboard",           icon:"🏠", path:"/worker"              },
  { label:"Locations",           icon:"📍", path:"/worker/locations"    },
  { label:"Safety Instructions", icon:"📖", path:"/worker/instructions" },
];

const categories = ["all","ppe","procedures","emergency","hazards"];
const categoryMeta = {
  all:        { name:"All Instructions",              icon:"📖" },
  ppe:        { name:"Personal Protective Equipment", icon:"👷" },
  procedures: { name:"Work Procedures",               icon:"📋" },
  emergency:  { name:"Emergency Protocols",           icon:"🚨" },
  hazards:    { name:"Hazard Identification",         icon:"⚠️" },
};

export default function SafetyInstructions() {
  const navigate = useNavigate();
  const token = localStorage.getItem("token");
  const [instructions, setInstructions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [expandedIndex, setExpandedIndex] = useState(null);
  const [acknowledged, setAcknowledged] = useState([]);

  const handleAcknowledge = (id) => {
    if (!acknowledged.includes(id)) setAcknowledged([...acknowledged, id]);
  };

  useEffect(() => {
    if (!token) navigate("/");
    axios.get("http://localhost:8000/worker/safety-instructions", { headers: { Authorization: `Bearer ${token}` } })
      .then(r => setInstructions(r.data || []))
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, [navigate]);

  const filtered = selectedCategory === "all" ? instructions : instructions.filter(i => i.category === selectedCategory);

  return (
    <div className="page-layout">
      <Sidebar menuItems={menuItems} role="worker" />
      <main className="main-content">

        <div className="topbar">
          <div className="topbar-title">Safety Instructions</div>
          <span className="topbar-badge">📖 Learn & Stay Safe</span>
        </div>

        {/* Category filter */}
        <div style={{display:"flex",gap:10,marginBottom:28,flexWrap:"wrap"}}>
          {categories.map(cat => (
            <button key={cat} onClick={() => setSelectedCategory(cat)}
              className={selectedCategory === cat ? "btn btn-primary" : "btn btn-ghost"}
              style={{fontSize:13}}>
              {categoryMeta[cat].icon} {categoryMeta[cat].name}
            </button>
          ))}
        </div>

        {loading ? <p className="loading-text">Loading instructions…</p> :
         filtered.length === 0 ? <p className="loading-text">No instructions found.</p> : (
          <div style={{display:"grid",gridTemplateColumns:"1fr 280px",gap:24,alignItems:"start"}}>

            {/* Instructions accordion */}
            <div style={{display:"flex",flexDirection:"column",gap:12}}>
              {filtered.map((instruction, idx) => {
                const isAck = acknowledged.includes(instruction.id);
                return (
                <div key={idx} className="content-section" style={{padding:0,overflow:"hidden"}}>
                  <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"20px 24px",cursor:"pointer",transition:"background 0.2s"}}
                    onClick={() => setExpandedIndex(expandedIndex===idx?null:idx)}>
                    <div style={{display:"flex",alignItems:"center",gap:14,flex:1}}>
                      <span style={{fontSize:28,width:48,height:48,background:"rgba(99,102,241,0.1)",borderRadius:10,display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}>
                        {categoryMeta[instruction.category]?.icon || "📖"}
                      </span>
                      <div>
                        <h3 style={{margin:0,fontSize:15,fontWeight:700,color:"var(--text)",display:"flex",alignItems:"center",gap:8}}>
                          {instruction.title}
                          {isAck && <span style={{color:"var(--success)",fontSize:16}}>✓</span>}
                        </h3>
                        <p style={{margin:"4px 0 0",fontSize:12,color:"var(--text3)"}}>{categoryMeta[instruction.category]?.name}</p>
                      </div>
                    </div>
                    <span style={{color:"var(--text3)",fontSize:12,transform:expandedIndex===idx?"rotate(90deg)":"none",transition:"transform 0.2s"}}>▶</span>
                  </div>

                  {expandedIndex === idx && (
                    <div style={{padding:"0 24px 24px",borderTop:"1px solid var(--border)"}}>
                      <p style={{margin:"20px 0 16px",fontSize:14,color:"var(--text2)",lineHeight:1.7}}>{instruction.description}</p>

                      {instruction.steps?.length > 0 && (
                        <div style={{marginBottom:16}}>
                          <h4 style={{margin:"0 0 10px",fontSize:13,fontWeight:700,color:"var(--text)"}}>Steps to Follow:</h4>
                          <ol style={{margin:0,paddingLeft:20}}>
                            {instruction.steps.map((step, i) => <li key={i} style={{margin:"6px 0",fontSize:13,color:"var(--text2)",lineHeight:1.5}}>{step}</li>)}
                          </ol>
                        </div>
                      )}

                      {instruction.warnings?.length > 0 && (
                        <div style={{background:"rgba(244,63,94,0.08)",borderLeft:"3px solid var(--danger)",borderRadius:8,padding:"14px 16px",marginBottom:14}}>
                          <h4 style={{margin:"0 0 8px",fontSize:13,fontWeight:700,color:"var(--danger)"}}>⚠️ Warnings:</h4>
                          <ul style={{margin:0,paddingLeft:18}}>{instruction.warnings.map((w,i) => <li key={i} style={{margin:"4px 0",fontSize:12,color:"#fb7185"}}>{w}</li>)}</ul>
                        </div>
                      )}

                      {instruction.dos?.length > 0 && (
                        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:14}}>
                          <div style={{background:"rgba(16,185,129,0.08)",borderLeft:"3px solid var(--success)",borderRadius:8,padding:"14px 16px"}}>
                            <h4 style={{margin:"0 0 8px",fontSize:13,fontWeight:700,color:"var(--success)"}}>✓ Do's:</h4>
                            <ul style={{margin:0,paddingLeft:18}}>{instruction.dos.map((d,i) => <li key={i} style={{margin:"4px 0",fontSize:12,color:"#6ee7b7"}}>{d}</li>)}</ul>
                          </div>
                          {instruction.donts?.length > 0 && (
                            <div style={{background:"rgba(244,63,94,0.08)",borderLeft:"3px solid var(--danger)",borderRadius:8,padding:"14px 16px"}}>
                              <h4 style={{margin:"0 0 8px",fontSize:13,fontWeight:700,color:"var(--danger)"}}>✗ Don'ts:</h4>
                              <ul style={{margin:0,paddingLeft:18}}>{instruction.donts.map((d,i) => <li key={i} style={{margin:"4px 0",fontSize:12,color:"#fb7185"}}>{d}</li>)}</ul>
                            </div>
                          )}
                        </div>
                      )}
                      
                      <div style={{marginTop:20,textAlign:"right"}}>
                        <button className={`btn ${isAck ? "btn-ghost" : "btn-primary"}`} 
                          onClick={(e) => { e.stopPropagation(); handleAcknowledge(instruction.id); }}
                          disabled={isAck}>
                          {isAck ? "✓ Acknowledged" : "Acknowledge"}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )})}
            </div>

            {/* Reference sidebar */}
            <div style={{display:"flex",flexDirection:"column",gap:16,position:"sticky",top:20}}>
              <div className="content-section">
                <h3 style={{margin:"0 0 16px",fontSize:14,fontWeight:700,color:"var(--text)"}}>Quick Reference</h3>
                {[["📞","Emergency Contact","Ext. 911"],["🏥","First Aid","Ground Floor, Room 101"],["👔","Safety Officer","Contact Supervisor"]].map(([icon,label,value]) => (
                  <div key={label} style={{display:"flex",alignItems:"center",gap:12,marginBottom:12}}>
                    <span style={{fontSize:20}}>{icon}</span>
                    <div>
                      <div style={{fontSize:11,color:"var(--text3)"}}>{label}</div>
                      <div style={{fontSize:13,fontWeight:600,color:"var(--text)",marginTop:2}}>{value}</div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="content-section">
                <h3 style={{margin:"0 0 16px",fontSize:14,fontWeight:700,color:"var(--text)"}}>Daily Safety Tips</h3>
                {["Always report hazards immediately","Wear PPE at all times","Follow all safety procedures","Keep work areas clean","Ask questions if unsure"].map((tip, i) => (
                  <div key={i} style={{display:"flex",alignItems:"center",gap:8,marginBottom:10,fontSize:12,color:"var(--text2)"}}>
                    <span style={{color:"var(--accent)",fontWeight:700,flexShrink:0}}>•</span>{tip}
                  </div>
                ))}
              </div>

              <div style={{background:"rgba(16,185,129,0.07)",border:"1px solid rgba(16,185,129,0.15)",borderRadius:14,padding:20}}>
                <h3 style={{margin:"0 0 16px",fontSize:14,fontWeight:700,color:"var(--success)"}}>Certifications</h3>
                {["Safety Orientation","Basic PPE Training"].map(cert => (
                  <div key={cert} style={{display:"flex",alignItems:"center",gap:8,marginBottom:10,fontSize:12,color:"#6ee7b7"}}>
                    <span style={{fontWeight:700}}>✓</span>{cert}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
