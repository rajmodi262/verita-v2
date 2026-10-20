# Demo script

A seven-minute walkthrough of Detect → Decide → Defend for a reviewer, on the HI-Small demo
pack. Every number on screen comes from `reports/metrics.json` or the live API; read them off
the screen rather than from this script, which deliberately quotes none.

## Before you start

```bash
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml run --rm api verita users seed-demo   # prints the demo password once
cd backend && VERITA_DEMO_PASSWORD=... uv run python scripts/smoke.py http://localhost:8080
```

Open <http://localhost:8080> in one window and keep a terminal ready for the offline verifier.
The smoke test leaves one signed case behind; that is fine. Have two browser profiles (or one
private window) so the analyst and the MLRO can be signed in side by side.

## 0:00 — The claim (landing page)

* Read the three-line headline: every alert explained, every miss quantified, every report
  provable. The figures beneath it are fetched live from the Evidence Room endpoint — point out
  that the page has no numbers typed into it.
* For a self-guided visit, sign in as `reviewer`: that role gets a read-only guided tour of
  every screen. For the live walkthrough below, sign in as `analyst`.

## 0:45 — Detect (queue → investigation), signed in as `analyst`

1. **Queue.** Alerts for the selected day, ranked by calibrated probability. Press `j`/`k` to
   move, `Enter` to open, `d` to disposition and `?` for every shortcut — the queue is
   keyboard-first.
2. **Investigation.** Show *Why this is an alert* (SHAP contributions in plain words), then the
   evidence subgraph: the money flow around the account, precomputed into the demo pack.
3. Say what the model is *not*: the Evidence Room compares it with the published GFP + LightGBM
   baseline, and ours is lower. The point of Verita is what happens after the score.

## 2:00 — Decide (capacity planner)

1. Open **Capacity**. Pick a bulk day, set the analyst count, and move the recall-guarantee
   slider (α).
2. The planner (CP-SAT) chooses which alerts to review so that the conformal guarantee holds
   with the staff available — or says plainly that it cannot, and how many analysts it would
   take. That refusal is a feature: it is the number a compliance lead needs to see.
3. Mention adaptive conformal (ACI): the Evidence Room shows realised recall against the
   guarantee over time.

## 3:30 — Defend (case file), still `analyst`

1. From the investigation, **Open a case file**, then **Draft narrative** (drafting runs as a
   job on the worker; offline mode needs no LLM key). The verifier runs on the draft: every
   claim is checked against the evidence, and the case shows *Verified*.
2. **Inject a fault (demo)** plants a wrong number in one sentence, as an LLM might. The claim
   is highlighted as not matching the evidence and **Submit for approval** is disabled.
   **Redraft narrative** and it verifies again.
3. **Submit for approval.** The analyst cannot approve at all; even an MLRO who opened a case
   sees *Approve and sign* disabled for it, and the API refuses too (maker-checker).

## 5:00 — Sign and prove it, as `mlro`

1. In the second window, sign in as `mlro`, open the case, **Approve and sign**. The page shows
   the signed case file, the server check (signature, root and ledger verified) and *Chain
   intact*; the ledger gains a `case.signed` event. The signature covers the case's Merkle root.
2. **Download signed JSON**, and the tampered copy next to it. Drop each onto *Verify a file*:
   the browser recomputes the Merkle root with WebCrypto and checks the Ed25519 signature
   against the published key, with no server involved. The genuine file is *Valid*; the
   tampered one is *Invalid* and names the exhibit that changed since signing.
3. The same check offline, as a third party would run it:

   ```bash
   curl -s http://localhost:8080/api/v1/keys | jq -r '.keys[0].public_key_pem' > verita-pub.pem
   cd backend && uv run verita-verify ~/Downloads/case-<id>.json --public-key ../verita-pub.pem
   ```

## 6:15 — Evidence Room

* Open **Evidence Room**: the Detect, Decide and Defend tabs show every headline figure with its
  confidence interval, the robustness result on LI-Small, and the limitations. Nothing on the
  page is computed in the browser; it renders the generated report, and CI fails if any doc or
  screen hand-types a metric.

## Questions this demo invites

| Question | Where to go |
|---|---|
| "How do you know there's no leakage?" | Evidence Room → Detect → sanity checks; `reports/EVAL_REPORT.md` |
| "Why trust the recall guarantee?" | Evidence Room → Decide → coverage over time; ADR-005 |
| "How do you stop the LLM inventing things?" | Evidence Room → Defend → fault-injection results |
| "How would this run at a bank?" | ADR-001/002/003/008, `docs/THREAT_MODEL.md`, `docs/RUNBOOK.md` |
| "What can't it do?" | `reports/MODEL_CARD.md` limitations; THREAT_MODEL residual risks |

## If something goes wrong

* **Queue empty / 503:** the demo pack did not load — `docker compose … logs migrate`.
* **Narrative stuck on "queued":** the worker is down — `docker compose … up -d worker`.
* **Anything else:** RUNBOOK.md → Recovery.
