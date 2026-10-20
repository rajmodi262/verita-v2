# Design system: Intaglio

Verita's interface borrows the language of **security printing** — banknotes, passports, share
certificates: the oldest design system built to make forgery visible. That is the product's own
promise (tamper-evident case files), so the identity is not decoration; it is the argument.

The principles from the earlier "Forensic Ledger" brief still hold: show the work, make
integrity visible, never animate state that did not happen, and meet **WCAG AAA** (7:1 body text)
in both themes. The visual execution is new.

## Tokens (`frontend/src/styles/tokens.css`)

The only file with raw colours and sizes (Stylelint enforces it); `contrast.test.ts` checks every
text/ground pair for 7:1 and every mark for 3:1.

| Role | Paper (light) | Vault (night) |
|---|---|---|
| Ground / surface | security-paper green-grey | deep green-black |
| Ink | banknote green-black | engraved pale green |
| Alert | currency red | signal red |
| Guilloché line | `--color-guilloche` | `--color-guilloche` |
| Foil | `--color-foil-1..3` — the seal medallion only | same |

Type: **Bodoni Moda** (engraved page titles, serials), **Schibsted Grotesk** (interface and
body), **Martian Mono** (hashes, amounts, identifiers). Labels are small caps, not tracked mono
capitals. Panels carry an engraved double rule instead of drop shadows.

## Signature components

- **Guilloché seal** (`components/seal/GuillocheSeal.tsx`) — a rosette whose curves are seeded by
  the case's Merkle root, one sector per leaf. A tampered exhibit breaks its sector out of the
  ring, cracked and inked red. Every signed case has its own seal.
- **Transit map** (`components/graph/TransitMap.tsx`) — the evidence subgraph as a metro map:
  accounts are stations, payments run on 45° rails, time flows left to right; replay runs the
  payments in order and calls out the riskiest one.
- **Risk tape** (`components/charts/RiskTape.tsx`) — alerts per day as engraved strokes; click
  to filter the queue.
- **Staffing frontier** (`components/charts/FrontierChart.tsx`) — drag to staff the day; the
  region where the recall guarantee cannot hold is hatched.
- **Evidence threads** (`components/case/EvidenceThreads.tsx`) — reading a narrative sentence
  draws ink threads to the exhibits it cites.
- **Gate certificates** (`routes/governance/GovernancePage.tsx`) — each model-risk gate as a
  certificate with its measured value and limit, under a lifecycle rail.

## Rules

1. **Every mark is data.** Seal sectors are Merkle leaves, rails are payments, tape strokes are
   alert counts, certificates are gate results. Nothing is ornamental filler.
2. **Foil once.** The iridescent foil appears only on the seal medallion.
3. **Motion demonstrates.** Engraving, replay and threads animate real state, and all motion
   honours `prefers-reduced-motion`.
4. **No hand-typed metrics.** Screens render API data; `verita report scan` guards the docs.
