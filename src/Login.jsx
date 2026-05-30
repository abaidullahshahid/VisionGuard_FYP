import { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";

export default function Login() {
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [loading, setLoading]   = useState(false);
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const response = await axios.post("http://localhost:8000/auth/login", { email, password });
      const { token, role } = response.data;
      localStorage.setItem("token", token);
      localStorage.setItem("role", role);
      if      (role === "admin")   navigate("/admin");
      else if (role === "officer") navigate("/officer");
      else if (role === "worker")  navigate("/worker");
      else setError("Unknown role. Contact admin.");
    } catch {
      setError("Invalid email or password. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const demoLogin = (role) => {
    localStorage.setItem("token", "demo");
    localStorage.setItem("role", role);
    if      (role === "admin")   navigate("/admin");
    else if (role === "officer") navigate("/officer");
    else                         navigate("/worker");
  };

  return (
    <div className="login-page">
      <div className="login-container">

        <div className="login-header">
          <span className="login-brand-icon">👁️</span>
          <h1 className="login-brand-title">VisionGuard</h1>
          <p className="login-brand-sub">Smart Workplace Safety Management System</p>
        </div>

        <form onSubmit={handleLogin}>
          <div className="login-input-group">
            <label className="login-input-label">Email Address</label>
            <div className="login-input-wrap">
              <span className="login-input-icon">✉️</span>
              <input
                type="email"
                className="login-input"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="login-input-group">
            <label className="login-input-label">Password</label>
            <div className="login-input-wrap">
              <span className="login-input-icon">🔒</span>
              <input
                type="password"
                className="login-input"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </div>

          {error && <div className="alert alert-error">{error}</div>}

          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? "Signing in…" : "Sign In →"}
          </button>
        </form>

        {/* Demo Access */}
        <div style={{
          marginTop: "28px",
          paddingTop: "24px",
          borderTop: "1px solid rgba(255,255,255,0.08)",
        }}>
          <p style={{
            fontSize: "11px", color: "var(--text3)", textAlign: "center",
            marginBottom: "14px", textTransform: "uppercase", letterSpacing: "1px", fontWeight: "700"
          }}>
            Quick Demo Access
          </p>
          <div style={{ display: "flex", gap: "10px", justifyContent: "center" }}>
            {["admin","officer","worker"].map(r => (
              <button key={r} className="btn btn-ghost btn-sm"
                onClick={() => demoLogin(r)}
                style={{textTransform:"capitalize", flex: 1}}>
                {r}
              </button>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}