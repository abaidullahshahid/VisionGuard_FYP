import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import ManageCameras from "./ManageCameras";
import { api } from "./api";

// react-router-dom v7 is ESM-only for CRA's Jest; the component only needs navigate.
const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }), { virtual: true });
jest.mock("./api", () => ({
  api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() },
  apiErrorMessage: (error, fallback) => error?.response?.data?.detail || fallback,
}));
jest.mock("./Sidebar", () => () => null);

beforeEach(() => {
  jest.clearAllMocks();
  sessionStorage.setItem("token", "admin-test");
  global.URL.createObjectURL = jest.fn(() => "blob:frame");
  global.URL.revokeObjectURL = jest.fn();
  api.get.mockImplementation((url) => {
    if (url === "/admin/cameras") {
      return Promise.resolve({ data: [
        { id: 1, name: "Factory Floor", type: "RTSP", stream_url: "rtsp://cam/1", location_id: 1, status: "active" },
        { id: 2, name: "Presentation Webcam", type: "WEBCAM", stream_url: "0", location_id: 1, status: "active" },
      ] });
    }
    if (url === "/admin/locations") return Promise.resolve({ data: [{ id: 1, name: "construction block 1" }] });
    if (url.endsWith("/restricted-zones")) return Promise.resolve({ data: [] });
    if (url.endsWith("/snapshot")) return Promise.resolve({ data: new Blob(["jpeg"]) });
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
});

afterEach(() => sessionStorage.clear());

test("each camera row offers Edit, Configure Zones, and Delete", async () => {
  render(<ManageCameras />);
  const row = await screen.findByRole("row", { name: /Factory Floor/ });
  for (const name of ["Edit", "Configure Zones", /Delete/]) {
    expect(within(row).getByRole("button", { name })).toBeInTheDocument();
  }
});

test("Configure Zones opens the zone manager for that camera", async () => {
  render(<ManageCameras />);
  const row = await screen.findByRole("row", { name: /Presentation Webcam/ });
  fireEvent.click(within(row).getByRole("button", { name: "Configure Zones" }));

  expect(await screen.findByRole("heading", { name: "Restricted Zones · Presentation Webcam" })).toBeInTheDocument();
  await waitFor(() => expect(api.get).toHaveBeenCalledWith("/admin/cameras/2/snapshot", expect.objectContaining({ responseType: "blob" })));
  expect(api.get).toHaveBeenCalledWith("/admin/cameras/2/restricted-zones");
  expect(api.get).not.toHaveBeenCalledWith("/admin/cameras/1/snapshot", expect.anything());
  expect(await screen.findByAltText("Current frame from Presentation Webcam")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Close/ }));
  expect(screen.queryByRole("heading", { name: /Restricted Zones/ })).not.toBeInTheDocument();
});
