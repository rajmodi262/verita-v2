import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { alertDetail, META, subgraph } from "../../test/alertFixtures";
import { ANALYST, json, mockApi, problem, renderAt } from "../../test/utils";

const cy = {
  on: vi.fn(),
  destroy: vi.fn(),
  edges: vi.fn(() => ({ unselect: vi.fn() })),
  getElementById: vi.fn(() => ({ select: vi.fn() })),
};
const cytoscape = vi.fn((_config: unknown) => cy);
vi.mock("cytoscape", () => ({ default: cytoscape }));

function api(extra = {}, user: object = ANALYST) {
  return mockApi({
    "GET /me": () => json(user),
    "GET /alerts/meta": () => json(META),
    "GET /alerts/7": () => json(alertDetail(7)),
    "GET /alerts/7/subgraph": () => json(subgraph(7)),
    ...extra,
  });
}

it("explains the alert with reasons, signals and evidence ids", async () => {
  api();
  renderAt("/alerts/7");
  expect(await screen.findByText("Why this is an alert")).toBeInTheDocument();
  expect(screen.getByText(/Sender paid 9 different accounts/)).toBeInTheDocument();
  expect(screen.getByText("EV-REASON-7-1")).toBeInTheDocument();
  expect(await screen.findByText("sender fanned out to 9 payees in 24 h")).toBeInTheDocument();
  expect(screen.getByText(/nothing after the alert day is used/)).toBeInTheDocument();
});

it("draws the graph with the layout and lists the dominant path", async () => {
  api();
  renderAt("/alerts/7");
  await screen.findByRole("img", { name: /Money-flow graph: 3 accounts and 2 payments/ });
  await waitFor(() => {
    expect(cytoscape).toHaveBeenCalled();
  });
  const config = cytoscape.mock.calls[0]![0] as { elements: { data: { id: string } }[] };
  expect(config.elements.map((e) => e.data.id)).toEqual(
    expect.arrayContaining(["11:800000001", "1001", "1002"]),
  );
  const path = screen.getByRole("region", { name: "Dominant path" });
  expect(within(path).getByText("EV-TXN-1001")).toBeInTheDocument();
  expect(within(path).queryByText("EV-TXN-1002")).not.toBeInTheDocument();
});

it("offers a full table view of every payment", async () => {
  const user = userEvent.setup();
  api();
  renderAt("/alerts/7");
  await screen.findByRole("img", { name: /Money-flow graph/ });
  await user.click(screen.getByRole("button", { name: "Table" }));
  expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getAllByRole("button", { name: "EV-TXN-1002" })).toHaveLength(1);
  await user.click(screen.getAllByRole("button", { name: "EV-TXN-1001" })[0]!);
  expect(screen.getAllByRole("button", { name: "EV-TXN-1001" })[0]).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

it("escalates with a reason", async () => {
  const user = userEvent.setup();
  const { calls } = api({
    "POST /alerts/7/disposition": () => json(alertDetail(7, { status: "escalated" })),
  });
  renderAt("/alerts/7");
  await user.click(await screen.findByRole("button", { name: "Escalate" }));
  const dialog = screen.getByRole("dialog", { name: "Escalate alert" });
  await user.selectOptions(within(dialog).getByLabelText("Reason"), "typology_match");
  await user.click(within(dialog).getByRole("button", { name: "Escalate alert" }));
  expect(await screen.findByText("escalated")).toBeInTheDocument();
  expect(calls.some((c) => c.key === "POST /alerts/7/disposition")).toBe(true);
});

it("shows decisions history and allows reopening", async () => {
  api({
    "GET /alerts/7": () =>
      json(
        alertDetail(7, {
          status: "dismissed",
          dispositions: [
            {
              id: 1,
              action: "dismiss",
              reason_code: "known_counterparty",
              note: "payroll",
              user_id: 1,
              created_at: "2026-10-19T10:00:00+00:00",
            },
          ],
        }),
      ),
  });
  renderAt("/alerts/7");
  expect(await screen.findByText(/known counterparty/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reopen" })).toBeInTheDocument();
});

it("disables decisions for read-only roles", async () => {
  api({}, { id: 2, username: "rev", role: "reviewer" });
  renderAt("/alerts/7");
  const escalate = await screen.findByRole("button", { name: "Escalate" });
  await waitFor(() => {
    expect(escalate).toBeDisabled();
  });
  expect(escalate).toHaveAttribute("title", "Only analysts and MLROs can decide on alerts");
});

it("reports a missing evidence store without breaking the page", async () => {
  api({
    "GET /alerts/7/subgraph": () => problem(503, "no-evidence-store", "Evidence store not built"),
  });
  renderAt("/alerts/7");
  expect(await screen.findByRole("alert")).toHaveTextContent("Evidence store not built");
  expect(screen.getByText("Why this is an alert")).toBeInTheDocument();
});

it("handles unknown and invalid alerts", async () => {
  api({ "GET /alerts/99": () => problem(404, "alert-not-found", "Alert not found") });
  const { unmount } = renderAt("/alerts/99");
  expect(await screen.findByRole("alert")).toHaveTextContent("Alert not found");
  unmount();
  renderAt("/alerts/abc");
  expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
});
