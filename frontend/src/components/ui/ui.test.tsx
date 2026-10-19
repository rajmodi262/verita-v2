import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Button, EmptyState, Field, Panel, Stamp } from ".";

describe("Button", () => {
  it("defaults to type=button so it never submits a form by accident", () => {
    render(<Button>Go</Button>);
    expect(screen.getByRole("button", { name: "Go" })).toHaveAttribute("type", "button");
  });

  it("is disabled and marked busy while busy", async () => {
    const onClick = vi.fn();
    render(
      <Button busy onClick={onClick}>
        Save
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("applies the variant class", () => {
    render(<Button variant="danger">Delete</Button>);
    expect(screen.getByRole("button").className).toContain("danger");
  });
});

describe("Field", () => {
  it("links label, hint and error for assistive tech", () => {
    render(<Field label="Analysts" hint="Between 1 and 20" error="Too many" defaultValue="40" />);
    const input = screen.getByLabelText("Analysts");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Between 1 and 20 Too many");
  });

  it("has no description when there is nothing to describe", () => {
    render(<Field label="Name" />);
    const input = screen.getByLabelText("Name");
    expect(input).not.toHaveAttribute("aria-describedby");
    expect(input).not.toHaveAttribute("aria-invalid");
  });
});

it("Panel is a labelled region with optional label and actions", () => {
  render(
    <Panel title="Evidence" label="Exhibit A" actions={<button type="button">Copy</button>}>
      body
    </Panel>,
  );
  expect(screen.getByRole("region", { name: "Evidence" })).toBeInTheDocument();
  expect(screen.getByText("Exhibit A")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
});

it("Panel renders without label or actions", () => {
  render(<Panel title="Plain">body</Panel>);
  expect(screen.getByRole("region", { name: "Plain" })).toHaveTextContent("body");
});

it("Stamp carries its tone", () => {
  render(<Stamp tone="verified">Sealed</Stamp>);
  expect(screen.getByText("Sealed").className).toContain("verified");
});

it("EmptyState is announced as status and can carry an action", () => {
  render(
    <EmptyState title="Nothing yet" action={<a href="/x">Go</a>}>
      <p>Explanation</p>
    </EmptyState>,
  );
  expect(screen.getByRole("status")).toHaveTextContent("Nothing yet");
  expect(screen.getByRole("link", { name: "Go" })).toBeInTheDocument();
});
