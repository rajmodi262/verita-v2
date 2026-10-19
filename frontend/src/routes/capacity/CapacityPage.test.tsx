import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CAPACITY_ROUTES, DAY, plan, planKey } from "../../test/capacityFixtures";
import type { Handler } from "../../test/utils";
import { ANALYST, json, mockApi, problem, renderAt } from "../../test/utils";

const MLRO = { id: 2, username: "marcus", role: "mlro" } as const;

function api(extra: Record<string, Handler> = {}, user: object = ANALYST) {
  const routes: Record<string, Handler> = {
    "GET /me": () => json(user),
    [`GET /capacity/plans/latest?date=${DAY}`]: () => problem(404, "no-plan", "No plan"),
    [planKey(4)]: () => json(plan(4)),
    ...extra,
  };
  for (const [key, body] of Object.entries(CAPACITY_ROUTES)) {
    routes[key] ??= () => json(body);
  }
  return mockApi(routes);
}

it("shows the guarantee, expected recall and the replay check for the chosen staffing", async () => {
  api();
  renderAt("/capacity?analysts=4");
  const guarantee = await screen.findByRole("group", { name: "95% recall guarantee" });
  expect(within(guarantee).getByText("✗ Needs 987 more")).toBeInTheDocument();
  const recall = screen.getByRole("group", { name: "Expected recall" });
  expect(within(recall).getByText("40.0%")).toBeInTheDocument();
  expect(await screen.findByText(/Exact plan \(cp-sat\); greedy gap 1.23%/)).toBeInTheDocument();
  expect(screen.getByText(/actually\s+caught/)).toBeInTheDocument();
  expect(screen.getByText("39.7%")).toBeInTheDocument(); // 120 of 302
  expect(screen.getByText(/1.7 expected positives sit below the alert floor/)).toBeInTheDocument();
});

it("explains how each figure is computed", async () => {
  const user = userEvent.setup();
  api();
  renderAt("/capacity?analysts=4");
  const recall = await screen.findByRole("group", { name: "Expected recall" });
  await user.click(within(recall).getByText("How computed"));
  expect(within(recall).getByText("plan.expected_recall")).toBeVisible();
});

it("answers the slider instantly from the frontier, then fetches the exact plan", async () => {
  const { calls } = api({ [planKey(2)]: () => json(plan(2)) });
  renderAt("/capacity?analysts=4");
  await screen.findByText(/Exact plan \(cp-sat\)/);
  fireEvent.change(screen.getByRole("slider", { name: "Analysts on duty" }), {
    target: { value: "2" },
  });
  // immediately: the precomputed estimate for 2 analysts
  expect(screen.getByText(/Estimate from the precomputed greedy frontier/)).toBeInTheDocument();
  expect(within(screen.getByRole("group", { name: "Expected recall" })).getByText("20.0%"));
  await screen.findByText(/Exact plan \(cp-sat\)/);
  expect(calls.some((c) => c.key === planKey(2))).toBe(true);
  expect(calls.some((c) => c.key === planKey(3))).toBe(false);
});

it("lets only the MLRO save a plan, and says why otherwise", async () => {
  api();
  renderAt("/capacity?analysts=4");
  await screen.findByText(/Exact plan/);
  expect(screen.getByRole("button", { name: "Save plan" })).toBeDisabled();
  expect(screen.getByText(/Only the MLRO can save a staffing plan/)).toBeInTheDocument();
});

it("saves the MLRO's plan with the chosen settings", async () => {
  const user = userEvent.setup();
  const { calls } = api({ "POST /capacity/plans": () => json({ id: 9, plan: plan(4) }) }, MLRO);
  renderAt("/capacity?analysts=4");
  await screen.findByText(/Exact plan/);
  await user.click(screen.getByRole("button", { name: "Save plan" }));
  expect(await screen.findByText(/Saved as plan #9/)).toBeInTheDocument();
  const post = calls.find((c) => c.key === "POST /capacity/plans");
  expect(JSON.parse(post?.init.body as string)).toEqual({
    date: DAY,
    analysts: 4,
    alpha: 0.05,
    mode: "pooled",
    objective: "cases",
  });
});

it("runs a what-if on the assumptions and never saves it", async () => {
  const user = userEvent.setup();
  const whatIf = planKey(4, "&median_minutes=45");
  const { calls } = api(
    {
      [whatIf]: () =>
        json(plan(4, { assumptions: { ...plan(4).assumptions, overridden: ["median_minutes"] } })),
    },
    MLRO,
  );
  renderAt("/capacity?analysts=4");
  await screen.findByText(/Exact plan/);
  await user.click(screen.getByText("Assumptions"));
  const minutes = screen.getByLabelText("Median handling time (minutes)");
  await user.clear(minutes);
  await user.type(minutes, "45");
  await user.click(screen.getByRole("button", { name: "Apply what-if" }));
  await waitFor(() => {
    expect(calls.some((c) => c.key === whatIf)).toBe(true);
  });
  expect(screen.getByRole("button", { name: "Save plan" })).toBeDisabled();
  expect(screen.getByText(/Reset the what-if first/)).toBeInTheDocument();
});

it("has a table alternative for every chart and states the takeaways", async () => {
  const user = userEvent.setup();
  api();
  renderAt("/capacity?analysts=4");
  expect(await screen.findByText(/guarantee needs 991 analysts on this day/)).toBeInTheDocument();
  expect(screen.getByText(/On 1 of 2 days the 95% guarantee needs more than the 4/)).toBeVisible();
  expect(
    await screen.findByText(
      /adaptive conformal realised 96.4% \(kept\) while reviewing 10.2% fewer/,
    ),
  ).toBeInTheDocument();
  const tables = screen.getAllByRole("button", { name: "Table" });
  expect(tables.length).toBe(4);
  for (const button of tables) await user.click(button);
  expect(
    screen.getByRole("table", { name: "Staffing frontier by analysts on duty" }),
  ).toBeVisible();
  expect(screen.getByRole("table", { name: "Forecast backtest by model" })).toBeVisible();
});

it("flags drift with a recalibration banner", async () => {
  api();
  renderAt("/capacity?analysts=4");
  const text = await screen.findByText(/Recalibration is\s+recommended/);
  const banner = text.closest("[role=status]");
  expect(banner).not.toBeNull();
  expect(within(banner as HTMLElement).getByText("r_age_min")).toBeInTheDocument();
});

it("says what to run when Decide has not been run", async () => {
  mockApi({
    "GET /me": () => json(ANALYST),
    "GET /capacity/meta": () => problem(503, "no-decide", "Capacity analysis has not been run"),
  });
  renderAt("/capacity");
  expect(await screen.findByText("Capacity analysis has not been run")).toBeInTheDocument();
});
