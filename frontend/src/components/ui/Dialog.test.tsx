import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { Dialog } from "./Dialog";

function Harness({ footer = true }: { footer?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
        }}
      >
        Open
      </button>
      <Dialog
        title="Dismiss alert"
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        footer={footer ? <button type="button">Confirm</button> : undefined}
      >
        <label>
          Reason <input />
        </label>
        <button type="button" disabled>
          Unavailable
        </button>
      </Dialog>
    </>
  );
}

it("renders nothing while closed", () => {
  render(<Harness />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("is a labelled modal that takes focus when it opens", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Open" }));
  const dialog = screen.getByRole("dialog", { name: "Dismiss alert" });
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(screen.getByRole("textbox", { name: "Reason" })).toHaveFocus();
});

it("traps Tab in both directions, skipping disabled controls", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Open" }));
  const input = screen.getByRole("textbox", { name: "Reason" });
  const confirm = screen.getByRole("button", { name: "Confirm" });

  await user.tab();
  expect(confirm).toHaveFocus();
  await user.tab(); // past the last control: back to the first
  expect(input).toHaveFocus();
  await user.tab({ shift: true }); // before the first control: round to the last
  expect(confirm).toHaveFocus();
});

it("closes on Escape and returns focus to what opened it", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  const opener = screen.getByRole("button", { name: "Open" });
  await user.click(opener);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(opener).toHaveFocus();
});

it("ignores other keys and works without a footer", async () => {
  const user = userEvent.setup();
  render(<Harness footer={false} />);
  await user.click(screen.getByRole("button", { name: "Open" }));
  await user.keyboard("a");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  await user.tab(); // the only control: Tab stays on it
  expect(screen.getByRole("textbox", { name: "Reason" })).toHaveFocus();
});
