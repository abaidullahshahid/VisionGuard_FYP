import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import SelectMenu from "./SelectMenu";

const OPTIONS = [
  { value: "All PPE", label: "All PPE", description: "Helmet, safety vest and gloves" },
  { value: "Helmet", label: "Helmet" },
  { value: "No PPE", label: "None", description: "No PPE required at this location" },
];

function Harness({ initial = "All PPE", disabled = false, onChange = () => {} }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="ppe">PPE Type</label>
      <SelectMenu
        id="ppe"
        value={value}
        options={OPTIONS}
        disabled={disabled}
        onChange={(next) => { setValue(next); onChange(next); }}
      />
      <span>outside</span>
    </>
  );
}

test("shows the selected label and opens a themed list with descriptions", () => {
  render(<Harness />);
  const button = screen.getByRole("button", { name: "PPE Type" });
  expect(button).toHaveTextContent("All PPE");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

  fireEvent.click(button);
  expect(screen.getAllByRole("option")).toHaveLength(3);
  expect(screen.getByText("No PPE required at this location")).toBeInTheDocument();
  expect(screen.getByRole("option", { name: /All PPE/ })).toHaveAttribute("aria-selected", "true");
});

test("hovering highlights an option and clicking selects it", () => {
  const onChange = jest.fn();
  render(<Harness onChange={onChange} />);
  fireEvent.click(screen.getByRole("button", { name: "PPE Type" }));
  const none = screen.getByRole("option", { name: /None/ });
  fireEvent.mouseEnter(none);
  expect(none).toHaveClass("active");
  fireEvent.click(none);
  expect(onChange).toHaveBeenCalledWith("No PPE");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "PPE Type" })).toHaveTextContent("None");
});

test("supports keyboard selection and Escape", () => {
  const onChange = jest.fn();
  render(<Harness onChange={onChange} />);
  const button = screen.getByRole("button", { name: "PPE Type" });
  fireEvent.keyDown(button, { key: "ArrowDown" });
  const list = screen.getByRole("listbox");
  fireEvent.keyDown(list, { key: "ArrowDown" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(onChange).toHaveBeenCalledWith("Helmet");

  fireEvent.keyDown(button, { key: "Enter" });
  fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(onChange).toHaveBeenCalledTimes(1);
});

test("closes on outside click and stays closed while disabled", () => {
  const { rerender } = render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "PPE Type" }));
  fireEvent.mouseDown(screen.getByText("outside"));
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

  rerender(<Harness disabled />);
  const button = screen.getByRole("button", { name: "PPE Type" });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});
