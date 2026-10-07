import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axios from "axios";
import ConfigureSafetyRules from "./ConfigureSafetyRules";

const mockNavigate = jest.fn(); // stable, like the real router's navigate
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }), { virtual: true });
jest.mock("./Sidebar", () => () => <nav />);
jest.mock("axios", () => ({ get: jest.fn(), post: jest.fn(), delete: jest.fn(), create: () => ({ interceptors: { request: { use: () => {} } } }) }));

const rules = [
  { id: 1, location_id: 2, ppe_type: "No PPE", is_restricted_area: false, severity_level: "Low" },
  { id: 2, location_id: 3, ppe_type: "All PPE", is_restricted_area: false, severity_level: "High" },
];

beforeEach(() => {
  sessionStorage.setItem("token", "admin-test");
  axios.get.mockImplementation((url) => Promise.resolve({
    data: url.endsWith("/safety-rules") ? rules : [{ id: 2, name: "PPE Area" }, { id: 3, name: "Store" }],
  }));
});

afterEach(() => sessionStorage.clear());

async function openForm() {
  render(<ConfigureSafetyRules />);
  await screen.findByText("Not applicable");
  fireEvent.click(screen.getByRole("button", { name: /Add Rule/ }));
  fireEvent.click(screen.getByLabelText("Location"));
  fireEvent.click(screen.getByRole("option", { name: "PPE Area" }));
}

test("None needs no severity; the table shows it as not applicable", async () => {
  axios.post.mockResolvedValue({ data: {} });
  await openForm();
  expect(screen.getByLabelText("Severity Level")).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("None"));
  expect(screen.queryByLabelText("Severity Level")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Helmet")).not.toBeChecked();

  fireEvent.click(screen.getAllByRole("button", { name: /Add Rule/ }).at(-1));
  await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
    expect.stringMatching(/\/admin\/safety-rules$/),
    expect.objectContaining({ location_id: 2, ppe_type: "No PPE", severity_level: "Low" }),
    expect.anything(),
  ));
});

test("explains why adding failed", async () => {
  axios.post.mockRejectedValueOnce({ message: "Network Error" });
  await openForm();
  fireEvent.click(screen.getAllByRole("button", { name: /Add Rule/ }).at(-1));
  expect(await screen.findByText(/Cannot reach the VisionGuard server/)).toBeInTheDocument();

  axios.post.mockRejectedValueOnce({ response: { status: 409, data: { detail: "This location already requires PPE. Delete those rules before choosing None." } } });
  fireEvent.click(screen.getAllByRole("button", { name: /Add Rule/ }).at(-1));
  expect(await screen.findByText(/already requires PPE/)).toBeInTheDocument();
});

test("several PPE items can be required together", async () => {
  axios.post.mockResolvedValue({ data: { detail: "PPE Area now requires Helmet, Safety Vest." } });
  await openForm();
  expect(screen.getByText(/All PPE: helmet, safety vest and gloves/)).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Gloves"));
  expect(screen.getByText("Required: Helmet + Safety Vest.")).toBeInTheDocument();

  fireEvent.click(screen.getAllByRole("button", { name: /Add Rule/ }).at(-1));
  await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
    expect.stringMatching(/\/admin\/safety-rules$/),
    { location_id: 2, ppe_types: ["Helmet", "Safety Vest"], severity_level: "High" },
    expect.anything(),
  ));
  expect(await screen.findByText("PPE Area now requires Helmet, Safety Vest.")).toBeInTheDocument();
});

test("a save whose reply was lost still counts as added", async () => {
  axios.post.mockRejectedValueOnce({ message: "Network Error" });
  await openForm();
  axios.get.mockImplementation((url) => Promise.resolve({
    data: url.endsWith("/safety-rules")
      ? [...rules, { id: 9, location_id: 2, ppe_type: "All PPE", is_restricted_area: false, severity_level: "High" }]
      : [{ id: 2, name: "PPE Area" }, { id: 3, name: "Store" }],
  }));
  fireEvent.click(screen.getAllByRole("button", { name: /Add Rule/ }).at(-1));
  expect(await screen.findByText("Safety rule added successfully.")).toBeInTheDocument();
  expect(screen.queryByText(/Cannot reach/)).not.toBeInTheDocument();
});

test("asks for at least one item", async () => {
  await openForm();
  for (const item of ["Helmet", "Safety Vest", "Gloves"]) fireEvent.click(screen.getByLabelText(item));
  fireEvent.click(screen.getAllByRole("button", { name: /Add Rule/ }).at(-1));
  expect(await screen.findByText("Tick at least one PPE item, or choose None.")).toBeInTheDocument();
  expect(axios.post).not.toHaveBeenCalled();
});
