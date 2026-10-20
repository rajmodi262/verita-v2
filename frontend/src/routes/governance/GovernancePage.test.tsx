import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { json, mockApi, renderAt } from "../../test/utils";

const VALIDATOR = { id: 3, username: "vera", role: "validator" } as const;

function model(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: "lgbm_champion",
    dataset: "hi_small",
    status: "candidate",
    is_champion: false,
    champion_sha256: "c".repeat(64),
    git_revision: null,
    threshold: 0.61,
    created_at: "2026-10-20T18:44:00Z",
    proposed_by: "pipeline",
    validation: null,
    approved_by_id: null,
    approved_at: null,
    promoted_by_id: null,
    promoted_at: null,
    decision_note: null,
    governance: "not reviewed",
    bypass_reason: null,
    ...overrides,
  };
}

const REPORT = {
  passed: false,
  gates: [
    {
      gate: "beats_incumbent",
      passed: true,
      value: true,
      limit: true,
      rule: "champion above incumbent",
    },
    { gate: "calibration", passed: false, value: 0.031, limit: 0.02, rule: "ECE ≤ limit" },
    { gate: "custom_gate", passed: true, value: null, limit: [1, 2], rule: "made up" },
  ],
};

it("shows the lifecycle, the gate certificates and lets a validator run validation", async () => {
  const user = userEvent.setup();
  const { calls } = mockApi({
    "GET /me": () => json(VALIDATOR),
    "GET /models": () => json({ items: [model()] }),
    "GET /models/1": () => json({ ...model(), report: null }),
    "POST /models/1/validate": () =>
      json({
        ...model({
          validation: {
            passed: false,
            sha256: "d".repeat(64),
            policy_version: 1,
            failed_gates: ["calibration"],
          },
        }),
        report: REPORT,
      }),
  });
  renderAt("/models");
  expect(await screen.findByRole("heading", { name: "Model governance" })).toBeInTheDocument();
  expect(await screen.findByText("Awaiting the validator")).toBeInTheDocument();
  expect(screen.getByText(/Not validated yet/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Promote to service" })).toBeDisabled();

  await user.click(screen.getByRole("button", { name: "Run validation" }));
  expect(calls.some((c) => c.key === "POST /models/1/validate")).toBe(true);
  expect(await screen.findByText("1 gate(s) failed")).toBeInTheDocument();
  expect(screen.getByText("Beats the rules incumbent outright")).toBeInTheDocument();
  expect(screen.getByText("Calibrated probabilities")).toBeInTheDocument();
  expect(screen.getByText("custom_gate")).toBeInTheDocument();
  expect(screen.getByText("0.0310")).toBeInTheDocument();
  expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
});

it("marks a model put into service without review", async () => {
  mockApi({
    "GET /me": () => json(VALIDATOR),
    "GET /models": () => json({ items: [model({ status: "champion", governance: "bypassed" })] }),
    "GET /models/1": () =>
      json({
        ...model({
          status: "champion",
          is_champion: true,
          governance: "bypassed",
          bypass_reason: "Synthetic demo pack",
          validation: { passed: true, sha256: "e".repeat(64), policy_version: 1, failed_gates: [] },
        }),
        report: { passed: true, gates: [] },
      }),
  });
  renderAt("/models");
  expect(await screen.findByText("Not independently reviewed")).toBeInTheDocument();
  expect(screen.getByText("Seated by the pipeline")).toBeInTheDocument();
  expect(screen.getByText(/hi_small · champion · bypassed/)).toBeInTheDocument();
});
