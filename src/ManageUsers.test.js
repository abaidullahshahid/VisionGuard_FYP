import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axios from "axios";
import ManageUsers from "./ManageUsers";

jest.mock("react-router-dom", () => ({ useNavigate: () => jest.fn() }), { virtual: true });
jest.mock("./Sidebar", () => () => <nav />);
jest.mock("axios", () => ({ get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn(), create: () => ({ interceptors: { request: { use: () => {} } } }) }));

beforeEach(() => {
  sessionStorage.setItem("token", "admin-test");
  axios.get.mockResolvedValue({ data: [{ id: 1, name: "Admin User", email: "admin@site.com", role: "admin", status: "active", department: null }] });
  axios.post.mockResolvedValue({ data: {} });
});

afterEach(() => sessionStorage.clear());

test("admins are shown as covering all departments", async () => {
  render(<ManageUsers />);
  expect(await screen.findByText("All departments")).toBeInTheDocument();
});

test("department is required for workers, optional for officers and hidden for admins", async () => {
  render(<ManageUsers />);
  fireEvent.click(await screen.findByRole("button", { name: /Add New User/ }));
  expect(screen.getByLabelText("Department")).toBeRequired();

  fireEvent.click(screen.getByLabelText("Role"));
  fireEvent.click(screen.getByRole("option", { name: /Safety Officer/ }));
  expect(screen.getByLabelText("Department (optional)")).not.toBeRequired();

  fireEvent.click(screen.getByLabelText("Role"));
  fireEvent.click(screen.getByRole("option", { name: /^Admin/ }));
  expect(screen.queryByLabelText(/Department/)).not.toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("Enter full name"), { target: { value: "Second Admin" } });
  fireEvent.change(screen.getByPlaceholderText("Enter email"), { target: { value: "admin2@site.com" } });
  fireEvent.change(screen.getByPlaceholderText("Enter password"), { target: { value: "secret12" } });
  fireEvent.click(screen.getByRole("button", { name: "Add User" }));
  await waitFor(() => expect(axios.post).toHaveBeenCalledWith(
    expect.stringMatching(/\/admin\/users$/),
    expect.objectContaining({ role: "admin", department: null }),
    expect.anything(),
  ));
});

test("delete explains what happens and shows the server's answer", async () => {
  axios.get.mockResolvedValue({ data: [{ id: 3, name: "abaid", email: "abaid@site.com", role: "worker", status: "active", department: "QA" }] });
  axios.delete.mockResolvedValue({ data: { detail: "abaid was deleted. Their 2 corrective action(s) are kept in the history; 1 open one(s) now need a new assignee in Corrective Actions." } });
  const confirm = jest.spyOn(window, "confirm").mockReturnValue(true);
  render(<ManageUsers />);
  fireEvent.click(await screen.findByRole("button", { name: /Delete/ }));
  expect(confirm.mock.calls[0][0]).toMatch(/unfinished tasks become unassigned/);
  expect(await screen.findByText(/1 open one\(s\) now need a new assignee/)).toBeInTheDocument();

  axios.delete.mockRejectedValue({ response: { data: { detail: "You cannot delete your own account." } } });
  fireEvent.click(screen.getByRole("button", { name: /Delete/ }));
  expect(await screen.findByText("You cannot delete your own account.")).toBeInTheDocument();
  confirm.mockRestore();
});

test("search and role filter narrow the user list", async () => {
  axios.get.mockResolvedValue({ data: [
    { id: 1, name: "abaid", email: "abaid@site.com", role: "admin", status: "active", department: null },
    { id: 2, name: "adnan", email: "adnan@site.com", role: "officer", status: "active", department: "construction" },
    { id: 3, name: "Sara", email: "sara@site.com", role: "worker", status: "inactive", department: "Warehouse" },
  ] });
  render(<ManageUsers />);
  await screen.findByText("Sara");

  fireEvent.change(screen.getByLabelText("Search users"), { target: { value: "ADNAN" } });
  expect(screen.getByText("adnan")).toBeInTheDocument();
  expect(screen.queryByText("Sara")).not.toBeInTheDocument();
  expect(screen.getByText("1 of 3 users match")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Search users"), { target: { value: "warehouse" } });
  expect(screen.getByText("Sara")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Search users"), { target: { value: "" } });
  fireEvent.click(screen.getByLabelText("Filter by role"));
  fireEvent.click(screen.getByRole("option", { name: "Safety Officer" }));
  expect(screen.getByText("adnan")).toBeInTheDocument();
  expect(screen.queryByText("abaid")).not.toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Search users"), { target: { value: "nobody" } });
  expect(screen.getByText("No users match your search.")).toBeInTheDocument();
});
