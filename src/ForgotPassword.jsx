import { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import ThemeToggle from "./ThemeToggle";

const logo = `${process.env.PUBLIC_URL}/images/burger.png?v=transparent-20260615`;

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleReset = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);

    try {
      const response = await axios.post("http://127.0.0.1:8001/auth/reset-password", {
        email,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      setSuccess(response.data.message || "Password updated successfully.");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setError(err.response?.data?.detail || "Unable to update password. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page auth-reset-page">
      <ThemeToggle className="theme-toggle auth-theme-toggle" />
      <div className="login-container reset-container">
        <div className="login-header">
          <span className="login-brand-icon"><img src={logo} alt="VisionGuard" /></span>
          <h1 className="login-brand-title">Reset Password</h1>
          <p className="login-brand-sub">Enter your account email and choose a new password.</p>
        </div>

        <form onSubmit={handleReset}>
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
            <label className="login-input-label">New Password</label>
            <div className="login-input-wrap">
              <span className="login-input-icon">*</span>
              <input
                type="password"
                className="login-input"
                placeholder="Create a new password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="login-input-group">
            <label className="login-input-label">Confirm Password</label>
            <div className="login-input-wrap">
              <span className="login-input-icon">*</span>
              <input
                type="password"
                className="login-input"
                placeholder="Confirm your new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </div>
          </div>

          {error && <div className="alert alert-error">{error}</div>}
          {success && <div className="alert alert-success">{success}</div>}

          <button type="submit" className="login-btn" disabled={loading}>
            {loading ? "Updating..." : "Update Password"}
          </button>
        </form>

        <div className="auth-secondary-action">
          <button type="button" className="login-link" onClick={() => navigate("/login")}>
            Back to Login
          </button>
        </div>
      </div>
    </div>
  );
}

