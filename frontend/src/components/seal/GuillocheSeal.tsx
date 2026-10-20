import { useId, useMemo } from "react";

import styles from "./GuillocheSeal.module.css";

/**
 * The case seal: a guilloché rosette engraved from the case's Merkle root.
 *
 * Security printing (banknotes, passports) uses guilloché — interlaced curves too fine to forge.
 * Here the curves are seeded by the root hash, so every signed case has its own seal, and the
 * ring is divided into one sector per Merkle leaf (one per exhibit). A leaf that no longer
 * matches its signed hash breaks its sector: the shard is pushed out, cracked and inked red.
 * Nothing is decorative: the pattern is a function of the root, the sectors are the leaves.
 */
export interface GuillocheSealProps {
  /** Merkle root (hex). Seeds the pattern. */
  root: string;
  /** Leaf names in tree order; one sector each. */
  leaves: string[];
  /** Leaves whose hash no longer matches; their sectors break. */
  broken?: string[];
  /** Case serial shown in the medallion. */
  serial: string;
  size?: number;
}

const C = 200;
const STEPS = 540;
const TAU = Math.PI * 2;
const FALLBACK_SEED = "9e3779b97f4a7c15f39cc0605cedc834";

const n1 = (v: number) => v.toFixed(1);
const n2 = (v: number) => v.toFixed(2);

function seed(root: string): number[] {
  const hex = /^[0-9a-f]+$/i.test(root) && root.length >= 16 ? root : FALLBACK_SEED;
  const out: number[] = [];
  for (let i = 0; i + 1 < hex.length; i += 2) out.push(parseInt(hex.slice(i, i + 2), 16));
  return out;
}

/** One closed polar curve r(θ), as an SVG path (1-decimal precision keeps it light). */
function polar(r: (t: number) => number): string {
  let d = "";
  for (let s = 0; s <= STEPS; s += 1) {
    const t = (s / STEPS) * TAU;
    const rr = r(t);
    d += `${s === 0 ? "M" : "L"}${n1(C + rr * Math.cos(t))} ${n1(C + rr * Math.sin(t))}`;
  }
  return `${d}Z`;
}

function wedge(a0: number, a1: number, r: number): string {
  const p = (a: number) => `${n2(C + r * Math.cos(a))} ${n2(C + r * Math.sin(a))}`;
  const large = a1 - a0 > Math.PI ? "1" : "0";
  return `M${n1(C)} ${n1(C)}L${p(a0)}A${n1(r)} ${n1(r)} 0 ${large} 1 ${p(a1)}Z`;
}

/** A jagged radial crack along angle a, deterministic in the seed. */
function crack(a: number, bytes: number[], k: number): string {
  let d = "";
  for (let i = 0; i <= 12; i += 1) {
    const r = 46 + (i / 12) * 142;
    const jitter = ((bytes[(k * 7 + i) % bytes.length] ?? 0) / 255 - 0.5) * 0.06;
    d += `${i === 0 ? "M" : "L"}${n1(C + r * Math.cos(a + jitter))} ${n1(C + r * Math.sin(a + jitter))}`;
  }
  return d;
}

interface Layer {
  cls: string;
  paths: string[];
}

function layers(bytes: number[]): Layer[] {
  const b = (i: number) => bytes[i % bytes.length] ?? 0;
  const p1 = 24 + (b(0) % 13); // outer band frequency
  const p2 = 7 + (b(1) % 7); // rosette petals
  const p3 = 2 + (b(2) % 4); // rosette modulation
  const p4 = 12 + (b(3) % 9); // inner ring
  const twist = (b(4) / 255) * TAU;
  const band = Array.from({ length: 18 }, (_, i) => {
    const ph = (i / 18) * TAU + twist;
    return polar((t) => 166 + 11 * Math.sin(p1 * t + ph) + 4 * Math.sin(3 * t - ph));
  });
  const rosette = Array.from({ length: 24 }, (_, i) => {
    const ph = (i / 24) * (TAU / p2);
    return polar((t) => 98 + 30 * Math.sin(p2 * t + ph) * Math.cos(p3 * t - ph * 2));
  });
  const inner = Array.from({ length: 12 }, (_, i) => {
    const ph = (i / 12) * TAU;
    return polar((t) => 58 + 7 * Math.sin(p4 * t + ph));
  });
  return [
    { cls: styles.band ?? "", paths: band },
    { cls: styles.rosette ?? "", paths: rosette },
    { cls: styles.inner ?? "", paths: inner },
  ];
}

