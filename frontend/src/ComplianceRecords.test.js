import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import ComplianceRecords from "./ComplianceRecords";
import AlertSettings from "./AlertSettings";
import { api } from "./api";

const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }), { virtual: true });
jest.mock("./Sidebar", () => () => <nav />);
jest.mock("./NotificationBell", () => ({ useNotificationRefresh: () => {} }));
jest.mock("./api", () => ({
  api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), put: jest.fn() },
  apiErrorMessage: (error, fallback) => error?.response?.data?.detail || fallback,
}));

const record = {
  id: 4,
  location_id: 3,
  location: "Warehouse",
  record_date: "2026-10-07",
  violations: 8,
  ppe_violations: 3,
  restricted_violations: 5,
  open_incidents: 8,
  actions_total: 1,
  actions_resolved: 0,
  cameras: 1,
  status: "pending",
  auto_status: "pending",
  status_source: "auto",
  summary: "3 PPE violations; 5 restricted-area entries.",
  notes: null,
  officer: null,
};
const stats = { compliant: 1, nonCompliant: 0, pending: 1, total: 2, totalViolations: 8, complianceRate: 50 };

function mockCompliance(records = [record]) {
  api.get.mockImplementation((url) => {
    if (url === "/officer/compliance-records") return Promise.resolve({ data: records });
    if (url === "/officer/compliance-stats") return Promise.resolve({ data: stats });
    if (url === "/officer/locations") return Promise.resolve({ data: [{ id: 3, name: "Warehouse" }] });
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  sessionStorage.setItem("token", "test");
});

afterEach(() => sessionStorage.clear());

test("shows records with the compliance rate and filters on the server", async () => {
  mockCompliance();
  render(<ComplianceRecords />);
  expect(await screen.findByText("3 PPE violations; 5 restricted-area entries.")).toBeInTheDocument();
  expect(screen.getByText("50%")).toBeInTheDocument();
  expect(screen.getByText("3 PPE · 5 restricted")).toBeInTheDocument();
  expect(screen.getByText("0/1 resolved")).toBeInTheDocument();

  await waitFor(() => expect(api.get).toHaveBeenCalledWith("/officer/locations"));
  fireEvent.click(screen.getByLabelText("Location"));
  fireEvent.click(await screen.findByRole("option", { name: "Warehouse" }));
  fireEvent.click(screen.getByLabelText("Status"));
  fireEvent.click(screen.getByRole("option", { name: "Pending" }));
  await waitFor(() => expect(api.get).toHaveBeenCalledWith("/officer/compliance-records", { params: { status: "pending", location_id: "3" } }));
});

test("generates records and saves an officer review", async () => {
  mockCompliance();
  api.post.mockResolvedValue({ data: { detail: "3 record(s) updated for 2026-10-07." } });
  api.patch.mockResolvedValue({ data: {} });
  render(<ComplianceRecords />);
  await screen.findByText("Warehouse", { selector: "td" });

  fireEvent.click(screen.getByRole("button", { name: /Generate Records/ }));
  expect(await screen.findByText("3 record(s) updated for 2026-10-07.")).toBeInTheDocument();
  expect(api.post.mock.calls[0][0]).toBe("/officer/compliance-records/generate");

  fireEvent.click(screen.getByRole("button", { name: "Review" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByLabelText("Status"));
  fireEvent.click(within(dialog).getByRole("option", { name: "Non-compliant" }));
  fireEvent.change(within(dialog).getByLabelText("Officer remarks"), { target: { value: "Team briefed." } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save Review" }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith("/officer/compliance-records/4", { status: "non-compliant", notes: "Team briefed." }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

test("empty state explains how to create records", async () => {
  mockCompliance([]);
  render(<ComplianceRecords />);
  expect(await screen.findByText(/Click Generate Records/)).toBeInTheDocument();
});

const overview = {
  settings: {
    email_enabled: false, min_severity: "HIGH", email_officers: true, email_admins: false, email_workers: false,
    extra_recipients: "", cooldown_minutes: 5, attach_snapshot: true, camera_alerts: true, daily_summary: false,
    daily_summary_hour: 18, last_summary_date: null, updated_at: null,
  },
  email_configured: true,
  sender: "alerts@gmail.com",
  recipients: { officers: ["officer@site.com"], admins: ["admin@site.com"], extra: [], assigned_workers: 2, staff: ["officer@site.com"] },
  log: [{ id: 1, kind: "incident", subject: "[VisionGuard] HIGH: PPE violation at Site", recipients: ["officer@site.com"], status: "sent", detail: null, created_at: "2026-10-07T10:00:00Z" }],
};

test("admin turns email alerts on and sends a test email", async () => {
  api.get.mockResolvedValue({ data: overview });
  api.put.mockResolvedValue({ data: { ...overview, settings: { ...overview.settings, email_enabled: true } } });
  api.post.mockResolvedValue({ data: { detail: "Sent to officer@site.com." } });
  render(<AlertSettings />);
  expect(await screen.findByText("Email alerts are OFF")).toBeInTheDocument();
  expect(screen.getByText("[VisionGuard] HIGH: PPE violation at Site")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save Settings" })).toBeDisabled();

  fireEvent.click(screen.getByLabelText("Send email alerts"));
  expect(screen.getByRole("button", { name: "Send Test Email" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Save Settings" }));
  await waitFor(() => expect(api.put).toHaveBeenCalledWith("/admin/alert-settings", expect.objectContaining({ email_enabled: true, min_severity: "HIGH", cooldown_minutes: 5 })));
  expect(await screen.findByText("Email alerts are ON")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Send Test Email" }));
  expect(await screen.findByText("Sent to officer@site.com.")).toBeInTheDocument();
  expect(api.post).toHaveBeenCalledWith("/admin/alert-settings/test");
});
