/* eslint-disable testing-library/no-container, testing-library/no-node-access --
   SVG zone shapes and layout boxes have no accessible roles; these tests
   assert rendered coordinates and element sizes directly. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import RestrictedZoneManager from "./RestrictedZoneManager";
import { api } from "./api";

// react-router-dom v7 is ESM-only for CRA's Jest; the component only needs navigate.
const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }), { virtual: true });
jest.mock("./api", () => ({
  api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() },
  apiErrorMessage: (error, fallback) => error?.response?.data?.detail || fallback,
}));

const camera = { id: 7, name: "Presentation Webcam", location_id: 1 };
const ZONES_PATH = "/admin/cameras/7/restricted-zones";
let savedZones;

beforeEach(() => {
  jest.clearAllMocks();
  savedZones = [
    { id: 1, camera_id: 7, name: "Loading Area", polygon_points: [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4]], enabled: true },
  ];
  global.URL.createObjectURL = jest.fn(() => "blob:camera-frame");
  global.URL.revokeObjectURL = jest.fn();
  window.confirm = jest.fn(() => true);
  api.get.mockImplementation((url) => {
    if (url === "/admin/cameras/7/snapshot") return Promise.resolve({ data: new Blob(["jpeg"], { type: "image/jpeg" }) });
    if (url === ZONES_PATH) return Promise.resolve({ data: savedZones.map((zone) => ({ ...zone })) });
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
  api.post.mockImplementation((url, body) => {
    const zone = { id: 2, camera_id: 7, enabled: true, ...body };
    savedZones.push(zone);
    return Promise.resolve({ data: zone });
  });
  api.patch.mockImplementation((url, body) => {
    const id = Number(url.split("/").pop());
    savedZones = savedZones.map((zone) => (zone.id === id ? { ...zone, ...body } : zone));
    return Promise.resolve({ data: savedZones.find((zone) => zone.id === id) });
  });
  api.delete.mockImplementation((url) => {
    const id = Number(url.split("/").pop());
    savedZones = savedZones.filter((zone) => zone.id !== id);
    return Promise.resolve({ data: { detail: "Restricted zone deleted" } });
  });
});

async function renderReadyEditor() {
  const view = render(
    <RestrictedZoneManager camera={camera} locationName="Block 1" onClose={jest.fn()} />,
  );
  const frame = await screen.findByAltText("Current frame from Presentation Webcam");
  Object.defineProperty(frame, "naturalWidth", { value: 640 });
  Object.defineProperty(frame, "naturalHeight", { value: 480 });
  fireEvent.load(frame);
  const surface = screen.getByTestId("zone-drawing-surface");
  // The drawing surface is displayed at 400x300 at page offset (100, 50).
  surface.getBoundingClientRect = () => ({ left: 100, top: 50, width: 400, height: 300, right: 500, bottom: 350, x: 100, y: 50 });
  within(await screen.findByRole("list")).getByText("Loading Area");
  return { ...view, surface };
}

const clickAt = (surface, clientX, clientY) => fireEvent.click(surface, { clientX, clientY });
const vertices = (container) => container.querySelectorAll(".zone-vertex");
const draftShape = (container) => container.querySelector(".zone-shape--draft");

test("shows the selected camera's current frame with its saved zones", async () => {
  const { container } = await renderReadyEditor();
  expect(screen.getByRole("heading", { name: "Restricted Zones · Presentation Webcam" })).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith("/admin/cameras/7/snapshot", expect.objectContaining({ responseType: "blob" }));
  expect(screen.getByAltText("Current frame from Presentation Webcam")).toHaveAttribute("src", "blob:camera-frame");
  const saved = container.querySelector(".zone-shape--restricted");
  expect(saved.tagName.toLowerCase()).toBe("polygon");
  expect(saved).toHaveAttribute("points", "10,10 40,10 40,40");
});

test("clicks create normalized vertices, close the polygon at 3 points, and support undo/clear", async () => {
  const { container, surface } = await renderReadyEditor();

  clickAt(surface, 300, 200); // center of the displayed frame
  expect(vertices(container)).toHaveLength(1);
  expect(vertices(container)[0]).toHaveStyle({ left: "50%", top: "50%" });

  clickAt(surface, 500, 50); // top-right corner
  expect(draftShape(container).tagName.toLowerCase()).toBe("polyline");
  expect(draftShape(container)).toHaveClass("zone-shape--open");

  clickAt(surface, 100, 350); // bottom-left corner
  expect(vertices(container)).toHaveLength(3);
  expect(draftShape(container).tagName.toLowerCase()).toBe("polygon");
  expect(draftShape(container)).toHaveAttribute("points", "50,50 100,0 0,100");

  fireEvent.click(screen.getByRole("button", { name: "Undo Last Point" }));
  expect(vertices(container)).toHaveLength(2);
  expect(draftShape(container).tagName.toLowerCase()).toBe("polyline");

  fireEvent.click(screen.getByRole("button", { name: "Clear Drawing" }));
  expect(vertices(container)).toHaveLength(0);
  expect(draftShape(container)).toBeNull();
});

test("saves normalized points and reloads the saved zone list", async () => {
  const { surface } = await renderReadyEditor();
  const save = screen.getByRole("button", { name: "Save Zone" });
  expect(save).toBeDisabled();

  clickAt(surface, 320, 140);
  clickAt(surface, 460, 140);
  clickAt(surface, 460, 320);
  expect(save).toBeDisabled(); // name still missing
  fireEvent.change(screen.getByLabelText("Zone Name"), { target: { value: "  Evaluator Test Zone " } });
  expect(save).toBeEnabled();
  fireEvent.click(save);

  await waitFor(() => expect(api.post).toHaveBeenCalledWith(ZONES_PATH, {
    name: "Evaluator Test Zone",
    polygon_points: [[0.55, 0.3], [0.9, 0.3], [0.9, 0.9]],
  }));
  expect(await screen.findByText('Zone "Evaluator Test Zone" saved.')).toBeInTheDocument();
  const list = screen.getByRole("list");
  expect(within(list).getByText("Evaluator Test Zone")).toBeInTheDocument();
  expect(api.get.mock.calls.filter(([url]) => url === ZONES_PATH)).toHaveLength(2);
  expect(screen.getByLabelText("Zone Name")).toHaveValue("");
});

test("edits an existing zone's name and polygon", async () => {
  const { container, surface } = await renderReadyEditor();
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText("Zone Name")).toHaveValue("Loading Area");
  expect(vertices(container)).toHaveLength(3);
  clickAt(surface, 100, 350);
  fireEvent.click(screen.getByRole("button", { name: "Update Zone" }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith(`${ZONES_PATH}/1`, {
    name: "Loading Area",
    polygon_points: [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0, 1]],
  }));
});

test("enables, disables, and deletes saved zones", async () => {
  await renderReadyEditor();
  fireEvent.click(screen.getByRole("button", { name: "Disable" }));
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith(`${ZONES_PATH}/1`, { enabled: false }));
  expect(await screen.findByText("Disabled")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Enable" }));
  await waitFor(() => expect(api.patch).toHaveBeenLastCalledWith(`${ZONES_PATH}/1`, { enabled: true }));
  expect(await screen.findByText("Enabled")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Delete/ }));
  expect(window.confirm).toHaveBeenCalled();
  await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${ZONES_PATH}/1`));
  expect(await screen.findByText(/No restricted zones for this camera/)).toBeInTheDocument();
});

test("shows the server's reason when the camera frame cannot be captured", async () => {
  api.get.mockImplementation((url) => {
    if (url === ZONES_PATH) return Promise.resolve({ data: [] });
    return Promise.reject({
      response: { status: 503, data: { text: () => Promise.resolve(JSON.stringify({ detail: "Camera source is unavailable" })) } },
    });
  });
  render(
    <RestrictedZoneManager camera={camera} onClose={jest.fn()} />,
  );
  expect(await screen.findByText("Camera source is unavailable")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
