import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { workerMenuItems as menuItems } from "./roleMenuItems";

const categories = ["all","ppe","procedures","emergency","hazards"];
const categoryMeta = {
  all:        { name:"All Instructions",              icon:"book" },
  ppe:        { name:"Personal Protective Equipment", icon:"worker" },
  procedures: { name:"Work Procedures",               icon:"clipboard" },
  emergency:  { name:"Emergency Protocols",           icon:"bell" },
  hazards:    { name:"Hazard Identification",         icon:"alert" },
};

export default function SafetyInstructions() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [instructions, setInstructions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [expandedIndex, setExpandedIndex] = useState(null);
  const [acknowledged, setAcknowledged] = useState([]);

  const handleAcknowledge = (id) => {
    if (!acknowledged.includes(id)) setAcknowledged([...acknowledged, id]);
  };

  useEffect(() => {
    if (!token) navigate("/login");
    axios.get("http://127.0.0.1:8001/worker/safety-instructions", { headers: { Authorization: `Bearer ${token}` } })
      .then(r => setInstructions(r.data || []))
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, [navigate]);

  const filtered = selectedCategory === "all" ? instructions : instructions.filter(i => i.category === selectedCategory);
  const references = [
    ["phone", "Emergency Contact", "Ext. 911"],
    ["medical", "First Aid", "Ground Floor, Room 101"],
    ["rules", "Safety Officer", "Contact Supervisor"],
  ];

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="worker" />
      <main className="main-content">

        <div className="topbar">
          <div>
            <div className="topbar-title">Safety Instructions</div>
            <div className="dashboard-subtitle">Review procedures, hazards, and requirements for your assigned workplaces.</div>
          </div>
          <span className="topbar-badge"><Icon name="book" size={16} /> Learn and stay safe</span>
        </div>

        <div className="segmented-toolbar">
          {categories.map(cat => (
            <button key={cat} onClick={() => setSelectedCategory(cat)}
              className={selectedCategory === cat ? "btn btn-primary" : "btn btn-ghost"}
              style={{fontSize:13}}>
              <Icon name={categoryMeta[cat].icon} size={16} /> {categoryMeta[cat].name}
            </button>
          ))}
        </div>

        {loading ? <p className="loading-text">Loading instructions...</p> :
         filtered.length === 0 ? <p className="loading-text">No instructions found for your assigned locations.</p> : (
          <div className="instructions-layout">

            <div style={{display:"flex",flexDirection:"column",gap:12}}>
              {filtered.map((instruction, idx) => {
                const isAck = acknowledged.includes(instruction.id);
                const iconName = categoryMeta[instruction.category]?.icon || "book";
                return (
                <div key={idx} className="content-section" style={{padding:0,overflow:"hidden"}}>
                  <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"20px 24px",cursor:"pointer",transition:"background 0.25s ease"}}
                    onClick={() => setExpandedIndex(expandedIndex===idx?null:idx)}>
                    <div style={{display:"flex",alignItems:"center",gap:14,flex:1}}>
                      <span className="instruction-icon">
                        <Icon name={iconName} size={22} />
                      </span>
                      <div>
                        <h3 style={{margin:0,fontSize:15,fontWeight:800,color:"var(--text)",display:"flex",alignItems:"center",gap:8}}>
                          {instruction.title}
                          {isAck && <span className="acknowledged-mark"><Icon name="check" size={14} /></span>}
                        </h3>
                        <p style={{margin:"4px 0 0",fontSize:12,color:"var(--text3)"}}>
                          {categoryMeta[instruction.category]?.name}
                          {instruction.location ? ` | ${instruction.location}` : ""}
                        </p>
                      </div>
                    </div>
                    <span style={{color:"var(--text3)",transform:expandedIndex===idx?"rotate(90deg)":"none",transition:"transform 0.25s ease"}}><Icon name="chevronRight" size={16} /></span>
                  </div>

                  {expandedIndex === idx && (
                    <div style={{padding:"0 24px 24px",borderTop:"1px solid var(--border)"}}>
                      <p style={{margin:"20px 0 16px",fontSize:14,color:"var(--text2)",lineHeight:1.7}}>{instruction.description}</p>

                      {instruction.steps?.length > 0 && (
                        <div style={{marginBottom:16}}>
                          <h4 style={{margin:"0 0 10px",fontSize:13,fontWeight:800,color:"var(--text)"}}>Steps to Follow</h4>
                          <ol style={{margin:0,paddingLeft:20}}>
                            {instruction.steps.map((step, i) => <li key={i} style={{margin:"6px 0",fontSize:13,color:"var(--text2)",lineHeight:1.5}}>{step}</li>)}
                          </ol>
                        </div>
                      )}

                      {instruction.warnings?.length > 0 && (
                        <div className="instruction-callout danger" style={{marginBottom:14}}>
                          <h4><Icon name="alert" size={15} /> Warnings</h4>
                          <ul>{instruction.warnings.map((w,i) => <li key={i}>{w}</li>)}</ul>
                        </div>
                      )}

                      {instruction.dos?.length > 0 && (
                        <div className="two-column-info" style={{marginBottom:14}}>
                          <div className="instruction-callout success">
                            <h4><Icon name="check" size={15} /> Do's</h4>
                            <ul>{instruction.dos.map((d,i) => <li key={i}>{d}</li>)}</ul>
                          </div>
                          {instruction.donts?.length > 0 && (
                            <div className="instruction-callout danger">
                              <h4><Icon name="x" size={15} /> Don'ts</h4>
                              <ul>{instruction.donts.map((d,i) => <li key={i}>{d}</li>)}</ul>
                            </div>
                          )}
                        </div>
                      )}

                      <div style={{marginTop:20,textAlign:"right"}}>
                        <button className={`btn ${isAck ? "btn-ghost" : "btn-primary"}`}
                          onClick={(e) => { e.stopPropagation(); handleAcknowledge(instruction.id); }}
                          disabled={isAck}>
                          {isAck ? <><Icon name="check" size={16} /> Acknowledged</> : "Acknowledge"}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )})}
            </div>

            <div className="reference-rail">
              <div className="content-section">
                <h3 style={{margin:"0 0 16px",fontSize:14,fontWeight:800,color:"var(--text)"}}>Quick Reference</h3>
                {references.map(([icon,label,value]) => (
                  <div key={label} style={{display:"flex",alignItems:"center",gap:12,marginBottom:12}}>
                    <span className="table-icon"><Icon name={icon} size={16} /></span>
                    <div>
                      <div style={{fontSize:11,color:"var(--text3)"}}>{label}</div>
                      <div style={{fontSize:13,fontWeight:700,color:"var(--text)",marginTop:2}}>{value}</div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="content-section">
                <h3 style={{margin:"0 0 16px",fontSize:14,fontWeight:800,color:"var(--text)"}}>Daily Safety Tips</h3>
                {["Always report hazards immediately","Wear PPE at all times","Follow all safety procedures","Keep work areas clean","Ask questions if unsure"].map((tip, i) => (
                  <div key={i} style={{display:"flex",alignItems:"center",gap:8,marginBottom:10,fontSize:12,color:"var(--text2)"}}>
                    <span className="status-dot" />{tip}
                  </div>
                ))}
              </div>

              <div className="certification-panel">
                <h3 style={{margin:"0 0 16px",fontSize:14,fontWeight:800,color:"var(--tone-green)"}}>Certifications</h3>
                {["Safety Orientation","Basic PPE Training"].map(cert => (
                  <div key={cert} style={{display:"flex",alignItems:"center",gap:8,marginBottom:10,fontSize:12,color:"var(--tone-green)"}}>
                    <Icon name="check" size={14} />{cert}
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
