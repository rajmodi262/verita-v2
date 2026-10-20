import { useEffect, useMemo, useState } from "react";

import type { GraphEdge, Subgraph } from "../../api/alerts";
import { cx } from "../../lib/cx";
import { dateTime, money, score, splitAccount } from "../../lib/format";

import { layoutGraph } from "./layout";
import styles from "./TransitMap.module.css";

export interface TransitMapProps {
  graph: Subgraph;
  selectedTxn: number | null;
  onSelectTxn: (txnId: number) => void;
}

const PAD = 110;
const REPLAY_MS = 9000;

/**
 * The money flow as a transit map: accounts are stations, payments are lines run on 45° rails,
 * time runs left to right (layout.ts). Replay runs the payments in their real order; the station
 * the alert is about is the interchange, and the riskiest payment is called out when it arrives.
 * Everything drawn is a payment in the evidence subgraph — the same rows as the table view.
 */
export function TransitMap({ graph, selectedTxn, onSelectTxn }: TransitMapProps) {
  // The shared layout, spread out so station names (account IDs) never collide.
  const positions = useMemo(() => {
    const spread = new Map<string, { x: number; y: number }>();
    for (const [id, p] of layoutGraph(graph.nodes, graph.edges)) {
      spread.set(id, { x: p.x * 2, y: p.y * 1.35 });
    }
    return spread;
  }, [graph]);
  const order = useMemo(
    () => [...graph.edges].sort((a, b) => a.ts.localeCompare(b.ts) || a.txn_id - b.txn_id),
    [graph.edges],
  );
  const riskiest = useMemo(
    () => order.reduce<GraphEdge | null>((m, e) => (m === null || e.score > m.score ? e : m), null),
    [order],
  );
  const [step, setStep] = useState(order.length); // edges shown: 0..n
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing) return undefined;
    const tick = Math.max(REPLAY_MS / Math.max(order.length, 1), 45);
    const id = window.setInterval(() => {
      setStep((s) => {
        if (s >= order.length) {
          setPlaying(false);
          return s;
        }
        return s + 1;
      });
    }, tick);
    return () => {
      window.clearInterval(id);
    };
  }, [playing, order.length]);

  const shown = order.slice(0, step);
  const current = step > 0 && step <= order.length ? order[step - 1] : undefined;
  const visibleStations = new Set(shown.flatMap((e) => [e.from, e.to]));
  if (step === 0) visibleStations.add(graph.center);

  const xs = [...positions.values()].map((p) => p.x);
  const ys = [...positions.values()].map((p) => p.y);
  const minX = Math.min(...xs, 0) - PAD;
  const minY = Math.min(...ys, 0) - PAD;
  const width = Math.max(...xs, 0) - minX + PAD;
  const height = Math.max(...ys, 0) - minY + PAD;

  // Parallel runs between the same pair of stations sit side by side, like tracks.
  const lanes = new Map<string, number>();
  const lane = (e: GraphEdge) => {
    const key = [e.from, e.to].sort().join("|");
    const n = lanes.get(`${key}#${String(e.txn_id)}`);
    if (n !== undefined) return n;
    const used = [...lanes.keys()].filter((k) => k.startsWith(`${key}#`)).length;
    lanes.set(`${key}#${String(e.txn_id)}`, used);
    return used;
  };

  const rail = (e: GraphEdge): string => {
    const a = positions.get(e.from) ?? { x: 0, y: 0 };
    const b = positions.get(e.to) ?? { x: 0, y: 0 };
    const k = lane(e);
    const off = (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 5;
    const dx = b.x - a.x;
    const dy = b.y + off - (a.y + off);
    const diag = Math.min(Math.abs(dx), Math.abs(dy));
    const sx = Math.sign(dx) || 1;
    const sy = Math.sign(dy);
    // straight run first, then the 45° rail into the station (metro-map octilinear routing)
    const midX = b.x - sx * diag;
    const p = (x: number, y: number) => `${x.toFixed(1)} ${y.toFixed(1)}`;
    if (a.x === b.x) return `M${p(a.x + off, a.y)}L${p(b.x + off, b.y)}`;
    return `M${p(a.x, a.y + off)}L${p(midX, a.y + off)}L${p(b.x, a.y + off + sy * diag)}L${p(b.x, b.y + off)}`;
  };

  const lineClass = (e: GraphEdge) =>
    e.on_dominant_path ? styles.trunk : e.flagged ? styles.flagged : styles.branch;

  return (
    <figure className={styles.figure}>
      <svg
        className={styles.map}
        viewBox={`${minX.toFixed(0)} ${minY.toFixed(0)} ${width.toFixed(0)} ${height.toFixed(0)}`}
        role="img"
        aria-label={`Money flow around ${graph.center}: ${String(graph.edges.length)} payments, ${String(shown.length)} shown`}
      >
        {shown.map((e) => (
          <path
            key={e.txn_id}
            d={rail(e)}
            className={cx(
              lineClass(e),
              e === current && styles.arriving,
              e.txn_id === selectedTxn && styles.picked,
            )}
            pathLength={1}
            onClick={() => {
              onSelectTxn(e.txn_id);
            }}
          >
            <title>{`${dateTime(e.ts)} · ${money(e.amount_paid, e.currency_paid)} · score ${score(e.score)}`}</title>
          </path>
        ))}
        {graph.nodes
          .filter((n) => visibleStations.has(n.id))
          .map((n) => {
            const pos = positions.get(n.id) ?? { x: 0, y: 0 };
            const { bank, account } = splitAccount(n.id);
            return (
              <g
                key={n.id}
                className={styles.station}
                transform={`translate(${pos.x.toFixed(1)} ${pos.y.toFixed(1)})`}
              >
                {n.is_center ? <circle className={styles.interchange} r={15} /> : null}
                <circle
                  className={n.max_score >= 0.5 ? styles.stopHot : styles.stop}
                  r={n.is_center ? 9 : 6}
                />
                <text className={styles.name} y={n.is_center ? -26 : -16} fontSize={15}>
                  {account}
                </text>
                <text className={styles.bank} y={n.is_center ? 36 : 26} fontSize={12}>
                  bank {bank}
                </text>
              </g>
            );
          })}
      </svg>

      <figcaption className={styles.controls}>
        <button
          type="button"
          className={styles.play}
          onClick={() => {
            if (step >= order.length) setStep(0);
            setPlaying((p) => !p);
          }}
        >
          {playing ? "Pause" : step >= order.length ? "Replay" : "Play"}
        </button>
        <label className={styles.scrub}>
          <span className={styles.srOnly}>Payments shown</span>
          <input
            type="range"
            min={0}
            max={order.length}
            value={step}
            onChange={(ev) => {
              setPlaying(false);
              setStep(Number(ev.target.value));
            }}
          />
        </label>
        <output className={styles.readout} aria-live="polite">
          {current ? (
            <>
              <span className={styles.clock}>{dateTime(current.ts)}</span>
              <span>
                {money(current.amount_paid, current.currency_paid)} ·{" "}
                {splitAccount(current.from).account} → {splitAccount(current.to).account}
              </span>
              {current === riskiest ? (
                <span className={styles.fires}>Alert fires · score {score(current.score)}</span>
              ) : null}
            </>
          ) : (
            <span>{String(order.length)} payments — press play to run them in order</span>
          )}
        </output>
      </figcaption>
      <ul className={styles.legend}>
        <li className={styles.legendTrunk}>Dominant path</li>
        <li className={styles.legendFlagged}>Flagged payment</li>
        <li className={styles.legendBranch}>Other payment</li>
      </ul>
    </figure>
  );
}
