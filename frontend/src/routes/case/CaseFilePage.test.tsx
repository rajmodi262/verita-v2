import { readFileSync } from "node:fs";
import { join } from "node:path";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CASE_META, caseDetail, job, SENTENCES } from "../../test/caseFixtures";
import type { Handler } from "../../test/utils";
import { ANALYST, json, mockApi, renderAt } from "../../test/utils";

const MLRO = { id: 2, username: "marcus", role: "mlro" } as const;
const fixture = (name: string) =>
  readFileSync(join(__dirname, "../../test/fixtures", name), "utf-8");
const PUB = (JSON.parse(fixture("case-export.json")) as { public_key_pem: string }).public_key_pem;

function api(routes: Record<string, Handler>, user: object = ANALYST) {
  return mockApi({
    "GET /me": () => json(user),
    "GET /cases/meta": () => json(CASE_META),
    "GET /keys": () =>
      json({
        keys: [
          {
            key_id: "k".repeat(16),
            algorithm: "Ed25519",
            public_key_pem: PUB,
            created_at: "2022",
            message_format: "verita-case-v1:<case_id>:<merkle_root_hex>",
          },
        ],
      }),
    ...routes,
  });
}

it("drafts through a real job and shows the verified narrative", async () => {
  const user = userEvent.setup();
  let drafted = false;
  const empty = caseDetail({ narrative: null, verification: null, state: "draft" });
  const { calls } = api({
    "GET /cases/1": () => json(drafted ? caseDetail() : empty),
    "POST /cases/1/narrative": () => json(job("queued"), 202),
    "GET /jobs/5": () => {
      drafted = true;
      return json(job("done"));
    },
  });
  renderAt("/cases/1");
  expect(await screen.findByText("No narrative yet")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Draft narrative" }));
  expect(await screen.findByText(/totalling 30,546.75 US Dollar/)).toBeInTheDocument();
  const post = calls.find((c) => c.key === "POST /cases/1/narrative");
  expect(JSON.parse(post?.init.body as string)).toEqual({ mode: "offline" });
  expect(screen.getAllByText("Verified").length).toBeGreaterThan(0);
  const narrative = screen.getByRole("region", { name: "Narrative" });
  expect(within(narrative).getByRole("button", { name: "EV-TXN-101" })).toBeInTheDocument();
});

it("highlights the failing claim and blocks submission", async () => {
  api({ "GET /cases/1": () => json(caseDetail({}, true)) });
  renderAt("/cases/1");
  const mark = await screen.findByText("9,800.00 US Dollar", { selector: "mark" });
  expect(mark).toHaveTextContent("(does not match the evidence)");
  expect(screen.getByText(/cited evidence says amount 9500.0 US Dollar/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Submit for approval" })).toBeDisabled();
  expect(screen.getByText(/blocked until every sentence passes/)).toBeInTheDocument();
  expect(screen.getByText(/Missing the typology/)).toBeInTheDocument();
});

it("selecting a citation previews the evidence it points to", async () => {
  const user = userEvent.setup();
  api({ "GET /cases/1": () => json(caseDetail()) });
  renderAt("/cases/1");
  const narrative = await screen.findByRole("region", { name: "Narrative" });
  await user.click(within(narrative).getByRole("button", { name: "EV-TXN-101" }));
  const preview = screen.getByRole("region", { name: "Evidence EV-TXN-101" });
  expect(within(preview).getByText("amount_paid")).toBeInTheDocument();
  expect(within(preview).getByText("9800")).toBeInTheDocument();
});

it("explains maker-checker when the MLRO cannot approve", async () => {
  api(
    {
      "GET /cases/1": () =>
        json(
          caseDetail({
            state: "submitted",
            permissions: {
              edit: false,
              submit: false,
              approve: false,
              approve_blockers: [
                "Maker-checker: you created this case, so someone else must approve it.",
              ],
              return: true,
              close: true,
            },
          }),
        ),
    },
    MLRO,
  );
  renderAt("/cases/1");
  const approve = await screen.findByRole("button", { name: "Approve and sign" });
  expect(approve).toBeDisabled();
  expect(screen.getByText(/Maker-checker: you created this case/)).toBeInTheDocument();
});

it("approves, signs and shows the seal with exports", async () => {
  const user = userEvent.setup();
  const submitted = caseDetail({
    state: "submitted",
    permissions: {
      edit: false,
      submit: false,
      approve: true,
      approve_blockers: [],
      return: true,
      close: true,
    },
  });
  const signed = caseDetail({
    state: "signed",
    signature: {
      merkle_root: "ef".repeat(32),
      key_id: "k".repeat(16),
      signed_by: "marcus",
      signed_at: "2022-09-12T10:00:00+00:00",
    },
    permissions: {
      edit: false,
      submit: false,
      approve: false,
      approve_blockers: [],
      return: false,
      close: false,
    },
  });
  const { calls } = api(
    {
      "GET /cases/1": () => json(submitted),
      "POST /cases/1/approve": () => json(signed),
      "GET /cases/1/verify-signature": () =>
        json({
          valid: true,
          signature_valid: true,
          root_matches: true,
          recomputed_root: "ef".repeat(32),
          changed_leaves: [],
          ledger: { valid: true, broken_at: null, reason: null },
        }),
    },
    MLRO,
  );
  renderAt("/cases/1");
  await user.click(await screen.findByRole("button", { name: "Approve and sign" }));
  expect(await screen.findByText("Signed case file")).toBeInTheDocument();
  expect(await screen.findByText(/signature, root and ledger verified/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download signed JSON" })).toHaveAttribute(
    "href",
    "/api/v1/cases/1/export.json",
  );
  expect(screen.getByRole("link", { name: /tampered copy/ })).toHaveAttribute(
    "href",
    "/api/v1/cases/1/export-tampered.json",
  );
  expect(calls.some((c) => c.key === "POST /cases/1/approve")).toBe(true);
});

it("verifies a dropped file in the browser and names the tampered leaf", async () => {
  const user = userEvent.setup();
  const signed = caseDetail({
    state: "signed",
    signature: {
      merkle_root: "ef".repeat(32),
      key_id: "k".repeat(16),
      signed_by: "marcus",
      signed_at: "2022",
    },
    permissions: {
      edit: false,
      submit: false,
      approve: false,
      approve_blockers: [],
      return: false,
      close: false,
    },
  });
  api({
    "GET /cases/1": () => json(signed),
    "GET /cases/1/verify-signature": () =>
      json({
        valid: true,
        signature_valid: true,
        root_matches: true,
        recomputed_root: "x",
        changed_leaves: [],
        ledger: { valid: true, broken_at: null, reason: null },
      }),
  });
  renderAt("/cases/1");
  const input = await screen.findByLabelText(/Drop a case-file JSON here/);
  await screen.findByText(/published key \(loaded\)/);
  await user.upload(
    input,
    new File([fixture("case-export.json")], "case-42.json", { type: "application/json" }),
  );
  expect(await screen.findByText("Valid")).toBeInTheDocument();
  await user.upload(
    input,
    new File([fixture("case-export-tampered.json")], "case-42-TAMPERED.json", {
      type: "application/json",
    }),
  );
  expect(await screen.findByText("Invalid")).toBeInTheDocument();
  expect(screen.getByText("EV-TXN-102")).toBeInTheDocument();
  expect(screen.getByText(/does not match the signed root/)).toBeInTheDocument();
});

it("injects a demo fault by editing one amount", async () => {
  const user = userEvent.setup();
  const { calls } = api({
    "GET /cases/1": () => json(caseDetail()),
    "PUT /cases/1/narrative": () => json(caseDetail({}, true)),
  });
  renderAt("/cases/1");
  await user.click(await screen.findByRole("button", { name: "Inject a fault (demo)" }));
  expect(
    await screen.findByText(/Injected a fault: 9,800.00 → 10,094.00 in sentence 2/),
  ).toBeInTheDocument();
  const put = calls.find((c) => c.key === "PUT /cases/1/narrative");
  const body = JSON.parse(put?.init.body as string) as { sentences: typeof SENTENCES };
  expect(body.sentences[1]?.text).toContain("10,094.00 US Dollar");
  expect(body.sentences[0]).toEqual(SENTENCES[0]);
});

it("edits sentences and saves for re-verification", async () => {
  const user = userEvent.setup();
  const { calls } = api({
    "GET /cases/1": () => json(caseDetail()),
    "PUT /cases/1/narrative": () => json(caseDetail()),
  });
  renderAt("/cases/1");
  await user.click(await screen.findByRole("button", { name: "Edit narrative" }));
  const boxes = screen.getAllByLabelText("Text");
  await user.clear(boxes[0]!);
  await user.type(boxes[0]!, "Rewritten.");
  await user.click(screen.getByRole("button", { name: "Save and re-verify" }));
  await waitFor(() => {
    expect(calls.some((c) => c.key === "PUT /cases/1/narrative")).toBe(true);
  });
  const put = calls.find((c) => c.key === "PUT /cases/1/narrative");
  expect(
    (JSON.parse(put?.init.body as string) as { sentences: { text: string }[] }).sentences[0]?.text,
  ).toBe("Rewritten.");
});

it("returns a case with a reason code", async () => {
  const user = userEvent.setup();
  const submitted = caseDetail({
    state: "submitted",
    permissions: {
      edit: false,
      submit: false,
      approve: true,
      approve_blockers: [],
      return: true,
      close: true,
    },
  });
  const { calls } = api(
    {
      "GET /cases/1": () => json(submitted),
      "POST /cases/1/return": () => json(caseDetail({ state: "returned" })),
    },
    MLRO,
  );
  renderAt("/cases/1");
  await user.click(await screen.findByRole("button", { name: "Return to analyst" }));
  const dialog = await screen.findByRole("dialog");
  await user.selectOptions(within(dialog).getByLabelText("Reason"), "narrative_unclear");
  await user.click(within(dialog).getByRole("button", { name: "Return to analyst" }));
  await waitFor(() => {
    expect(calls.some((c) => c.key === "POST /cases/1/return")).toBe(true);
  });
  const post = calls.find((c) => c.key === "POST /cases/1/return");
  expect(JSON.parse(post?.init.body as string)).toEqual({ reason: "narrative_unclear", note: "" });
});

it("lists case files", async () => {
  api({
    "GET /cases": () =>
      json({
        items: [
          {
            id: 1,
            title: "Fan-out",
            state: "signed",
            created_by: "priya",
            updated_at: "2022-09-12T10:00:00",
            alerts: 1,
          },
        ],
      }),
  });
  renderAt("/cases");
  expect(await screen.findByRole("link", { name: "C-1" })).toHaveAttribute("href", "/cases/1");
  expect(screen.getByText("Signed")).toBeInTheDocument();
});
