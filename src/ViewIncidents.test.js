import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ViewIncidents from "./ViewIncidents";
import { api } from "./api";

const mockNavigate = jest.fn();
const mockLocation = { search: "" };
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate, useLocation: () => mockLocation }), { virtual: true });
jest.mock("./Sidebar", () => () => <nav />);
jest.mock("./NotificationBell", () => ({ useNotificationRefresh: () => {} }));
jest.mock("./api", () => ({
  api: { get: jest.fn(), post: jest.fn(), delete: jest.fn(), patch: jest.fn() },
  apiErrorMessage: (error, fallback) => error?.response?.data?.detail || fallback,
  apiUrl: (value) => value || "",
}));

const incident = (id, severity = "HIGH") => ({
  id,
  incident_id: `uuid-${id}-0000`,
  violation_type: "PPE_VIOLATION",
  incident_type: "PPE_VIOLATION",
  severity_level: severity,
  severity,
  status: "open",
  missing_items: ["helmet"],
  location: "PPE Area",
  camera_id: 1,
  detected_at: "2026-10-07T10:00:00Z",
});

let listed;

beforeEach(() => {
  sessionStorage.setItem("token", "officer-test");
  listed = [incident(7), incident(8, "LOW")];
  api.get.mockImplementation((url, options) => {
    if (url === "/officer/cameras") return Promise.resolve({ data: [{ id: 1, name: "Webcam" }] });
    if (url === "/officer/incidents") {
      const severity = options?.params?.severity;
      return Promise.resolve({ data: severity ? listed.filter((item) => item.severity === severity) : listed });
    }
    return Promise.resolve({ data: {} });
  });
});

afterEach(() => sessionStorage.clear());

test("deletes one incident after confirming", async () => {
  const confirm = jest.spyOn(window, "confirm").mockReturnValue(true);
  api.delete.mockImplementation(() => {
    listed = listed.filter((item) => item.id !== 7);
    return Promise.resolve({ data: { detail: "Incident #7 was deleted with its corrective actions and snapshot." } });
  });
  render(<ViewIncidents />);
  fireEvent.click(await screen.findByRole("button", { name: "Delete incident #7" }));
  expect(confirm.mock.calls[0][0]).toMatch(/This cannot be undone/);
  expect(api.delete).toHaveBeenCalledWith("/officer/incidents/7");
  expect(await screen.findByText(/Incident #7 was deleted/)).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("button", { name: "Delete incident #7" })).not.toBeInTheDocument());
  confirm.mockRestore();
});

test("Delete All removes everything; with filters only the shown incidents", async () => {
  const confirm = jest.spyOn(window, "confirm").mockReturnValue(true);
  api.post.mockResolvedValue({ data: { detail: "Deleted 1 incident with their corrective actions and snapshots." } });
  render(<ViewIncidents />);
  await screen.findByRole("button", { name: "Delete incident #8" });

  fireEvent.click(screen.getByLabelText("Severity"));
  fireEvent.click(screen.getByRole("option", { name: "Low" }));
  fireEvent.click(await screen.findByRole("button", { name: /Delete 1 Shown/ }));
  expect(confirm.mock.calls[0][0]).toMatch(/shown by the current filters/);
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/officer/incidents/delete", { ids: [8] }));

  fireEvent.click(screen.getByRole("button", { name: /Clear Filters/ }));
  fireEvent.click(await screen.findByRole("button", { name: /Delete All/ }));
  expect(confirm.mock.calls[1][0]).toMatch(/Delete ALL 2 incidents/);
  await waitFor(() => expect(api.post).toHaveBeenLastCalledWith("/officer/incidents/delete", { all: true }));
  confirm.mockRestore();
});

test("nothing is deleted when the confirmation is cancelled", async () => {
  const confirm = jest.spyOn(window, "confirm").mockReturnValue(false);
  render(<ViewIncidents />);
  fireEvent.click(await screen.findByRole("button", { name: /Delete All/ }));
  fireEvent.click(screen.getByRole("button", { name: "Delete incident #7" }));
  expect(api.post).not.toHaveBeenCalled();
  expect(api.delete).not.toHaveBeenCalled();
  confirm.mockRestore();
});
