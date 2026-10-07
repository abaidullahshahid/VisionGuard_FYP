import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { API_BASE } from "./api";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import menuItems from "./adminMenuItems";
import SelectMenu from "./SelectMenu";

const PPE_OPTIONS = [
  { value: "All PPE", label: "All PPE", description: "Helmet, safety vest and gloves" },
  { value: "Helmet", label: "Helmet" },
  { value: "Safety Vest", label: "Safety Vest" },
  { value: "Gloves", label: "Gloves" },
  { value: "No PPE", label: "None", description: "No PPE required at this location" },
];

const SEVERITY_OPTIONS = ["Low", "Medium", "High", "Critical"].map((level) => ({ value: level, label: level }));

const ppeLabel = (ppeType) => PPE_OPTIONS.find((option) => option.value === ppeType)?.label || ppeType;
const NO_PPE = "No PPE";
// Items an admin can tick together, e.g. Helmet + Safety Vest (all three = All PPE).
const PPE_CHOICES = [
  { value: "Helmet", icon: "worker" },
  { value: "Safety Vest", icon: "vest" },
  { value: "Gloves", icon: "glove" },
];
// "None" means nothing is checked at the location, so no violation (and no severity) is possible.
const hasSeverity = (rule) => rule.is_restricted_area || rule.ppe_type !== NO_PPE;
const formHasSeverity = (form) => form.is_restricted_area || !form.no_ppe;

function requestErrorText(error, fallback) {
  if (!error?.response) {
    // The browser's own reason helps when an extension blocks the request.
    const reason = error?.message && error.message !== "Network Error" ? ` (${error.message})` : "";
    return "Cannot reach the VisionGuard server. If it was just restarted, wait a few seconds and try again. "
      + `If it keeps happening, turn off browser extensions such as download managers, VPNs or ad blockers for this site${reason}.`;
  }
  const detail = error.response.data?.detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join(" ");
  return detail || `${fallback} (server error ${error.response.status}).`;
}

const emptyForm = {
  location_id: "",
  ppe_items: PPE_CHOICES.map((choice) => choice.value),
  no_ppe: false,
  is_restricted_area: false,
  severity_level: "High",
};

const severityBadge = {
  Critical: "red",
  High: "red",
  Medium: "yellow",
  Low: "green",
};

