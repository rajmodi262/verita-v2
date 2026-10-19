import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { alertDetail, alertSummary, META } from "../../test/alertFixtures";
import { ANALYST, json, mockApi, problem, renderAt } from "../../test/utils";

function queueApi(extra = {}) {
  return mockApi({
    "GET /me": () => json(ANALYST),
    "GET /alerts/meta": () => json(META),
    "GET /alerts?limit=100&status=open": () =>
      json({
        items: [alertSummary(1), alertSummary(2), alertSummary(3)],
        next_cursor: "c1",
        total: 4,
        threshold: 0.42,
      }),
    "GET /alerts?limit=100&status=open&cursor=c1": () =>
      json({ items: [alertSummary(4)], next_cursor: null, total: 4, threshold: 0.42 }),
    ...extra,
  });
}

it("lists alerts riskiest first and pages with a cursor", async () => {
  const user = userEvent.setup();
  queueApi();
  renderAt("/queue");
  expect(await screen.findByText("Showing 3 of 4 alerts, riskiest first")).toBeInTheDocument();
  const rows = screen.getAllByRole("row").slice(1);
  expect(rows).toHaveLength(3);
  expect(within(rows[0]!).getByText("0.890")).toBeInTheDocument();
  expect(screen.getByText(/flagged at score ≥/)).toHaveTextContent("0.420");
  await user.click(screen.getByRole("button", { name: /Load the next 1 alerts/ }));
  expect(await screen.findByText("Showing 4 of 4 alerts, riskiest first")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Load the next/ })).not.toBeInTheDocument();
});

it("changes filters through the URL", async () => {
  const user = userEvent.setup();
  const { calls } = queueApi({
    "GET /alerts?limit=100&date=2022-09-10&status=open": () =>
      json({ items: [alertSummary(9)], next_cursor: null, total: 1, threshold: 0.42 }),
    "GET /capacity/plans/latest?date=2022-09-10": () => problem(404, "no-plan", "No plan"),
  });
  const { router } = renderAt("/queue");
  await screen.findByText("Showing 3 of 4 alerts, riskiest first");
  await user.selectOptions(screen.getByLabelText("Day"), "2022-09-10");
  expect(await screen.findByText("Showing 1 of 1 alerts, riskiest first")).toBeInTheDocument();
  expect(router.state.location.search).toContain("date=2022-09-10");
  expect(calls.some((c) => c.key.includes("date=2022-09-10"))).toBe(true);
});

it("shows the MLRO's saved plan for the filtered day", async () => {
  queueApi({
    "GET /alerts?limit=100&date=2022-09-10&status=open": () =>
      json({ items: [alertSummary(9)], next_cursor: null, total: 1, threshold: 0.42 }),
    "GET /capacity/plans/latest?date=2022-09-10": () =>
      json({
        id: 3,
        date: "2022-09-10",
        analysts: 6,
        alpha: 0.05,
        mode: "pooled",
        created_by: 2,
        created_at: "2022-09-09T18:00:00+00:00",
        result: {},
        selected_alert_ids: [9, 10, 11],
      }),
  });
  renderAt("/queue?date=2022-09-10");
  expect(
    await screen.findByText(/6 analysts reviewing the top 3 alerts at a 95% recall guarantee/),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open in the planner" })).toHaveAttribute(
    "href",
    "/capacity?date=2022-09-10&analysts=6&alpha=0.05",
  );
});

it("moves with J/K, opens with Enter, and dismisses with D", async () => {
  const user = userEvent.setup();
  const { calls } = queueApi({
    "POST /alerts/2/disposition": () => json(alertDetail(2, { status: "dismissed" })),
    "GET /alerts/2": () => json(alertDetail(2)),
    "GET /alerts/2/subgraph": () => problem(503, "no-evidence-store", "Evidence store not built"),
  });
  const { router } = renderAt("/queue");
  await screen.findByText("Showing 3 of 4 alerts, riskiest first");
  await user.keyboard("j");
  expect(screen.getAllByRole("row")[2]).toHaveAttribute("aria-selected", "true");
  await user.keyboard("k");
  await user.keyboard("j");
  await user.keyboard("d");
  const dialog = await screen.findByRole("dialog", { name: "Dismiss alert" });
  await user.selectOptions(within(dialog).getByLabelText("Reason"), "known_counterparty");
  await user.type(within(dialog).getByLabelText("Note (optional)"), "payroll");
  await user.click(within(dialog).getByRole("button", { name: "Dismiss alert" }));
  await waitFor(() => {
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  const sent = calls.find((c) => c.key === "POST /alerts/2/disposition")!.init.body as string;
  expect(JSON.parse(sent)).toEqual({
    action: "dismiss",
    reason_code: "known_counterparty",
    note: "payroll",
  });
  await user.keyboard("{Enter}");
  await waitFor(() => {
    expect(router.state.location.pathname).toBe("/alerts/2");
  });
});

it("shows keyboard help and closes it with Escape", async () => {
  const user = userEvent.setup();
  queueApi();
  renderAt("/queue");
  await screen.findByText("Showing 3 of 4 alerts, riskiest first");
  await user.keyboard("?");
  const dialog = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
  expect(within(dialog).getByText("Open the investigation")).toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("explains how to load alerts when no model is deployed", async () => {
  mockApi({
    "GET /me": () => json(ANALYST),
    "GET /alerts/meta": () => problem(503, "no-model", "No detector has been deployed yet"),
    "GET /alerts?limit=100&status=open": () => problem(503, "no-model", "No detector"),
  });
  renderAt("/queue");
  expect(await screen.findByText("No alerts loaded yet")).toBeInTheDocument();
});

it("shows an empty state when filters match nothing", async () => {
  mockApi({
    "GET /me": () => json(ANALYST),
    "GET /alerts/meta": () => json(META),
    "GET /alerts?limit=100&status=open": () =>
      json({ items: [], next_cursor: null, total: 0, threshold: 0.42 }),
  });
  renderAt("/queue");
  expect(await screen.findByText("No alerts match")).toBeInTheDocument();
});
