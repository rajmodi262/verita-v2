# Defend it — the panel questions

Forty questions a financial-crime-compliance panel is likely to ask about Verita, each with a
short model answer and the place in the code where the answer lives. Paths are relative to the
repository root; line numbers point at the function or block that does the work.

No figure in this file is typed by hand. Every result (detection quality, calibration, coverage,
planner gains, latency) is generated from `reports/metrics.json` into
[`reports/EVAL_REPORT.md`](../reports/EVAL_REPORT.md) and shown live in the app's **Evidence
Room** (`GET /api/v1/evidence-room/metrics`, `backend/verita/api/routers/evidence_room.py:20`).
When asked "how good is it?", open the Evidence Room rather than quoting from memory.

---

## 1. Data and leakage

**Q1. What data is this trained on, and why should I believe results on synthetic data?**
The IBM AML synthetic transaction sets (HI-Small and LI-Small). They are the only public data
with transaction-level laundering labels *and* the laundering pattern each one belongs to, which
is what lets every alert be traced to a typology. Synthetic data cannot prove production
performance; it proves the method is honest and reproducible. The raw files are pinned by hash
(`configs/data_manifest.yaml`, checked by `backend/verita/pipeline/verify.py:36`) and documented
in `DATA_CARD.md`.

**Q2. How did you split the data, and why not a random split?**
By time, cut at fixed fractions of the transaction *count*: train, then hpo (model selection),
then calib (calibration and conformal), then test, in that order
(`backend/verita/pipeline/splits.py:1`, `compute_splits` at `:100`). A random split lets the
model see the future of the same laundering ring it is tested on. The cut is by count, not by
time span, because the IBM files end in a sparse tail that is mostly laundering; a span cut would
put the entire test set inside that tail.

**Q3. Can you show me what a random split would have claimed?**
Yes — the pipeline trains the same model on a random split and reports the gap
(`_random_split_check`, `backend/verita/ml/detect.py:456`). The temporal-vs-random comparison
is in the Evidence Room under the sanity checks.

**Q4. How do you know no feature peeks into the future?**
Every rolling feature is a DuckDB window that ends *one minute before* the transaction
(`RANGE BETWEEN … PRECEDING AND INTERVAL 1 MINUTE PRECEDING`,
`backend/verita/ml/features.py:112`). This is enforced by a property test: random future events
are appended and the features of every earlier transaction must not change
(`backend/tests/ml/test_features_asof.py:64`); same-minute activity is invisible
(`:91`); a cycle feature fires only once the cycle has actually closed (`:98`).

**Q5. What is the label-shuffle test?**
Train the champion on shuffled labels; its test PR-AUC must collapse to roughly the base rate
(`backend/verita/ml/detect.py:405`). If it does not, something other than the label is carrying
signal — leakage. The model-risk policy turns this into a gate
(`configs/model_policy.yaml`, `max_shuffled_pr_auc_over_base_rate`).

**Q6. Where does the laundering label come from — transaction, account, or pattern?**
Transaction labels come from the IBM files; each laundering transaction is linked to the pattern
it belongs to (`backend/verita/pipeline/patterns.py`). Unlinked laundering is counted, not
dropped (`backend/tests/pipeline/test_patterns_graph_splits.py:121`), and an alert built from
unattributed laundering must say so in its narrative (`backend/tests/defend/test_verifier.py:157`).

## 2. Detection model

**Q7. Why LightGBM and not a graph neural network?**
Tabular gradient boosting on well-engineered windowed and graph features is fast, stable across
seeds, explainable with exact TreeSHAP, and cheap to retrain and validate. A GNN is a
challenger, not the champion, until it beats LightGBM under the same temporal split and passes
the same gates. Reasoning in `docs/adr/ADR-004-lightgbm-champion.md`.

**Q8. What is the incumbent you compare against?**
A rules engine of classic transaction-monitoring typologies (`rules_score`,
`backend/verita/ml/detect.py:200`), with its alert threshold chosen on the hpo split
(`:349`). The champion has to beat it outright — its interval must sit above the incumbent's —
before a validator may approve it (`configs/model_policy.yaml`, `beats_incumbent`).

