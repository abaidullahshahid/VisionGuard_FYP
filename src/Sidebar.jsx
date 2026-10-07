import { useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { API_BASE } from "./api";
import { Icon } from "./Icons";
import ThemeToggle from "./ThemeToggle";
import NotificationBell from "./NotificationBell";

const logo = `${process.env.PUBLIC_URL}/images/burger.png?v=transparent-20260615`;
const emptyProfile = {
  name: "",
  email: "",
  department: "",
  current_password: "",
  new_password: "",
  confirm_password: "",
};

export default function Sidebar({ menuItems, role }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileLoaded, setProfileLoaded] = useState(false);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileForm, setProfileForm] = useState(emptyProfile);
  const [profileError, setProfileError] = useState("");
  const [profileSuccess, setProfileSuccess] = useState("");
  const navRef = useRef(null);

  // The navbar sticks to the top and wraps onto more rows on narrow screens;
  // publish its height so sticky page parts and scrolling stop below it.
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return undefined;
    const publish = () => document.documentElement.style.setProperty("--app-nav-height", `${nav.offsetHeight}px`);
    publish();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(publish);
    observer.observe(nav);
    return () => observer.disconnect();
  }, []);

  const handleLogout = () => {
    sessionStorage.clear();
    navigate("/login");
  };

  const roleLabel = {
    admin:   "Administrator",
    officer: "Safety Officer",
    worker:  "Field Worker",
  }[role] || role;

  const initials = (profileForm.name || sessionStorage.getItem("name") || roleLabel || "User")
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0]?.toUpperCase())
    .join("") || "U";

  const authHeaders = () => ({ Authorization: `Bearer ${sessionStorage.getItem("token")}` });

  const loadProfile = async () => {
    const token = sessionStorage.getItem("token");
    if (!token) return;
    setProfileLoading(true);
    setProfileError("");
    try {
      const response = await axios.get(`${API_BASE}/auth/me`, { headers: authHeaders() });
      setProfileForm({
        name: response.data.name || "",
        email: response.data.email || "",
        department: response.data.department || "",
        current_password: "",
        new_password: "",
        confirm_password: "",
      });
      sessionStorage.setItem("name", response.data.name || "");
      setProfileLoaded(true);
    } catch (err) {
      setProfileError(err.response?.data?.detail || "Unable to load profile.");
    } finally {
      setProfileLoading(false);
    }
  };

  const toggleProfile = () => {
    const nextOpen = !profileOpen;
    setProfileOpen(nextOpen);
    setProfileSuccess("");
    setProfileError("");
    if (nextOpen && !profileLoaded) loadProfile();
  };

  const handleProfileChange = (field, value) => {
    setProfileForm(prev => ({ ...prev, [field]: value }));
  };

  const handleProfileSave = async (e) => {
    e.preventDefault();
    setProfileSaving(true);
    setProfileError("");
    setProfileSuccess("");

    const payload = {
      name: profileForm.name,
      email: profileForm.email,
      department: profileForm.department,
    };

    if (profileForm.current_password || profileForm.new_password || profileForm.confirm_password) {
      payload.current_password = profileForm.current_password;
      payload.new_password = profileForm.new_password;
      payload.confirm_password = profileForm.confirm_password;
    }

    try {
      const response = await axios.patch(`${API_BASE}/auth/me`, payload, { headers: authHeaders() });
      setProfileForm({
        name: response.data.name || "",
        email: response.data.email || "",
        department: response.data.department || "",
        current_password: "",
        new_password: "",
        confirm_password: "",
      });
      sessionStorage.setItem("name", response.data.name || "");
      setProfileSuccess("Profile updated successfully.");
      setProfileLoaded(true);
    } catch (err) {
      setProfileError(err.response?.data?.detail || "Unable to update profile.");
    } finally {
      setProfileSaving(false);
    }
  };

  return (
    <header className="sidebar app-navbar" ref={navRef}>
      <div className="sidebar-logo">
        <span className="sidebar-logo-icon">
          <img src={logo} alt="VisionGuard" />
        </span>
        <div>
          <div className="sidebar-logo-text">VisionGuard</div>
          <div className="sidebar-logo-sub">{roleLabel}</div>
        </div>
      </div>

      <div className="sidebar-section-label">Navigation</div>

      <nav className="sidebar-nav">
        {menuItems.map((item) => (
          <button
            key={item.label}
            className={`nav-item${location.pathname === item.path ? " active" : ""}`}
            onClick={() => navigate(item.path)}
          >
            <span className="nav-icon">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="navbar-actions">
        <NotificationBell />
        <ThemeToggle />
        <button
          className="profile-trigger"
          type="button"
          onClick={toggleProfile}
          aria-label="Open profile settings"
          aria-expanded={profileOpen}
          title="Profile settings"
        >
          {initials}
        </button>
        <button className="sidebar-logout" onClick={handleLogout}>
          <span className="nav-icon"><Icon name="logout" /></span>
          <span>Logout</span>
        </button>
      </div>

      {profileOpen && (
        <div className="profile-popover" role="dialog" aria-label="Profile settings">
          <div className="profile-popover-header">
            <div className="profile-avatar-lg">{initials}</div>
            <div>
              <h3>Profile</h3>
              <p>{roleLabel}</p>
            </div>
            <button className="profile-close" type="button" onClick={() => setProfileOpen(false)} aria-label="Close profile">
              <Icon name="x" size={16} />
            </button>
          </div>

          {profileLoading ? (
            <p className="profile-helper">Loading profile...</p>
          ) : (
            <form onSubmit={handleProfileSave}>
              <div className="profile-form-grid">
                <label>
                  <span>Name</span>
                  <input
                    className="form-input"
                    value={profileForm.name}
                    onChange={(e) => handleProfileChange("name", e.target.value)}
                    required
                  />
                </label>
                <label>
                  <span>Email</span>
                  <input
                    type="email"
                    className="form-input"
                    value={profileForm.email}
                    onChange={(e) => handleProfileChange("email", e.target.value)}
                    required
                  />
                </label>
                {role !== "admin" && (
                  <label>
                    <span>Department</span>
                    <input
                      className="form-input"
                      value={profileForm.department}
                      onChange={(e) => handleProfileChange("department", e.target.value)}
                      placeholder="Not assigned"
                    />
                  </label>
                )}
              </div>

              <div className="profile-password-panel">
                <div>
                  <h4>Password</h4>
                  <p>Fill these only when you want to change it.</p>
                </div>
                <input
                  type="password"
                  className="form-input"
                  placeholder="Current password"
                  value={profileForm.current_password}
                  onChange={(e) => handleProfileChange("current_password", e.target.value)}
                />
                <input
                  type="password"
                  className="form-input"
                  placeholder="New password"
                  value={profileForm.new_password}
                  onChange={(e) => handleProfileChange("new_password", e.target.value)}
                />
                <input
                  type="password"
                  className="form-input"
                  placeholder="Confirm new password"
                  value={profileForm.confirm_password}
                  onChange={(e) => handleProfileChange("confirm_password", e.target.value)}
                />
              </div>

              {profileError && <div className="profile-message error">{profileError}</div>}
              {profileSuccess && <div className="profile-message success">{profileSuccess}</div>}

              <div className="profile-actions">
                <button className="btn btn-ghost btn-sm" type="button" onClick={() => setProfileOpen(false)}>
                  Close
                </button>
                <button className="btn btn-primary btn-sm" type="submit" disabled={profileSaving}>
                  {profileSaving ? "Saving..." : "Save Profile"}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </header>
  );
}

