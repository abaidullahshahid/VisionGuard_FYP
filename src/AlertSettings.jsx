import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Sidebar from "./Sidebar";
import { Icon } from "./Icons";
import menuItems from "./adminMenuItems";
import { api, apiErrorMessage } from "./api";
import SelectMenu from "./SelectMenu";

const SEVERITIES = [
  { value: "LOW", label: "Low and above (every violation)" },
  { value: "MEDIUM", label: "Medium and above" },
  { value: "HIGH", label: "High and above (recommended)" },
  { value: "CRITICAL", label: "Critical only" },
];
const HOURS = Array.from({ length: 24 }, (_, hour) => ({
  value: hour,
  label: new Date(2000, 0, 1, hour).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }),
}));
const KIND_LABELS = { incident: "Violation", worker_alert: "Worker alert", camera: "Camera", summary: "Daily summary", test: "Test" };
const logStatusClass = (status) => ({ sent: "green", failed: "red", skipped: "gray" }[status] || "gray");

const formatTime = (value) => (value ? new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "");

function Check({ id, checked, onChange, title, hint }) {
  return (
    <label className="check-field" htmlFor={id}>
      <input id={id} type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>
        <strong>{title}</strong>
        {hint && <small>{hint}</small>}
      </span>
    </label>
  );
}

function Recipients({ emails }) {
  if (!emails?.length) return <small className="alert-log-detail">No active accounts.</small>;
  return <div className="recipient-list">{emails.map((email) => <span key={email} className="recipient-chip">{email}</span>)}</div>;
}

