import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import { officerMenuItems as menuItems } from "./roleMenuItems";
import { api, apiErrorMessage } from "./api";
import SelectMenu from "./SelectMenu";
import { formatDateTime } from "./incidentUtils";

const CATEGORY_OPTIONS = [
  { value: "procedures", label: "Work Procedures" },
  { value: "ppe", label: "Personal Protective Equipment" },
  { value: "emergency", label: "Emergency Protocols" },
  { value: "hazards", label: "Hazard Identification" },
];
const categoryLabel = (value) => CATEGORY_OPTIONS.find((option) => option.value === value)?.label || value;
const emptyForm = { location_id: "", category: "procedures", title: "", content: "" };

export default function OfficerInstructions() {
  const navigate = useNavigate();
  const [instructions, setInstructions] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    try {
      const [instructionResponse, locationResponse] = await Promise.all([
        api.get("/officer/safety-instructions"),
        api.get("/officer/locations"),
      ]);
      setInstructions(instructionResponse.data || []);
      setLocations(locationResponse.data || []);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to load safety instructions.", navigate));
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    if (!sessionStorage.getItem("token")) {
      navigate("/login", { replace: true });
      return;
    }
    load();
  }, [load, navigate]);

  const publish = async (event) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (!form.location_id) {
      setError("Select the location this instruction is for.");
      return;
    }
    setSaving(true);
    try {
      await api.post("/officer/safety-instructions", { ...form, location_id: Number(form.location_id) });
      setSuccess("Instruction published. Workers assigned to that location have been notified.");
      setForm(emptyForm);
      setShowForm(false);
      await load();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to publish the instruction.", navigate));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (instruction) => {
    if (!window.confirm(`Delete "${instruction.title}"?`)) return;
    setError("");
    setSuccess("");
    try {
      await api.delete(`/officer/safety-instructions/${instruction.id}`);
      setSuccess("Instruction deleted.");
      await load();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to delete the instruction.", navigate));
    }
  };

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="officer" />
      <main className="main-content">
        <div className="topbar">
          <div>
            <div className="topbar-title">Safety Instructions</div>
            <div className="dashboard-subtitle">Publish instructions to a location's workers and track who has acknowledged them.</div>
          </div>
          <button type="button" className="btn btn-primary" onClick={() => { setShowForm((visible) => !visible); setError(""); setSuccess(""); }}>
            <Icon name={showForm ? "x" : "plus"} size={16} /> {showForm ? "Cancel" : "Publish Instruction"}
          </button>
        </div>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {success && <div className="alert alert-success" role="status">{success}</div>}

        {showForm && (
          <section className="content-section menu-host">
            <h2 className="section-title">New Safety Instruction</h2>
            <form onSubmit={publish}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label" htmlFor="instruction-location">Location</label>
                  <SelectMenu
                    id="instruction-location"
                    value={form.location_id}
                    placeholder="Select a location"
                    options={locations.map((location) => ({ value: String(location.id), label: location.name }))}
                    onChange={(value) => setForm({ ...form, location_id: value })}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label" htmlFor="instruction-category">Category</label>
                  <SelectMenu
                    id="instruction-category"
                    value={form.category}
                    options={CATEGORY_OPTIONS}
                    onChange={(value) => setForm({ ...form, category: value })}
                  />
                </div>
              </div>
              <div className="form-group" style={{ marginTop: 16 }}>
                <label className="form-label" htmlFor="instruction-title">Title</label>
                <input id="instruction-title" className="form-input" maxLength={255} placeholder="e.g. Evacuation route for Block 1" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required />
              </div>
              <div className="form-group" style={{ marginTop: 16 }}>
                <label className="form-label" htmlFor="instruction-content">Instruction</label>
                <textarea id="instruction-content" className="form-input" rows={4} placeholder="What workers must know or do..." value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} required />
              </div>
              <div className="form-actions">
                <button type="submit" className="btn btn-primary" disabled={saving}>{saving ? "Publishing..." : "Publish"}</button>
              </div>
            </form>
          </section>
        )}

        <section className="content-section">
          <div className="section-heading">
            <div>
              <h2 className="section-title">Published Instructions</h2>
              <p>Safety rules are published here automatically; you can add your own.</p>
            </div>
          </div>
          {loading ? <p className="loading-text">Loading instructions...</p> : instructions.length === 0 ? (
            <div className="empty-state">
              <span className="empty-state-icon"><Icon name="book" size={24} /></span>
              <strong>No instructions yet</strong>
              <span>Add a safety rule or publish an instruction for a location.</span>
            </div>
          ) : (
            <table>
              <thead>
                <tr><th>Instruction</th><th>Location</th><th>Category</th><th>Acknowledged</th><th>Published</th><th>Action</th></tr>
              </thead>
              <tbody>
                {instructions.map((instruction) => {
                  const total = instruction.assigned_workers;
                  const done = instruction.acknowledged_workers;
                  return (
                    <tr key={instruction.id}>
                      <td>
                        <span className="table-primary">
                          <span className="table-icon"><Icon name="book" size={16} /></span>
                          <span>
                            {instruction.title}
                            <span className={`badge badge-${instruction.source === "safety_rule" ? "blue" : "gray"} instruction-source`}>
                              {instruction.source === "safety_rule" ? "Safety rule" : "Officer"}
                            </span>
                          </span>
                        </span>
                      </td>
                      <td>{instruction.location}</td>
                      <td className="table-secondary">{categoryLabel(instruction.category)}</td>
                      <td>
                        {total === 0 ? <span className="table-secondary">No workers assigned</span> : (
                          <div className="instruction-progress" title={`${done} of ${total} assigned workers acknowledged`}>
                            <span>{done} / {total} workers</span>
                            <div className="instruction-progress-bar"><span style={{ width: `${(done / total) * 100}%` }} /></div>
                          </div>
                        )}
                      </td>
                      <td className="table-secondary">{formatDateTime(instruction.created_at)}</td>
                      <td>
                        {instruction.source === "safety_rule" ? (
                          <span className="table-secondary" title="Delete the rule in Safety Rules to remove it">Managed by rule</span>
                        ) : (
                          <button type="button" className="btn btn-danger btn-sm" onClick={() => remove(instruction)}>
                            <Icon name="trash" size={14} /> Delete
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      </main>
    </div>
  );
}
