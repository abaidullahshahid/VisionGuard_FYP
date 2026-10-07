import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import NotificationBell from "./NotificationBell";
import { api } from "./api";

const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }), { virtual: true });
jest.mock("./api", () => ({ api: { get: jest.fn(), post: jest.fn(() => Promise.resolve({})) } }));

const incident = {
  id: 7,
  kind: "incident",
  title: "PPE violation at Site A",
  message: "Missing gloves — Gate Cam",
  severity: "HIGH",
  link: "/officer/incidents?incident=12",
  read: false,
  created_at: new Date().toISOString(),
};

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  api.post.mockResolvedValue({});
  sessionStorage.setItem("token", "officer-test");
});

afterEach(() => {
  jest.useRealTimers();
  sessionStorage.clear();
});

test("shows the unread count and opens an alert's page when clicked", async () => {
  api.get.mockResolvedValue({ data: { unread: 1, latest_id: 7, items: [incident] } });
  render(<NotificationBell />);
  const bell = await screen.findByRole("button", { name: "Notifications, 1 unread" });

  fireEvent.click(bell);
  fireEvent.click(screen.getByText("PPE violation at Site A"));
  expect(api.post).toHaveBeenCalledWith("/notifications/7/read");
  expect(mockNavigate).toHaveBeenCalledWith("/officer/incidents?incident=12");
  expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();
});

test("pops up a toast only for alerts that arrive after the page opened", async () => {
  api.get.mockResolvedValueOnce({ data: { unread: 1, latest_id: 7, items: [incident] } });
  render(<NotificationBell />);
  await screen.findByRole("button", { name: "Notifications, 1 unread" });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();

  const fresh = { ...incident, id: 8, title: "Restricted zone violation at Store", severity: "CRITICAL", link: "/officer/incidents?incident=13" };
  api.get.mockResolvedValue({ data: { unread: 2, latest_id: 8, items: [fresh, incident] } });
  await act(async () => { jest.advanceTimersByTime(5000); });
  const toast = await screen.findByRole("alert");
  expect(toast).toHaveTextContent("Restricted zone violation at Store");

  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
});

test("mark all as read clears the badge", async () => {
  api.get.mockResolvedValue({ data: { unread: 1, latest_id: 7, items: [incident] } });
  render(<NotificationBell />);
  fireEvent.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
  fireEvent.click(screen.getByRole("button", { name: "Mark all as read" }));
  expect(api.post).toHaveBeenCalledWith("/notifications/read-all");
  expect(await screen.findByRole("button", { name: "Notifications" })).toBeInTheDocument();
});
