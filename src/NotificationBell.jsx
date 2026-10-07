import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./api";
import { Icon } from "./Icons";

const POLL_MS = 5000;
const TOAST_MS = 8000;
const SEVERITY_TONE = { CRITICAL: "red", HIGH: "red", MEDIUM: "amber", LOW: "green" };
const KIND_ICON = {
  incident: "alert",
  safety_alert: "alert",
  camera: "camera",
  task: "clipboard",
  task_update: "clipboard",
  instruction: "book",
  password_reset: "users",
  account: "user",
};

function timeAgo(value) {
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(value).toLocaleDateString();
}

const tone = (item) => SEVERITY_TONE[item.severity] || "blue";
const NOTIFICATION_EVENT = "visionguard:notifications";

// Lets a page reload its data when a matching alert arrives (e.g. a new incident).
export function useNotificationRefresh(kinds, onNotify) {
  const callback = useRef(onNotify);
  callback.current = onNotify;
  const kindKey = kinds.join(",");
  useEffect(() => {
    const wanted = new Set(kindKey.split(","));
    const handler = (event) => {
      if ((event.detail || []).some((item) => wanted.has(item.kind))) callback.current();
    };
    window.addEventListener(NOTIFICATION_EVENT, handler);
    return () => window.removeEventListener(NOTIFICATION_EVENT, handler);
  }, [kindKey]);
}

export default function NotificationBell() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [toasts, setToasts] = useState([]);
  const lastSeenId = useRef(null);
  const rootRef = useRef(null);

  const load = useCallback(async () => {
    if (!sessionStorage.getItem("token")) return;
    try {
      const { data } = await api.get("/notifications");
      setItems(data.items || []);
      setUnread(data.unread || 0);
      // Pop up only what arrived after this page opened.
      if (lastSeenId.current !== null) {
        const fresh = (data.items || []).filter((item) => !item.read && item.id > lastSeenId.current);
        if (fresh.length) {
          setToasts((current) => [...fresh.slice(0, 3), ...current].slice(0, 3));
          window.dispatchEvent(new CustomEvent(NOTIFICATION_EVENT, { detail: fresh }));
        }
      }
      lastSeenId.current = Math.max(lastSeenId.current ?? 0, data.latest_id || 0);
    } catch {
      // Alerts are best-effort; the page keeps working without them.
    }
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!toasts.length) return undefined;
    const timer = window.setTimeout(() => setToasts((current) => current.slice(0, -1)), TOAST_MS);
    return () => window.clearTimeout(timer);
  }, [toasts]);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) setOpen(false);
    };
    const escape = (event) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const openItem = async (item) => {
    setOpen(false);
    setToasts((current) => current.filter((toast) => toast.id !== item.id));
    if (!item.read) {
      setItems((current) => current.map((entry) => entry.id === item.id ? { ...entry, read: true } : entry));
      setUnread((count) => Math.max(0, count - 1));
      api.post(`/notifications/${item.id}/read`).catch(() => {});
    }
    if (item.link) navigate(item.link);
  };

  const markAllRead = async () => {
    setItems((current) => current.map((item) => ({ ...item, read: true })));
    setUnread(0);
    try { await api.post("/notifications/read-all"); } catch { load(); }
  };

  return (
    <div className="notify-root" ref={rootRef}>
      <button
        type="button"
        className={`notify-trigger${unread ? " has-unread" : ""}`}
        onClick={() => {
          setOpen((value) => !value);
          setToasts([]); // the panel lists them; avoid covering it
        }}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        title="Notifications"
      >
        <Icon name="bell" size={18} />
        {unread > 0 && <span className="notify-count">{unread > 99 ? "99+" : unread}</span>}
      </button>

      {open && (
        <div className="notify-panel" role="dialog" aria-label="Notifications">
          <div className="notify-panel-head">
            <strong>Notifications</strong>
            {unread > 0 && <button type="button" className="notify-link" onClick={markAllRead}>Mark all as read</button>}
          </div>
          {items.length === 0 ? (
            <p className="notify-empty"><Icon name="check" size={16} /> You're all caught up.</p>
          ) : (
            <ul className="notify-list">
              {items.map((item) => (
                <li key={item.id}>
                  <button type="button" className={`notify-item${item.read ? "" : " unread"}`} onClick={() => openItem(item)}>
                    <span className={`notify-icon tone-${tone(item)}`}><Icon name={KIND_ICON[item.kind] || "bell"} size={15} /></span>
                    <span className="notify-copy">
                      <strong>{item.title}</strong>
                      {item.message && <span>{item.message}</span>}
                      <small>
                        {item.severity && <em className={`notify-severity tone-${tone(item)}`}>{item.severity.toLowerCase()}</em>}
                        {timeAgo(item.created_at)}
                      </small>
                    </span>
                    {!item.read && <span className="notify-dot" aria-label="Unread" />}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {toasts.length > 0 && (
        <div className="notify-toasts" aria-live="assertive">
          {toasts.map((toast) => (
            <div key={toast.id} className={`notify-toast tone-${tone(toast)}`} role="alert">
              <button type="button" className="notify-toast-body" onClick={() => openItem(toast)}>
                <Icon name={KIND_ICON[toast.kind] || "bell"} size={18} />
                <span>
                  <strong>{toast.title}</strong>
                  {toast.message && <span>{toast.message}</span>}
                </span>
              </button>
              <button
                type="button"
                className="notify-toast-close"
                aria-label="Dismiss"
                onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}
              >
                <Icon name="x" size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