export default function ConfigureSafetyRules() {
  const navigate = useNavigate();
  const token = sessionStorage.getItem("token");
  const [rules, setRules] = useState([]);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [form, setForm] = useState(emptyForm);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const [ruleResponse, locationResponse] = await Promise.all([
        axios.get(`${API_BASE}/admin/safety-rules`, { headers }),
        axios.get(`${API_BASE}/admin/locations`, { headers }),
      ]);
      setRules(ruleResponse.data || []);
      setLocations(locationResponse.data || []);
      setError("");
    } catch (requestError) {
      setError(requestErrorText(requestError, "Failed to load safety rules and locations."));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!token) {
      navigate("/login");
      return;
    }
    fetchData();
  }, [fetchData, navigate, token]);

  const handleAdd = async (event) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (!form.location_id) {
      setError("Select a location for this rule.");
      return;
    }

    if (!form.is_restricted_area && !form.no_ppe && form.ppe_items.length === 0) {
      setError("Tick at least one PPE item, or choose None.");
      return;
    }

    const location_id = Number(form.location_id);
    const headers = { Authorization: `Bearer ${token}` };
    try {
      let message = "Safety rule added successfully.";
      if (form.is_restricted_area || form.no_ppe) {
        await axios.post(`${API_BASE}/admin/safety-rules`, {
          location_id,
          is_restricted_area: form.is_restricted_area,
          ppe_type: form.is_restricted_area ? null : NO_PPE,
          severity_level: formHasSeverity(form) ? form.severity_level : "Low",
        }, { headers });
      } else {
        // One request for all ticked items, e.g. Helmet + Safety Vest.
        const response = await axios.post(`${API_BASE}/admin/safety-rules`, {
          location_id,
          ppe_types: form.ppe_items,
          severity_level: form.severity_level,
        }, { headers });
        message = response.data?.detail || message;
      }
      setSuccess(message);
      setShowForm(false);
      setForm(emptyForm);
      await fetchData();
    } catch (requestError) {
      if (!requestError?.response && await ruleWasSaved(location_id, headers)) {
        // The save went through but its reply was lost on the way back.
        setSuccess("Safety rule added successfully.");
        setShowForm(false);
        setForm(emptyForm);
        await fetchData();
        return;
      }
      setError(requestErrorText(requestError, "Failed to add safety rule."));
    }
  };

  const ruleWasSaved = async (locationId, headers) => {
    try {
      const response = await axios.get(`${API_BASE}/admin/safety-rules`, { headers });
      const before = new Set(rules.map((rule) => rule.id));
      return (response.data || []).some((rule) => rule.location_id === locationId && !before.has(rule.id));
    } catch {
      return false;
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this safety rule?")) return;

    setError("");
    setSuccess("");
    try {
      await axios.delete(`${API_BASE}/admin/safety-rules/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setSuccess("Safety rule deleted successfully.");
      await fetchData();
    } catch (requestError) {
      setError(requestErrorText(requestError, "Failed to delete safety rule."));
    }
  };

  const getLocationName = (locationId) => {
    const location = locations.find((item) => String(item.id) === String(locationId));
    return location?.name || "Unknown location";
  };

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">
        <div className="topbar">
          <div>
            <div className="topbar-title">Safety Rules</div>
            <div className="dashboard-subtitle">
              Define PPE requirements and restricted areas for each monitored location.
            </div>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setShowForm((visible) => !visible);
              setError("");
              setSuccess("");
            }}
          >
            <Icon name={showForm ? "x" : "plus"} size={16} />
            {showForm ? "Cancel" : "Add Rule"}
          </button>
        </div>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {success && <div className="alert alert-success" role="status">{success}</div>}

        {showForm && (
          <section className="content-section menu-host">
            <h2 className="section-title">Add New Safety Rule</h2>
            <form onSubmit={handleAdd}>
              <div className="form-grid">
                <div className="form-group">
                  <label className="form-label" htmlFor="rule-location">Location</label>
                  <SelectMenu
                    id="rule-location"
                    value={form.location_id}
                    placeholder="Select a location"
                    options={locations.map((location) => ({ value: String(location.id), label: location.name }))}
                    onChange={(locationId) => setForm({ ...form, location_id: locationId })}
                  />
                </div>
                {formHasSeverity(form) && (
                  <div className="form-group">
                    <label className="form-label" htmlFor="rule-severity">Severity Level</label>
                    <SelectMenu
                      id="rule-severity"
                      value={form.severity_level}
                      options={SEVERITY_OPTIONS}
                      onChange={(level) => setForm({ ...form, severity_level: level })}
                    />
                  </div>
                )}
              </div>

              {!form.is_restricted_area && (
                <fieldset className="ppe-choice-group">
                  <legend className="form-label">PPE Required</legend>
                  <div className="ppe-choice-grid">
                    {PPE_CHOICES.map((choice) => {
                      const checked = !form.no_ppe && form.ppe_items.includes(choice.value);
                      return (
                        <label key={choice.value} className={`ppe-choice${checked ? " is-on" : ""}`}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(event) => setForm({
                              ...form,
                              no_ppe: false,
                              ppe_items: event.target.checked
                                ? PPE_CHOICES.map((item) => item.value).filter((value) => value === choice.value || form.ppe_items.includes(value))
                                : form.ppe_items.filter((value) => value !== choice.value),
                            })}
                          />
                          <Icon name={choice.icon} size={16} /> {choice.value}
                        </label>
                      );
                    })}
                    <label className={`ppe-choice ppe-choice-none${form.no_ppe ? " is-on" : ""}`}>
                      <input
                        type="checkbox"
                        checked={form.no_ppe}
                        onChange={(event) => setForm({ ...form, no_ppe: event.target.checked, ppe_items: event.target.checked ? [] : form.ppe_items })}
                      />
                      None
                    </label>
                  </div>
                  <small className="form-hint">
                    {form.no_ppe
                      ? "No PPE is required here, so nothing is checked."
                      : form.ppe_items.length === PPE_CHOICES.length
                        ? "All PPE: helmet, safety vest and gloves are required."
                        : form.ppe_items.length
                          ? `Required: ${form.ppe_items.join(" + ")}.`
                          : "Tick one or more items (e.g. Helmet + Safety Vest), or None."}
                  </small>
                </fieldset>
              )}

              <label className="check-field" htmlFor="restricted-area">
                <input
                  id="restricted-area"
                  type="checkbox"
                  checked={form.is_restricted_area}
                  onChange={(event) => setForm({ ...form, is_restricted_area: event.target.checked })}
                />
                <span>
                  <strong>Restricted area</strong>
                  <small>No one may enter. Anyone seen by this location's cameras is a violation, with or without PPE.</small>
                </span>
              </label>

              <div className="form-actions">
                <button type="submit" className="btn btn-primary" disabled={locations.length === 0}>
                  <Icon name="plus" size={16} /> Add Rule
                </button>
                {locations.length === 0 && (
                  <span className="form-hint">Create a location before adding a rule.</span>
                )}
              </div>
            </form>
          </section>
        )}

        <section className="content-section">
          <div className="section-heading">
            <div>
              <h2 className="section-title">Configured Rules</h2>
              <p>{rules.length} safety rule{rules.length === 1 ? "" : "s"} active</p>
            </div>
            <span className="topbar-badge"><Icon name="rules" size={16} /> Policy registry</span>
          </div>

          {loading ? (
            <p className="loading-text">Loading safety rules...</p>
          ) : rules.length === 0 ? (
            <div className="empty-state">
              <span className="empty-state-icon"><Icon name="rules" size={24} /></span>
              <strong>No safety rules configured</strong>
              <span>Add a rule to enforce PPE or restricted-area policies.</span>
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Location</th>
                  <th>PPE Type</th>
                  <th>Restricted Area</th>
                  <th>Severity</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule, index) => (
                  <tr key={rule.id}>
                    <td className="table-index">{index + 1}</td>
                    <td>
                      <span className="table-primary">
                        <span className="table-icon"><Icon name="location" size={16} /></span>
                        {getLocationName(rule.location_id)}
                      </span>
                    </td>
                    <td>
                      <span className={`badge badge-${rule.is_restricted_area ? "gray" : "blue"}`}>
                        {rule.is_restricted_area ? "Not checked" : ppeLabel(rule.ppe_type) || "Not set"}
                      </span>
                    </td>
                    <td>
                      <span className={`badge badge-${rule.is_restricted_area ? "red" : "green"}`}>
                        {rule.is_restricted_area ? "Restricted" : "Standard access"}
                      </span>
                    </td>
                    <td>
                      {hasSeverity(rule) ? (
                        <span className={`badge badge-${severityBadge[rule.severity_level] || "gray"}`}>
                          {rule.severity_level}
                        </span>
                      ) : (
                        <span className="badge badge-gray">Not applicable</span>
                      )}
                    </td>
                    <td>
                      <button type="button" className="btn btn-danger btn-sm" onClick={() => handleDelete(rule.id)}>
                        <Icon name="trash" size={14} /> Delete
                      </button>
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