**Q9. How were hyper-parameters chosen without touching the test set?**
Optuna searches on train → hpo only (`tune`, `backend/verita/ml/detect.py:169`); the decision
threshold is the best-F1 point on hpo (`backend/verita/ml/evaluation.py:49`). The test split is
read only by the evaluation stage.

**Q10. Your intervals — how are they computed, and why blocks?**
Block bootstrap over time blocks of the test split (`time_blocks` and `summarize_binary`,
`backend/verita/ml/evaluation.py:78` and `:184`). Laundering arrives in bursts; resampling
single transactions would treat a ring's many payments as independent evidence and produce
intervals that are too narrow.

**Q11. Is the result a lucky seed?**
The champion is retrained over several seeds and the spread is reported
(`backend/verita/ml/detect.py:362`); the policy caps the allowed spread
(`max_f1_std_over_seeds`).

**Q12. Which features matter, and how do you know a group earns its place?**
Global TreeSHAP ranks features (`backend/verita/ml/detect.py:423`). Each feature group is also
ablated and the paired bootstrap difference against the champion is reported
(`:377`, `bootstrap_paired_delta_f1` at `backend/verita/ml/evaluation.py:104`).

**Q13. How do you handle the class imbalance?**
Negatives are subsampled for training, and the pipeline reports the alternatives side by side —
all data with `scale_pos_weight`, and all data unweighted (`backend/verita/ml/detect.py:392`).
Imbalance handling is an empirical choice, so the evidence is shown rather than asserted.

**Q14. How does an analyst see *why* an alert fired?**
Per-alert TreeSHAP contributions are turned into plain-English reasons from templates
(`top_reasons`, `backend/verita/ml/reasons.py:112`) — "received from 7 new payers in 24 hours",
not "feature_17 = 0.83".

**Q15. Is the score a probability?**
After isotonic calibration on the calib split, yes in the reliability sense
(`backend/verita/ml/conformal.py:45`, applied in `backend/verita/ml/decide.py:116`). Expected
calibration error before and after is in the Evidence Room, and the policy gates it.

## 3. Decide: conformal guarantee and ACI

**Q16. What exactly does "recall guarantee" mean here?**
A split-conformal threshold on the scores of calibration *positives*: the threshold is the
order statistic that a new positive exceeds with probability at least 1 − α, assuming
exchangeability (`conformal_threshold`, `backend/verita/ml/conformal.py:95`). It is a marginal
statement about laundering alerts, not a promise about every case. ADR:
`docs/adr/ADR-005-conformal-recall-guarantee.md`.

**Q17. What if there are too few positives to calibrate?**
Then no alert can be excluded and the threshold is "review everything"
(`backend/verita/ml/conformal.py:105`, test at `backend/tests/ml/test_conformal.py:31`). The
system refuses to manufacture confidence it does not have.

**Q18. Per-typology guarantees?**
Mondrian conformal: one threshold per typology when there are enough calibration positives,
falling back to the pooled threshold otherwise, and the fallback groups are listed
(`fit_thresholds`, `backend/verita/ml/conformal.py:133`; minimum group size `MIN_GROUP` at
`:38`).

**Q19. Exchangeability breaks under drift. What then?**
Adaptive conformal inference: the working α is nudged by every revealed miss,
`α_t ← α_t + γ(α − err)`, using labels only once their investigation delay has elapsed
(`replay_aci`, `backend/verita/ml/conformal.py:220`). The replay compares static and adaptive
coverage on the drifting tail days, and a delay-sensitivity table shows what happens when labels
come back later (`backend/verita/ml/decide.py:157`).

**Q20. How do you detect drift in the first place?**
PSI per feature per day with equal-mass bins (`backend/verita/ml/drift.py:16`), on the features
that are not time-anchored (`backend/verita/ml/decide.py:210`). Days with too few rows for PSI to
mean anything are listed, not gated (`min_rows_for_drift` in `configs/model_policy.yaml`).

## 4. Capacity planning (CP-SAT)

