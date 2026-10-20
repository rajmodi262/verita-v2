import { readFileSync } from "node:fs";
import { join } from "node:path";

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { metricsFile } from "../../api/evidence";
import type { MetricsFile } from "../../api/evidence";
import { percent } from "../../lib/format";
import { ANALYST, json, mockApi, problem, renderAt } from "../../test/utils";

// The real generated report: if the backend's metrics.json drifts from what the Evidence Room
// reads, this test fails, not the demo.
const raw = readFileSync(join(__dirname, "../../../../reports/metrics.json"), "utf-8");
const METRICS = JSON.parse(raw) as MetricsFile;
const SHA = "ab".repeat(32);

function api() {
  return mockApi({
    "GET /me": () => json(ANALYST),
    "GET /evidence-room/metrics": () => json({ sha256: SHA, metrics: METRICS }),
  });
}

it("parses the committed metrics.json", () => {
  expect(metricsFile.safeParse(METRICS).success).toBe(true);
});

it("opens on Detect with the champion's F1 from the report", async () => {
  api();
  renderAt("/evidence-room");
  const champion = METRICS.datasets.hi_small?.detect?.models.lgbm_champion?.test.f1.value ?? 0;
  const stat = await screen.findByRole("group", { name: "Laundering F1, champion" });
  expect(within(stat).getByText(percent(champion))).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Detect" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText(/GFP \+ LightGBM \(published\)/)).toBeInTheDocument();
  expect(
    screen.getAllByRole("link", { name: "Download the underlying JSON" }).length,
  ).toBeGreaterThan(0);
  expect(screen.getByText(METRICS.git_sha)).toBeInTheDocument();
});

it("moves between tabs with the arrow keys", async () => {
  const user = userEvent.setup();
  const { router } = (api(), renderAt("/evidence-room?tab=data"));
  const data = await screen.findByRole("tab", { name: "Data" });
  expect(screen.getByRole("group", { name: "Payments" })).toBeInTheDocument();
  data.focus();
  await user.keyboard("{ArrowRight}");
  expect(router.state.location.search).toContain("tab=detect");
  expect(screen.getByRole("tab", { name: "Detect" })).toHaveFocus();
  await user.keyboard("{ArrowLeft}{ArrowLeft}");
  expect(router.state.location.search).toContain("tab=lineage");
});

it("shows the verifier's results and its misses verbatim", async () => {
  api();
  renderAt("/evidence-room?tab=defend");
  expect(await screen.findByRole("group", { name: "Planted faults caught" })).toBeInTheDocument();
  expect(screen.getByText("What it missed")).toBeInTheDocument();
  expect(screen.getByText(/claims are matched by value, not by role/)).toBeInTheDocument();
});

it("shows the raw LLM rate with who wrote the drafts and how many attempts failed", async () => {
  const m = structuredClone(METRICS);
  const defend = m.datasets.hi_small?.defend;
  if (!defend) throw new Error("fixture report has no Defend section");
  defend.llm = {
    run: true,
    drafts: 17,
    provider_failures: 13,
    drafted_by: { "groq/openai/gpt-oss-120b": 17 },
    unsupported_claim_rate: { hits: 18, total: 615, value: 0.029268, low: 0.0186, high: 0.0458 },
    drafts_passing_verification: { hits: 1, total: 17, value: 0.0588, low: 0.0105, high: 0.2698 },
  };
  mockApi({
    "GET /me": () => json(ANALYST),
    "GET /evidence-room/metrics": () => json({ sha256: SHA, metrics: m }),
  });
  renderAt("/evidence-room?tab=defend");
  const rate = await screen.findByRole("group", { name: "Raw LLM hallucination" });
  expect(within(rate).getByText("2.9%")).toBeInTheDocument();
  expect(within(rate).getByText(/18 of 615 claims unsupported/)).toBeInTheDocument();
  expect(within(rate).getByText(/17 by groq\/openai\/gpt-oss-120b/)).toBeInTheDocument();
  const passing = screen.getByRole("group", { name: "LLM drafts passing as written" });
  expect(within(passing).getByText(/1 of 17 drafts/)).toBeInTheDocument();
  expect(within(passing).getByText(/30 attempted, 13 hit provider quota/)).toBeInTheDocument();
});

it("says why the raw LLM rate was not measured", async () => {
  const m = structuredClone(METRICS);
  const defend = m.datasets.hi_small?.defend;
  if (!defend) throw new Error("fixture report has no Defend section");
  defend.llm = { run: false, reason: "not requested" };
  mockApi({
    "GET /me": () => json(ANALYST),
    "GET /evidence-room/metrics": () => json({ sha256: SHA, metrics: m }),
  });
  renderAt("/evidence-room?tab=defend");
  const rate = await screen.findByRole("group", { name: "Raw LLM hallucination" });
  expect(within(rate).getByText("not run")).toBeInTheDocument();
  expect(within(rate).getByText("not requested")).toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "LLM drafts passing as written" })).toBeNull();
});

it("renders the Decide tab's reliability diagram and coverage", async () => {
  api();
  renderAt("/evidence-room?tab=decide");
  expect(await screen.findByRole("img", { name: /Reliability diagram/ })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Guarantee coverage by day/ })).toBeInTheDocument();
});

it("says plainly when a dataset has not been through a stage", async () => {
  const m = structuredClone(METRICS);
  const li = m.datasets.li_small ?? m.datasets.hi_small;
  if (li) li.defend = null;
  m.datasets.li_small = li!;
  mockApi({
    "GET /me": () => json(ANALYST),
    "GET /evidence-room/metrics": () => json({ sha256: SHA, metrics: m }),
  });
  renderAt("/evidence-room?tab=defend&dataset=li_small");
  expect(await screen.findByText("No verifier results for this dataset")).toBeInTheDocument();
});

it("reports a missing evaluation", async () => {
  mockApi({
    "GET /me": () => json(ANALYST),
    "GET /evidence-room/metrics": () => problem(503, "no-metrics", "No evaluation report yet"),
  });
  renderAt("/evidence-room");
  expect(await screen.findByText("No evaluation report yet")).toBeInTheDocument();
});
