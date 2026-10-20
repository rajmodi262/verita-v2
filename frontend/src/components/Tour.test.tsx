import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { json, mockApi, problem, renderAt } from "../test/utils";

import { TOUR } from "./Tour";

const REVIEWER = { id: 4, username: "rev", role: "reviewer" } as const;

function api() {
  return mockApi({
    "GET /me": () => json(REVIEWER),
    "GET /evidence-room/metrics": () => problem(503, "no-metrics", "No evaluation report yet"),
    "GET /cases": () => json({ items: [] }),
  });
}

it("walks a reviewer through the demo path and remembers where they are", async () => {
  const user = userEvent.setup();
  api();
  const { router } = renderAt("/evidence-room");
  const tour = await screen.findByRole("complementary", { name: "Guided tour" });
  expect(tour).toHaveTextContent("1 of 8");
  for (let i = 0; i < 4; i++) await user.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByRole("complementary", { name: "Guided tour" })).toHaveTextContent(
    TOUR[4]!.title,
  );
  expect(router.state.location.pathname).toBe("/cases");
  expect(localStorage.getItem("verita.tour")).toBe("4");
  await user.click(screen.getByRole("button", { name: "Skip tour" }));
  expect(screen.queryByRole("complementary", { name: "Guided tour" })).not.toBeInTheDocument();
  expect(localStorage.getItem("verita.tour")).toBe("done");
  await user.click(screen.getByRole("button", { name: "Restart the tour" }));
  expect(screen.getByRole("complementary", { name: "Guided tour" })).toHaveTextContent("1 of 8");
});

it("is not shown to analysts", async () => {
  mockApi({
    "GET /me": () => json({ id: 1, username: "priya", role: "analyst" }),
    "GET /evidence-room/metrics": () => problem(503, "no-metrics", "No evaluation report yet"),
  });
  renderAt("/evidence-room");
  await screen.findByText("No evaluation report yet");
  expect(screen.queryByRole("complementary", { name: "Guided tour" })).not.toBeInTheDocument();
});
