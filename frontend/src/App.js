import { BrowserRouter, Routes, Route } from "react-router-dom";
import LandingPage          from "./LandingPage";
import Login                from "./Login";
import ForgotPassword       from "./ForgotPassword";
import AdminDashboard       from "./AdminDashboard";
import ManageUsers          from "./ManageUsers";
import ManageLocations      from "./ManageLocations";
import ManageCameras        from "./ManageCameras";
import ConfigureSafetyRules from "./ConfigureSafetyRules";
import AlertSettings        from "./AlertSettings";
import OfficerDashboard     from "./OfficerDashboard";
import ViewIncidents        from "./ViewIncidents";
import CorrectiveActions    from "./CorrectiveActions";
import LiveVideoFeed        from "./LiveVideoFeed";
import OfficerInstructions  from "./OfficerInstructions";
import WorkerTasks          from "./WorkerTasks";
import ComplianceRecords    from "./ComplianceRecords";
import WorkerDashboard      from "./WorkerDashboard";
import WorkerLocations      from "./WorkerLocations";
import SafetyInstructions   from "./SafetyInstructions";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Auth */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ForgotPassword />} />

        {/* Admin Routes */}
        <Route path="/admin"           element={<AdminDashboard />} />
        <Route path="/admin/users"     element={<ManageUsers />} />
        <Route path="/admin/locations" element={<ManageLocations />} />
        <Route path="/admin/cameras"   element={<ManageCameras />} />
        <Route path="/admin/rules"     element={<ConfigureSafetyRules />} />
        <Route path="/admin/alerts"    element={<AlertSettings />} />

        {/* Officer Routes */}
        <Route path="/officer"         element={<OfficerDashboard />} />
        <Route path="/officer/incidents"  element={<ViewIncidents />} />
        <Route path="/officer/actions"    element={<CorrectiveActions />} />
        <Route path="/officer/live"       element={<LiveVideoFeed />} />
        <Route path="/officer/compliance" element={<ComplianceRecords />} />
        <Route path="/officer/instructions" element={<OfficerInstructions />} />

        {/* Worker Routes */}
        <Route path="/worker"           element={<WorkerDashboard />} />
        <Route path="/worker/locations" element={<WorkerLocations />} />
        <Route path="/worker/instructions" element={<SafetyInstructions />} />
        <Route path="/worker/tasks"     element={<WorkerTasks />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