**Q21. What does the planner optimise?**
Given today's alerts, analyst-minutes and per-typology handling times
(`configs/operations.yaml`), it chooses which alerts to work: every alert the conformal guarantee
requires is forced in, and spare capacity maximises expected laundering caught (Σp) or expected
dollars caught (Σp·v) (`plan_day`, `backend/verita/optimize/planner.py:233`).

**Q22. Why CP-SAT and not a greedy sort by score?**
It is a 0/1 knapsack; greedy-by-density is not optimal when handling times differ
(`_knapsack_cpsat`, `backend/verita/optimize/planner.py:133`; the counter-example test is
`backend/tests/ml/test_planner.py:60`). Handling times are kept in tenths of a minute so integer
rounding does not silently shrink capacity (`:141`), and a large day must never lose to greedy
(`backend/tests/ml/test_planner.py:165`).

**Q23. What if the guarantee cannot be met with the staff available?**
The plan says so and reports how many analysts would be needed
(`backend/tests/ml/test_planner.py:93`). The capacity frontier shows the trade-off across
staffing levels, backtested against the true labels (`frontier`,
`backend/verita/optimize/planner.py:312`).

**Q24. Isn't CP-SAT too slow for a big day?**
A candidate pool keeps the forced alerts and the densest others (`candidate_pool`, `:210`),
the solver has a time cap (`SOLVER_SECONDS`, `:35`), and on timeout it still returns the best
feasible plan. The plan names which solver produced it (`backend/tests/ml/test_planner.py:130`).

## 5. Defend: signed case files

**Q25. What is actually signed?**
The case file is a set of named items (evidence, narrative, verification report, approvals).
Each is canonicalised with RFC 8785 JCS, hashed into a Merkle tree, and the Ed25519 signature
covers `verita-case-v1:<case id>:<root>` — domain-tagged, so a signature cannot be replayed
for another case or format (`message`, `backend/verita/defend/signing.py:28`;
document assembly in `backend/verita/services/cases.py:422`). ADR:
`docs/adr/ADR-006-signed-case-files.md`.

**Q26. Why JCS? Why not just `json.dumps(sort_keys=True)`?**
Two systems must produce identical bytes for the same value, or signatures fail across
languages. JCS fixes number formatting to ECMAScript rules and sorts keys by UTF-16 code units;
Python's defaults do neither (`backend/verita/defend/canonical.py:51`, `:80`). Tested against the
RFC's own example and every double bit pattern (`backend/tests/defend/test_crypto.py:20`, `:77`).

**Q27. Why a Merkle tree instead of hashing the whole document?**
Selective disclosure and precise tamper reports: one item can be proven to belong to a signed
case without revealing the others (`MerkleTree.proof`, `backend/verita/defend/merkle.py:76`),
and a tampered file names exactly which items changed (`changed_leaves`, `:90`). Leaves and
nodes are domain-separated (`0x00` / `0x01` prefixes, `:21`) so a node cannot be passed off as
a leaf.

**Q28. Who can verify a case file, and do they need your system?**
Anyone with the public key, offline: `verita-verify case.json --pubkey verita-pub.pem` checks
the signature, rebuilds the root and names changed leaves — no network, database or server
(`backend/verita/defend/verify_cli.py:1`; service path
`verify_export`, `backend/verita/services/cases.py:516`). The demo exports a deliberately
tampered copy to show the failure (`backend/verita/api/routers/cases.py:161`).

**Q29. How is the case history protected?**
Every state transition appends to a hash-chained ledger: each event hashes the previous hash
plus its own body (`backend/verita/services/ledger.py:43`), and the chain is re-verified on
demand (`verify_chain`, `:83`).

**Q30. What stops one person from writing and approving their own SAR?**
Maker-checker: only an MLRO approves, and never the person who created or submitted the case
(`approval_blockers`, `backend/verita/services/cases.py:408`).

**Q31. Key management?**
The demo keeps an Ed25519 key on disk and publishes the public key and key ID
(`Signer.load_or_create`, `backend/verita/defend/signing.py:77`). In a bank the private key lives
in an HSM or cloud KMS, signing is a KMS call, and the key ID in each case file lets old cases
verify after rotation.

## 6. The narrative verifier and the LLM

