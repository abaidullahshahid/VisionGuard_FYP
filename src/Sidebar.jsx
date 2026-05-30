import { useNavigate, useLocation } from "react-router-dom";

export default function Sidebar({ menuItems, role }) {
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = () => {
    localStorage.clear();
    navigate("/");
  };

  const roleLabel = {
    admin:   "Administrator",
    officer: "Safety Officer",
    worker:  "Field Worker",
  }[role] || role;

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <span className="sidebar-logo-icon">👁️</span>
        <div>
          <div className="sidebar-logo-text">VisionGuard</div>
          <div className="sidebar-logo-sub">{roleLabel}</div>
        </div>
      </div>

      <div className="sidebar-section-label">Navigation</div>

      <nav style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
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

      <button className="sidebar-logout" onClick={handleLogout}>
        <span className="nav-icon">🚪</span>
        <span>Logout</span>
      </button>
    </aside>
  );
}
