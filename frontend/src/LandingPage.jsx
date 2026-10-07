import { useNavigate } from "react-router-dom";
import ThemeToggle from "./ThemeToggle";

const logo = `${process.env.PUBLIC_URL}/images/burger.png?v=transparent-20260615`;

export default function LandingPage() {
  const navigate = useNavigate();

  return (
    <main className="landing-page">
      <section className="landing-hero">
        <nav className="landing-nav">
          <div className="landing-brand">
            <span className="landing-brand-icon"><img src={logo} alt="VisionGuard" /></span>
            <div>
              <div className="landing-brand-name">VisionGuard</div>
              <div className="landing-brand-sub">Enterprise safety operations</div>
            </div>
          </div>

          <ThemeToggle className="theme-toggle landing-theme-toggle" />
        </nav>

        <div className="landing-content">
          <div className="landing-copy">
            <span className="landing-eyebrow">AI-powered workplace safety</span>
            <h1>Workplace intelligence for safer teams.</h1>
            <p>
              Monitor sites, investigate incidents, assign corrective actions, and keep workers aligned
              from one secure operations console.
            </p>

            <div className="landing-actions">
              <button className="landing-primary" onClick={() => navigate("/login")}>
                Continue to Login
              </button>
              <span className="landing-note">Built for admins, safety officers, and field teams.</span>
            </div>
          </div>

          <div className="landing-metrics" aria-label="VisionGuard platform highlights">
            <div className="landing-metric">
              <strong>24/7</strong>
              <span>Live safety monitoring</span>
            </div>
            <div className="landing-metric">
              <strong>Live</strong>
              <span>Compliance visibility</span>
            </div>
            <div className="landing-metric">
              <strong>3 roles</strong>
              <span>Admin, officer, worker</span>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