**Q32. The narrative is LLM-written. How do you stop hallucinations reaching a regulator?**
A deterministic verifier checks every sentence: it must cite evidence that exists in the case,
and every amount, count, date, duration, account, bank, typology and percentage it states must
match a fact of the *cited* item — citing the wrong item fails
(`backend/verita/defend/verifier.py:1`, matching rules at `:104`). The narrative must also cover
the dominant path, total, date range and typology. No model is consulted, so the report itself
can be signed.

**Q33. How do you know the verifier catches errors?**
Fault injection: wrong amounts, wrong dates, swapped accounts, invented counterparties, wrong
typology, wrong counts, uncited and irrelevant sentences are planted into correct narratives,
and every one must be caught (`inject`, `backend/verita/defend/faults.py:217`; test at
`backend/tests/defend/test_verifier.py:168`). The raw hallucination rate of the live LLM, before
verification, is published in the Evidence Room.

**Q34. What are the verifier's limits?**
It matches *values*, not *roles*. "A paid B $5,000" and "B paid A $5,000" both pass if the
cited payment is $5,000 between A and B; it does not parse who did what to whom. It also cannot
judge whether the reasoning is sound — only that the facts stated are true of the evidence
cited. That is why a human MLRO still approves every case; the verifier makes the review faster
and catches fabricated facts, it does not replace judgement.

**Q35. What happens when the LLM provider fails or rate-limits?**
Keys are pooled per provider with cooldowns parsed from the provider's own errors
(`backend/verita/defend/keypool.py:182`), and an offline template narrative always exists, so a
case can be drafted with no LLM at all.

## 7. Governance, security and operations

**Q36. How does a new model get into production?**
Candidate → validated against the policy gates → approved by a validator → promoted by an MLRO
(`backend/verita/services/models.py:107`, `:135`, `:199`). The validation report reads only
artifacts the pipeline already produced, and refuses artifacts of a different model
(`build_report`, `backend/verita/ml/validation.py:101`).

**Q37. What if someone bypasses the API and writes to the database?**
The database refuses it: a champion must have an approver and a promoter who are different
people, or carry an explicit, displayed bypass reason (`CHAMPION_REVIEWED_CHECK`,
`backend/verita/db/detect_models.py:69`; test at
`backend/tests/integration/test_model_governance.py:162`). The development pipeline uses that
bypass openly (`backend/verita/ml/alerts.py:155`) and is refused in production
(`backend/tests/integration/test_model_governance.py:228`).

**Q38. How is access controlled?**
Four roles (analyst, MLRO, validator, reviewer). Every mutating route requires a CSRF-checked
session with an allowed role (`csrf_role`, `backend/verita/api/deps.py:64`), and an
authorization matrix test enumerates every route × role
(`backend/tests/integration/test_authz_matrix.py`). Threats are in `docs/THREAT_MODEL.md`.

**Q39. Why can't analysts run their own SQL against the data?**
Because an ad-hoc query is an unaudited data-access path and an injection surface; analysts get
purpose-built, logged views instead. `docs/adr/ADR-007-no-user-sql.md`.

## 8. Scale

**Q40. How would this scale to a bank with hundreds of millions of transactions a day?**
- *Scoring* is batch and embarrassingly parallel (`docs/adr/ADR-001-batch-scoring.md`);
  LightGBM inference latency per 10k rows is measured in the Evidence Room. Partition by
  account hash and score in parallel workers.
- *Features* are windowed SQL; DuckDB on one machine today, the same windows map to Spark or
  Flink for streaming (`docs/adr/ADR-002-duckdb-and-postgres.md`).
- *Graph features* (cycles) are bounded by window and hop count, so they stay local to an
  account's recent neighbourhood rather than the whole graph.
- *Jobs* use a Postgres queue today (`docs/adr/ADR-003-postgres-job-queue.md`); at bank scale,
  a managed queue with the same idempotent job contract.
- *Planning* is per day and per team, so CP-SAT problems stay small; the candidate pool bounds
  them further.
- *Governance and signing* do not change with volume: they act on models and cases, not on
  transactions.
- What would change: a KMS for signing keys, data-residency controls, an independent model-risk
  sign-off process, and validation on the bank's own labelled history before any claim is made.