/** The engraved line work, drawn inline (animations do not run inside <use> copies). */
function Art({ layers: list }: { layers: Layer[] }) {
  return (
    <>
      {list.map((layer) => (
        <g key={layer.cls} className={layer.cls}>
          {layer.paths.map((d, i) => (
            <path key={i} d={d} pathLength={1} />
          ))}
        </g>
      ))}
    </>
  );
}

export function GuillocheSeal({
  root,
  leaves,
  broken = [],
  serial,
  size = 280,
}: GuillocheSealProps) {
  const uid = useId().replace(/:/g, "");
  const bytes = useMemo(() => seed(root), [root]);
  const art = useMemo(() => layers(bytes), [bytes]);
  const n = Math.max(leaves.length, 1);
  const brokenSet = new Set(broken);
  const isBroken = broken.length > 0;
  const ring = `VERITA · SEALED CASE FILE · MERKLE ROOT ${root.toUpperCase()} · `;
  const sectors = leaves.map((name, i) => {
    const a0 = (i / n) * TAU - Math.PI / 2;
    const a1 = ((i + 1) / n) * TAU - Math.PI / 2;
    return { name, i, a0, a1, mid: (a0 + a1) / 2, broken: brokenSet.has(name) };
  });
  const shards = sectors.filter((s) => s.broken);
  const label = isBroken
    ? `Seal broken: ${String(broken.length)} of ${String(n)} exhibits changed since signing (${broken.join(", ")})`
    : `Seal intact: ${String(n)} exhibits under Merkle root ${root.slice(0, 16)}…`;

  return (
    <svg
      className={isBroken ? styles.sealBroken : styles.seal}
      viewBox="0 0 400 400"
      width={size}
      height={size}
      role="img"
      aria-label={label}
    >
      <defs>
        <linearGradient id={`foil-${uid}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" className={styles.foil1} />
          <stop offset="0.5" className={styles.foil2} />
          <stop offset="1" className={styles.foil3} />
          <animateTransform
            attributeName="gradientTransform"
            type="rotate"
            from="0 0.5 0.5"
            to="360 0.5 0.5"
            dur="9s"
            repeatCount="indefinite"
          />
        </linearGradient>
        <path id={`ring-${uid}`} d={`M${n1(C)} ${n1(C - 190)}a190 190 0 1 1 -0.01 0`} />
        {shards.map((s) => (
          <clipPath key={s.name} id={`clip-${uid}-${String(s.i)}`}>
            <path d={wedge(s.a0, s.a1, 189)} />
          </clipPath>
        ))}
        <mask id={`mask-${uid}`}>
          <rect width="400" height="400" fill="white" />
          {shards.map((s) => (
            <path key={s.name} d={wedge(s.a0, s.a1, 189)} fill="black" />
          ))}
        </mask>
      </defs>

      <circle className={styles.rim} cx={C} cy={C} r={196} />
      <text className={styles.micro} fontSize={6.2}>
        <textPath href={`#ring-${uid}`}>{ring.repeat(3)}</textPath>
      </text>

      <g mask={`url(#mask-${uid})`}>
        <Art layers={art} />
      </g>

      {sectors.map((s) => (
        <line
          key={s.name}
          className={s.broken ? styles.tickBroken : styles.tick}
          x1={C + 178 * Math.cos(s.mid)}
          y1={C + 178 * Math.sin(s.mid)}
          x2={C + 188 * Math.cos(s.mid)}
          y2={C + 188 * Math.sin(s.mid)}
        >
          <title>{s.name}</title>
        </line>
      ))}

      {shards.map((s) => (
        <g
          key={s.name}
          transform={`translate(${n1(11 * Math.cos(s.mid))} ${n1(11 * Math.sin(s.mid))})`}
        >
          <g className={styles.shard}>
            <g clipPath={`url(#clip-${uid}-${String(s.i)})`}>
              <path className={styles.shardFill} d={wedge(s.a0, s.a1, 189)} />
              <Art layers={art} />
            </g>
            <path className={styles.crack} d={crack(s.a0, bytes, s.i)} />
            <path className={styles.crack} d={crack(s.a1, bytes, s.i + 3)} />
            <title>{`${s.name} changed since signing`}</title>
          </g>
        </g>
      ))}

      <circle className={styles.medallion} cx={C} cy={C} r={44} stroke={`url(#foil-${uid})`} />
      <circle className={styles.medallionInner} cx={C} cy={C} r={38} />
      <text className={styles.no} x={C} y={C - 10} fontSize={11}>
        No.
      </text>
      <text className={styles.serial} x={C} y={C + 12} fontSize={22}>
        {serial}
      </text>
      <text
        className={isBroken ? styles.stateBroken : styles.state}
        x={C}
        y={C + 27}
        fontSize={7.5}
      >
        {isBroken ? "BROKEN" : "SEALED"}
      </text>
    </svg>
  );
}
