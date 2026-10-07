/* eslint-disable testing-library/no-container, testing-library/no-node-access --
   SVG zone shapes and layout boxes have no accessible roles; these tests
   assert rendered coordinates and element sizes directly. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import LiveVideoFeed from "./LiveVideoFeed";
import { api } from "./api";

// react-router-dom v7 is ESM-only for CRA's Jest; the component only needs navigate.
const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }), { virtual: true });
jest.mock("./api", () => ({
  api: { get: jest.fn() },
  apiErrorMessage: (error, fallback) => error?.response?.data?.detail || fallback,
  apiUrl: (value) => value,
}));
jest.mock("./Sidebar", () => () => null);

const ZONE = { id: 5, camera_id: 1, name: "Evaluator Test Zone", enabled: true, polygon_points: [[0.55, 0.3], [0.9, 0.3], [0.9, 0.9], [0.55, 0.9]] };

beforeEach(() => {
  jest.clearAllMocks();
  sessionStorage.setItem("token", "officer-test");
  api.get.mockImplementation((url) => {
    const responses = {
      "/officer/cameras": [
        { id: 1, name: "Presentation Webcam", location_id: 1, status: "active" },
        { id: 2, name: "Gate Camera", location_id: 1, status: "active" },
      ],
      "/officer/locations": [{ id: 1, name: "construction block 1" }],
      "/officer/alerts": [],
      "/officer/cameras/1/stream-url": { stream_url: "http://stream.test/1" },
      "/officer/cameras/2/stream-url": { stream_url: "http://stream.test/2" },
      "/officer/cameras/1/restricted-zones": [ZONE],
      "/officer/cameras/2/restricted-zones": [],
    };
    return url in responses ? Promise.resolve({ data: responses[url] }) : Promise.reject(new Error(`Unexpected GET ${url}`));
  });
});

afterEach(() => sessionStorage.clear());

function setBoxSize(element, width, height) {
  Object.defineProperty(element, "clientWidth", { configurable: true, value: width });
  Object.defineProperty(element, "clientHeight", { configurable: true, value: height });
}

async function startStream(cameraId, name, natural) {
  fireEvent.click(screen.getByLabelText("Camera"));
  fireEvent.click(screen.getByRole("option", { name: (text) => text.startsWith(`${name} |`) }));
  const image = await screen.findByAltText(`Live feed from ${name}`);
  Object.defineProperty(image, "naturalWidth", { configurable: true, value: natural[0] });
  Object.defineProperty(image, "naturalHeight", { configurable: true, value: natural[1] });
  fireEvent.load(image);
}

test("overlays the selected camera's enabled zones aligned to the painted video", async () => {
  const { container } = render(<LiveVideoFeed />);
  expect(await screen.findByText("Select a camera to start live monitoring")).toBeInTheDocument();
  expect(api.get).not.toHaveBeenCalledWith(expect.stringMatching(/stream-url|restricted-zones/));

  // Simulate a stage whose box is wider than a 4:3 webcam picture.
  setBoxSize(container.querySelector(".video-stage"), 1600, 900);
  await startStream(1, "Presentation Webcam", [640, 480]);

  const overlay = await screen.findByTestId("restricted-zone-overlay");
  expect(api.get).toHaveBeenCalledWith("/officer/cameras/1/restricted-zones");
  // Pillarboxed 4:3 content: 1200x900 starting 200px from the left.
  expect(overlay).toHaveStyle({ left: "200px", top: "0px", width: "1200px", height: "900px" });
  expect(overlay.querySelector("polygon")).toHaveAttribute("points", "55,30 90,30 90,90 55,90");
  expect(screen.getByText("RESTRICTED · Evaluator Test Zone")).toBeInTheDocument();

  // Responsive: re-measures on resize, still aligned with the content.
  setBoxSize(container.querySelector(".video-stage"), 800, 600);
  fireEvent(window, new Event("resize"));
  await waitFor(() => expect(overlay).toHaveStyle({ left: "0px", top: "0px", width: "800px", height: "600px" }));
  setBoxSize(container.querySelector(".video-stage"), 1000, 900);
  fireEvent(window, new Event("resize"));
  await waitFor(() => expect(overlay).toHaveStyle({ left: "0px", top: "75px", width: "1000px", height: "750px" }));
});

test("a camera with no zones shows no overlay", async () => {
  const { container } = render(<LiveVideoFeed />);
  await screen.findByText("Select a camera to start live monitoring");
  setBoxSize(container.querySelector(".video-stage"), 1280, 720);

  await startStream(1, "Presentation Webcam", [1280, 720]);
  expect(await screen.findByTestId("restricted-zone-overlay")).toBeInTheDocument();

  await startStream(2, "Gate Camera", [1280, 720]);
  await waitFor(() => expect(api.get).toHaveBeenCalledWith("/officer/cameras/2/restricted-zones"));
  await waitFor(() => expect(screen.queryByTestId("restricted-zone-overlay")).not.toBeInTheDocument());
  expect(container.querySelector(".zone-shape")).toBeNull();
});

test("shows live AI detections and a violation banner for the watched camera", async () => {
  const status = {
    state: "running",
    fps: 7.5,
    video_fps: 29.5,
    required_ppe: ["gloves", "helmet", "vest"],
    restricted_location: false,
    zones: [],
    people: [
      { track_id: 3, state: "violation", missing: ["gloves"], checking: [], restricted_zones: [], entering_zones: [], wearing: { helmet: true, vest: true, gloves: false } },
      { track_id: 4, state: "ok", missing: [], checking: [], restricted_zones: [], entering_zones: [], wearing: { helmet: true, vest: true, gloves: true } },
    ],
    recent_events: [{ time: "2026-10-05T10:00:00Z", type: "PPE_VIOLATION", track_id: 3, missing_items: ["gloves"], zone_name: null }],
    events_total: 1,
  };
  const baseGet = api.get.getMockImplementation();
  api.get.mockImplementation((url) => (url === "/officer/cameras/1/ai-status" ? Promise.resolve({ data: { ...status } }) : baseGet(url)));

  render(<LiveVideoFeed />);
  await screen.findByText("Select a camera to start live monitoring");
  expect(api.get).not.toHaveBeenCalledWith("/officer/cameras/1/ai-status");
  await startStream(1, "Presentation Webcam", [640, 480]);

  expect(await screen.findByText("AI detection live · Video 29.5 FPS · AI 7.5 FPS")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Person 3: no Gloves");
  expect(screen.getByText("Person 4")).toBeInTheDocument();
  expect(screen.getByText("Person 3 · Missing Gloves")).toBeInTheDocument();
  // A confirmed violation refreshes the incident alert list.
  await waitFor(() => expect(api.get.mock.calls.filter(([url]) => url === "/officer/alerts").length).toBeGreaterThan(1));

  // Restricted location: no PPE chips, entry is the violation.
  status.restricted_location = true;
  status.required_ppe = [];
  status.people = [{ track_id: 5, state: "violation", missing: [], checking: [], restricted_zones: ["Restricted area"], entering_zones: [], wearing: {} }];
  expect(await screen.findByText(/anyone seen is a violation/, {}, { timeout: 3000 })).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Person 5: in Restricted area");

  fireEvent.click(screen.getByRole("button", { name: /Stop Streaming/ }));
  expect(screen.queryByTestId("ai-panel")).not.toBeInTheDocument();
});
