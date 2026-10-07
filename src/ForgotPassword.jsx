import { useEffect, useState } from "react";
import axios from "axios";
import { API_BASE } from "./api";
import { useNavigate } from "react-router-dom";
import ThemeToggle from "./ThemeToggle";

const logo = `${process.env.PUBLIC_URL}/images/burger.png?v=transparent-20260615`;
const RESEND_SECONDS = 60;

// Steps: "email" -> "code" -> "password" -> "done".  A link from the email
// (/reset-password?token=...) starts at "password".  When Gmail is not set
// up, the request goes to an administrator instead ("admin").
export default function ForgotPassword() {
  const navigate = useNavigate();
  const token = new URLSearchParams(window.location.search).get("token") || "";
  const [step, setStep] = useState(token ? "checking" : "email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const [resendIn, setResendIn] = useState(0);

  const errorText = (err, fallback) => err.response?.data?.detail || (err.response ? fallback : "Cannot reach the VisionGuard server.");

  useEffect(() => {
    if (!token) return;
    axios.post(`${API_BASE}/auth/reset-password/check`, { token })
      .then(() => setStep("password"))
      .catch((err) => { setError(errorText(err, "This reset link is invalid or has expired.")); setStep("email"); });
  }, [token]);

  useEffect(() => {
    if (resendIn <= 0) return undefined;
    const timer = window.setTimeout(() => setResendIn((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [resendIn]);

  const requestCode = async (event) => {
    event?.preventDefault();
    setError("");
    setInfo("");
    setLoading(true);
    try {
      const response = await axios.post(`${API_BASE}/auth/forgot-password`, { email });
      setInfo(response.data.message);
      if (response.data.email_enabled) {
        setStep("code");
        setResendIn(RESEND_SECONDS);
      } else {
        setStep("admin");
      }
    } catch (err) {
      setError(errorText(err, "Unable to send the code. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const verifyCode = async (event) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await axios.post(`${API_BASE}/auth/reset-password/check`, { email, code });
      setInfo("");
      setStep("password");
    } catch (err) {
      setError(errorText(err, "The code is not valid."));
    } finally {
      setLoading(false);
    }
  };

  const savePassword = async (event) => {
    event.preventDefault();
    setError("");
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);
    try {
      const proof = token ? { token } : { email, code };
      const response = await axios.post(`${API_BASE}/auth/reset-password`, {
        ...proof,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      setInfo(response.data.message);
      setStep("done");
    } catch (err) {
      setError(errorText(err, "Unable to change the password."));
    } finally {
      setLoading(false);
    }
  };

  const subtitle = {
    checking: "Checking your reset link...",
    email: "Enter your account email and we will send you a 6-digit verification code.",
    code: `Enter the 6-digit code we sent to ${email}.`,
    password: "Choose a new password for your account.",
    done: "Your password has been changed.",
    admin: "Your request has been sent.",
  }[step];

  return (
    <div className="login-page auth-reset-page">
      <ThemeToggle className="theme-toggle auth-theme-toggle" />
      <div className="login-container reset-container">
        <div className="login-header">
          <span className="login-brand-icon"><img src={logo} alt="VisionGuard" /></span>
          <h1 className="login-brand-title">Reset Password</h1>
          <p className="login-brand-sub">{subtitle}</p>
        </div>

        {step === "email" && (
          <form onSubmit={requestCode}>
            <div className="login-input-group">
              <label className="login-input-label" htmlFor="reset-email">Email Address</label>
              <div className="login-input-wrap">
                <span className="login-input-icon">@</span>
                <input id="reset-email" type="email" className="login-input" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
              </div>
            </div>
            {error && <div className="alert alert-error">{error}</div>}
            <button type="submit" className="login-btn" disabled={loading}>{loading ? "Sending..." : "Send Verification Code"}</button>
          </form>
        )}

        {step === "code" && (
          <form onSubmit={verifyCode}>
            {info && <div className="alert alert-success">{info}</div>}
            <div className="login-input-group">
              <label className="login-input-label" htmlFor="reset-code">Verification Code</label>
              <div className="login-input-wrap">
                <span className="login-input-icon">#</span>
                <input
                  id="reset-code"
                  className="login-input reset-code-input"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="000000"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  required
                  autoFocus
                />
              </div>
            </div>
            {error && <div className="alert alert-error">{error}</div>}
            <button type="submit" className="login-btn" disabled={loading || code.length !== 6}>{loading ? "Checking..." : "Verify Code"}</button>
            <div className="auth-secondary-action">
              <button type="button" className="login-link" disabled={resendIn > 0 || loading} onClick={() => requestCode()}>
                {resendIn > 0 ? `Resend code in ${resendIn}s` : "Resend code"}
              </button>
              <button type="button" className="login-link" onClick={() => { setStep("email"); setCode(""); setError(""); setInfo(""); }}>
                Use a different email
              </button>
            </div>
          </form>
        )}

        {step === "password" && (
          <form onSubmit={savePassword}>
            <div className="login-input-group">
              <label className="login-input-label" htmlFor="reset-new">New Password</label>
              <div className="login-input-wrap">
                <span className="login-input-icon">*</span>
                <input id="reset-new" type="password" className="login-input" placeholder="At least 6 characters" minLength={6} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required autoFocus />
              </div>
            </div>
            <div className="login-input-group">
              <label className="login-input-label" htmlFor="reset-confirm">Confirm Password</label>
              <div className="login-input-wrap">
                <span className="login-input-icon">*</span>
                <input id="reset-confirm" type="password" className="login-input" placeholder="Type it again" minLength={6} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required />
              </div>
            </div>
            {error && <div className="alert alert-error">{error}</div>}
            <button type="submit" className="login-btn" disabled={loading}>{loading ? "Saving..." : "Save New Password"}</button>
          </form>
        )}

        {(step === "done" || step === "admin") && (
          <>
            <div className="alert alert-success">{info}</div>
            <button type="button" className="login-btn" onClick={() => navigate("/login")}>Go to Login</button>
          </>
        )}

        {step === "checking" && <p className="loading-text">Please wait...</p>}

        {step !== "done" && step !== "admin" && (
          <div className="auth-secondary-action">
            <button type="button" className="login-link" onClick={() => navigate("/login")}>
              Back to Login
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
