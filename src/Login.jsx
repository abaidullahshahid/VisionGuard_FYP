import { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import ThemeToggle from "./ThemeToggle";

const logo = `${process.env.PUBLIC_URL}/images/burger.png?v=transparent-20260615`;

export default function Login() {
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [loading, setLoading]   = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const response = await axios.post("http://127.0.0.1:8001/auth/login", { email: email.trim().toLowerCase(), password });
      const { token, role, name } = response.data;
      sessionStorage.setItem("token", token);
      sessionStorage.setItem("role", role);
      sessionStorage.setItem("name", name || "");
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

  return (
    <div className="login-page">
      <ThemeToggle className="theme-toggle auth-theme-toggle" />
      <div className="login-container">
        <div className="login-header">
          <span className="login-brand-icon"><img src={logo} alt="VisionGuard" /></span>
          <h1 className="login-brand-title">Welcome Back!</h1>
          <p className="login-brand-sub">Enter your details below to sign in to your VisionGuard account.</p>
        </div>

        <form onSubmit={handleLogin}>
          <div className="login-input-group">
            <label className="login-input-label">Email Address</label>
            <div className="login-input-wrap">
              <span className="login-input-icon">@</span>
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
              <span className="login-input-icon">*</span>
              <input
                type={showPassword ? "text" : "password"}
                className="login-input"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="login-password-toggle"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </div>
          </div>

          <div className="login-helper-row">
            <button type="button" className="login-link" onClick={() => navigate("/forgot-password")}>
              Forgot Password?
            </button>
          </div>

          {error && <div className="alert alert-error">{error}</div>}

          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>

      </div>
    </div>
  );
}