export default function AlertSettings() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const apply = (overview) => {
    setData(overview);
    const { last_summary_date: _last, updated_at: _updated, ...settings } = overview.settings;
    setForm(settings);
  };

  const load = useCallback(async () => {
    try {
      const response = await api.get("/admin/alert-settings");
      apply(response.data);
      setError("");
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Failed to load alert settings.", navigate));
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

  const set = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));

  const save = async (event, overrides = {}) => {
    event?.preventDefault();
    setBusy("save");
    setError("");
    setSuccess("");
    try {
      const response = await api.put("/admin/alert-settings", { ...form, ...overrides, cooldown_minutes: Number(form.cooldown_minutes) || 0 });
      apply(response.data);
      setSuccess("Alert settings saved.");
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not save alert settings.", navigate));
    } finally {
      setBusy("");
    }
  };

  const run = async (kind) => {
    setBusy(kind);
    setError("");
    setSuccess("");
    try {
      const response = await api.post(`/admin/alert-settings/${kind}`);
      setSuccess(response.data.detail);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "The email could not be sent.", navigate));
    } finally {
      setBusy("");
      load();
    }
  };

  const recipients = data?.recipients;
  const enabled = Boolean(data?.settings.email_enabled);
  const dirty = data && form && JSON.stringify(form) !== JSON.stringify((({ last_summary_date: _l, updated_at: _u, ...rest }) => rest)(data.settings));

  return (
    <div className="page-layout admin-shell">
      <Sidebar menuItems={menuItems} role="admin" />
      <main className="main-content">
        <div className="topbar">
          <div>
            <div className="topbar-title">Alert Settings</div>
            <div className="dashboard-subtitle">Choose who gets email alerts for violations, camera problems and the daily compliance summary.</div>
          </div>
          <span className="topbar-badge"><Icon name="bell" size={16} /> In-app alerts are always on</span>
        </div>

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {success && <div className="alert alert-success" role="status">{success}</div>}

        {loading || !form ? <p className="loading-text">Loading alert settings...</p> : (
          <form onSubmit={save}>
            {!data.email_configured ? (
              <div className="alert-status-banner is-off">
                <div>
                  <strong>Gmail is not set up</strong>
                  <span>Add SMTP_USERNAME and SMTP_PASSWORD to backend/.env and restart the backend to send email.</span>
                </div>
              </div>
            ) : (
              <div className={`alert-status-banner ${enabled ? "is-on" : "is-off"}`}>
                <div>
                  <strong>{enabled ? "Email alerts are ON" : "Email alerts are OFF"}</strong>
                  <span>Sent from {data.sender}. {enabled ? "" : "Turn them on, check the recipients, then save."}</span>
                </div>
                <label className="alert-switch" htmlFor="email-enabled">
                  <input id="email-enabled" type="checkbox" checked={form.email_enabled} onChange={(event) => set("email_enabled")(event.target.checked)} />
                  Send email alerts
                </label>
              </div>
            )}

            <div className="alert-settings-grid">
              <section className="content-section">
                <h2 className="section-title">Who receives emails</h2>
                <Check id="email-officers" checked={form.email_officers} onChange={set("email_officers")} title="Safety officers" hint="Violation emails with the snapshot and a link to the incident." />
                <Recipients emails={recipients.officers} />
                <Check id="email-admins" checked={form.email_admins} onChange={set("email_admins")} title="Administrators" hint="Same emails as officers." />
                <Recipients emails={recipients.admins} />
                <Check id="email-workers" checked={form.email_workers} onChange={set("email_workers")} title="Workers at the location" hint={`A short safety alert (no snapshot) to workers assigned to that location. ${recipients.assigned_workers} worker(s) have assignments.`} />
                <div className="form-group" style={{ marginTop: 16 }}>
                  <label className="form-label" htmlFor="extra-recipients">Extra email addresses</label>
                  <textarea id="extra-recipients" className="form-input" rows={2} value={form.extra_recipients} onChange={(event) => set("extra_recipients")(event.target.value)} placeholder="manager@company.com, supervisor@company.com" />
                </div>
                <p className="alert-log-detail">Only real inboxes receive email. Users can change their email address in Profile.</p>
              </section>

              <section className="content-section">
                <h2 className="section-title">When to email</h2>
                <div className="form-group">
                  <label className="form-label" htmlFor="min-severity">Violations to email</label>
                  <SelectMenu id="min-severity" value={form.min_severity} options={SEVERITIES} onChange={set("min_severity")} />
                </div>
                <div className="form-group" style={{ marginTop: 14 }}>
                  <label className="form-label" htmlFor="cooldown">Wait between emails for the same violation at the same location (minutes)</label>
                  <input id="cooldown" type="number" min={0} max={1440} className="form-input" value={form.cooldown_minutes} onChange={(event) => set("cooldown_minutes")(event.target.value)} />
                </div>
                <Check id="attach-snapshot" checked={form.attach_snapshot} onChange={set("attach_snapshot")} title="Include the snapshot" hint="Shows the evidence image inside the email." />
                <Check id="camera-alerts" checked={form.camera_alerts} onChange={set("camera_alerts")} title="Camera problems" hint="Email when a camera feed stops working (at most every 30 minutes per camera)." />
                <Check id="daily-summary" checked={form.daily_summary} onChange={set("daily_summary")} title="Daily compliance summary" hint="One email a day with each location's compliance status and the CSV attached." />
                {form.daily_summary && (
                  <div className="form-group" style={{ marginTop: 14 }}>
                    <label className="form-label" htmlFor="summary-hour">Send the summary at</label>
                    <SelectMenu id="summary-hour" value={form.daily_summary_hour} options={HOURS} onChange={(hour) => set("daily_summary_hour")(Number(hour))} />
                  </div>
                )}
              </section>
            </div>

            <div className="alert-settings-actions">
              <button type="submit" className="btn btn-primary" disabled={busy === "save" || !dirty}>{busy === "save" ? "Saving..." : "Save Settings"}</button>
              <button type="button" className="btn btn-ghost" onClick={() => run("test")} disabled={Boolean(busy) || !data.email_configured || dirty} title={dirty ? "Save your changes first" : ""}>
                {busy === "test" ? "Sending..." : "Send Test Email"}
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => run("send-summary")} disabled={Boolean(busy) || !data.email_configured || dirty} title={dirty ? "Save your changes first" : ""}>
                {busy === "send-summary" ? "Sending..." : "Send Today's Summary Now"}
              </button>
            </div>
            {recipients.staff.length > 0 && (
              <p className="alert-log-detail" style={{ marginTop: -12, marginBottom: 24 }}>Test and summary emails go to: {recipients.staff.join(", ")}</p>
            )}
          </form>
        )}

        {data && (
          <div className="content-section">
            <h2 className="section-title">Recent emails</h2>
            {data.log.length === 0 ? <p className="loading-text">No emails sent yet.</p> : (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Time</th><th>Type</th><th>Subject</th><th>Recipients</th><th>Result</th></tr></thead>
                  <tbody>
                    {data.log.map((entry) => (
                      <tr key={entry.id}>
                        <td style={{ whiteSpace: "nowrap", color: "var(--text2)" }}>{formatTime(entry.created_at)}</td>
                        <td>{KIND_LABELS[entry.kind] || entry.kind}</td>
                        <td style={{ minWidth: 220 }}>{entry.subject}</td>
                        <td><span className="alert-log-detail">{entry.recipients.join(", ") || "—"}</span></td>
                        <td>
                          <span className={`badge badge-${logStatusClass(entry.status)}`}>{entry.status}</span>
                          {entry.detail && <div className="alert-log-detail">{entry.detail}</div>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
