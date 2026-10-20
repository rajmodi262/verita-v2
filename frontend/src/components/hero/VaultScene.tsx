/* eslint-disable react/no-unknown-property -- react-three-fiber elements take Three.js props */
import { Stars } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

/**
 * The landing hero: the case seal as an engraved coin that sways toward the viewer, circled by a
 * neon orbit of payments (flagged ones in gold foil), under a night of transactions. Colours come
 * from the design tokens.
 */

function token(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

const TAU = Math.PI * 2;

/**
 * The coin face, drawn once to a canvas: a beaded and lettered rim, a guilloché band, a classical
 * facade (the courthouse — evidence) and VERITA in engraved capitals. The same canvas drives the
 * colour, the glow and the relief (bump map), so every engraved line is both lit and raised.
 */
function engraving(line: string, ground: string): THREE.CanvasTexture {
  const size = 2048;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const c = size / 2;
    const k = size / 420; // design units (face radius ~ 205) -> pixels
    const X = (u: number) => c + u * k;
    const Y = (v: number) => c + v * k;
    const g = ctx.createRadialGradient(c, c * 0.8, 0, c, c, c);
    g.addColorStop(0, ground);
    g.addColorStop(1, "#000000");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
    ctx.strokeStyle = line;
    ctx.fillStyle = line;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    const ring = (r: number, w: number) => {
      ctx.lineWidth = w * k;
      ctx.beginPath();
      ctx.arc(c, c, r * k, 0, TAU);
      ctx.stroke();
    };
    const curve = (r: (t: number) => number, alpha: number) => {
      ctx.globalAlpha = alpha;
      ctx.lineWidth = 0.55 * k;
      ctx.beginPath();
      for (let s = 0; s <= 1440; s += 1) {
        const t = (s / 1440) * TAU;
        const rr = r(t) * k;
        if (s === 0) ctx.moveTo(c + rr * Math.cos(t), c + rr * Math.sin(t));
        else ctx.lineTo(c + rr * Math.cos(t), c + rr * Math.sin(t));
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
    };
    const rect = (x0: number, y0: number, x1: number, y1: number) => {
      ctx.strokeRect(X(x0), Y(y0), (x1 - x0) * k, (y1 - y0) * k);
    };

    // rim: beads between two rules
    ring(203, 3);
    ring(196, 1);
    for (let i = 0; i < 160; i += 1) {
      const t = (i / 160) * TAU;
      ctx.beginPath();
      ctx.arc(X(199.5 * Math.cos(t)), Y(199.5 * Math.sin(t)), 1.3 * k, 0, TAU);
      ctx.fill();
    }

    // lettered ring
    const legend = "VERITA · FOLLOW THE MONEY · DETECT · DECIDE · DEFEND · ".split("");
    ctx.font = `600 ${String(Math.round(13 * k))}px 'Bodoni Moda Variable', Didot, serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    legend.forEach((ch, i) => {
      const t = (i / legend.length) * TAU - Math.PI / 2;
      ctx.save();
      ctx.translate(X(182 * Math.cos(t)), Y(182 * Math.sin(t)));
      ctx.rotate(t + Math.PI / 2);
      ctx.fillText(ch, 0, 0);
      ctx.restore();
    });
    ring(170, 1.2);

    // guilloché band
    for (let i = 0; i < 26; i += 1) {
      const ph = (i / 26) * TAU;
      curve((t) => 157 + 9 * Math.sin(34 * t + ph) + 2.5 * Math.sin(3 * t - ph), 0.8);
    }
    ring(143, 1.2);

    // the facade: steps, fluted columns, entablature, pediment with the seal in the tympanum
    ctx.lineWidth = 2.2 * k;
    rect(-84, 38, 84, 46);
    rect(-76, 30, 76, 38);
    rect(-70, -38, 70, -28);
    for (let i = 0; i < 6; i += 1) {
      const x = -60 + i * 24;
      rect(x - 6, -28, x + 6, 30);
      for (const f of [-3, 0, 3]) {
        ctx.beginPath();
        ctx.moveTo(X(x + f), Y(-25));
        ctx.lineTo(X(x + f), Y(27));
        ctx.stroke();
      }
      rect(x - 8, -31, x + 8, -28);
      rect(x - 8, 28, x + 8, 30);
    }
    for (const [w, top, base] of [
      [76, -80, -38],
      [60, -73, -43],
    ] as const) {
      ctx.beginPath();
      ctx.moveTo(X(-w), Y(base));
      ctx.lineTo(X(0), Y(top));
      ctx.lineTo(X(w), Y(base));
      ctx.closePath();
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(X(0), Y(-52), 7 * k, 0, TAU);
    ctx.stroke();

    // flanking stars
    for (const sx of [-112, 112]) {
      ctx.beginPath();
      for (let i = 0; i < 10; i += 1) {
        const t = (i / 10) * TAU - Math.PI / 2;
        const r = (i % 2 ? 3 : 8) * k;
        if (i === 0) ctx.moveTo(X(sx) + r * Math.cos(t), Y(4) + r * Math.sin(t));
        else ctx.lineTo(X(sx) + r * Math.cos(t), Y(4) + r * Math.sin(t));
      }
      ctx.closePath();
      ctx.fill();
    }

    // VERITA, engraved
    ctx.font = `600 ${String(Math.round(40 * k))}px 'Bodoni Moda Variable', Didot, serif`;
    ctx.fillText("V E R I T A", c, Y(80));
    ctx.font = `500 ${String(Math.round(10 * k))}px 'Schibsted Grotesk Variable', sans-serif`;
    ctx.fillText("EVIDENCE YOU CAN PROVE", c, Y(108));
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 16;
  return texture;
}

/** The coin's edge: fine vertical reeding, like a milled coin. */
function reeding(line: string): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 1024;
  canvas.height = 32;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.fillStyle = "#000000";
    ctx.fillRect(0, 0, 1024, 32);
    ctx.fillStyle = line;
    for (let x = 0; x < 1024; x += 8) ctx.fillRect(x, 0, 4, 32);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.repeat.set(3, 1);
  return texture;
}

const COIN_R = 1.5;
const COIN_T = 0.36; // thick: a struck coin, not a disc

/** What the scene tells the page each frame: how squarely the coin faces the viewer, and any
 * pattern being performed (for the caption). */
export interface StageSignal {
  face: number;
  caption: string | null;
}

function Medallion({
  line,
  ground,
  metal,
  onFace,
}: {
  line: string;
  ground: string;
  metal: string;
  onFace: (face: number) => void;
}) {
  const group = useRef<THREE.Group>(null);
  const face = useMemo(() => engraving(line, ground), [line, ground]);
  const edge = useMemo(() => reeding(line), [line]);
  const material = useRef<THREE.MeshPhysicalMaterial>(null);
  const back = useRef<THREE.MeshPhysicalMaterial>(null);
  useFrame((state, delta) => {
    const g = group.current;
    if (!g) return;
    g.rotation.y += delta * 0.5; // a full, unhurried turn
    // face tilted slightly up, so VERITA reads high on the coin
    const tilt = -0.16 - state.pointer.y * 0.12 + Math.sin(state.clock.elapsedTime * 0.3) * 0.04;
    g.rotation.x = THREE.MathUtils.lerp(g.rotation.x, tilt, 0.06);
    onFace(Math.abs(Math.cos(g.rotation.y)));
    // the coin glints when a pattern is caught (same script clock as the money stream)
    const phase = phaseAt(state.clock.elapsedTime);
    const since = phase.local - 1.3;
    const flash = phase.name !== "ORBIT" && since > 0 ? Math.max(0, 1 - since) : 0;
    const glow = 0.5 + flash * 1.1;
    if (material.current) material.current.emissiveIntensity = glow;
    if (back.current) back.current.emissiveIntensity = glow;
  });
  const faceProps = {
    map: face,
    bumpMap: face,
    bumpScale: 3,
    emissiveMap: face,
    emissive: line,
    emissiveIntensity: 0.5,
    color: metal,
    metalness: 1,
    roughness: 0.38,
    clearcoat: 0.4,
  };
  return (
    <group ref={group} position={[0, 0.22, 0]}>
      {/* the milled edge */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[COIN_R, COIN_R, COIN_T, 192, 1, true]} />
        <meshPhysicalMaterial
          color={metal}
          bumpMap={edge}
          bumpScale={3}
          metalness={1}
          roughness={0.25}
          clearcoat={0.6}
        />
      </mesh>
      {/* the same struck face on both sides; the back disc is turned to read correctly */}
      <mesh position={[0, 0, COIN_T / 2]}>
        <circleGeometry args={[COIN_R, 192]} />
        <meshPhysicalMaterial ref={material} {...faceProps} />
      </mesh>
      <mesh position={[0, 0, -COIN_T / 2]} rotation={[0, Math.PI, 0]}>
        <circleGeometry args={[COIN_R, 192]} />
        <meshPhysicalMaterial ref={back} {...faceProps} />
      </mesh>
      {/* raised rims with a bevel that catches the light */}
      {[COIN_T / 2, -COIN_T / 2].map((z) => (
        <mesh key={z} position={[0, 0, z]}>
          <torusGeometry args={[COIN_R - 0.05, 0.06, 24, 192]} />
          <meshPhysicalMaterial color={metal} metalness={1} roughness={0.2} clearcoat={0.8} />
        </mesh>
      ))}
    </group>
  );
}

const CURRENCIES = ["$", "€", "£", "¥", "₹", "₿", "₽", "₩"];

/** One currency symbol, engraved: a dark keyline under a solid fill, with a soft glow. */
function glyph(ch: string, color: string): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 160;
  canvas.height = 160;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.font =
      "700 112px 'Bodoni Moda Variable', 'Segoe UI Symbol', 'Segoe UI', 'Noto Sans', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.shadowColor = color;
    ctx.shadowBlur = 6;
    ctx.lineWidth = 8;
    ctx.strokeStyle = "#0a0618";
    ctx.strokeText(ch, 80, 88);
    ctx.fillStyle = color;
    ctx.fillText(ch, 80, 88);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** A soft round glow for the comet tails. */
function glow(color: string): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, color);
    g.addColorStop(1, "#00000000");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 64, 64);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

const RADIUS = 2.75;
const STREAM = 24; // symbols in orbit
const ACTORS = 7; // how many of them perform each pattern
const TAIL = 5; // fading glow dots behind each symbol
const TILT = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.36, 0, -0.24));
const BEHIND = -Math.PI / 2; // the point on the orbit hidden behind the coin

/**
 * The script the money performs: calm orbit, then the laundering typologies Verita detects —
 * fan-in, a cycle (round-tripping through currencies), scatter-gather — each caught and named.
 */
const SCRIPT = [
  { name: "ORBIT", dur: 5, caption: null },
  { name: "FAN-IN", dur: 4.6, caption: "Pattern detected · FAN-IN — many accounts pay into one" },
  { name: "ORBIT", dur: 3, caption: null },
  { name: "CYCLE", dur: 5.2, caption: "Pattern detected · CYCLE — the money comes back changed" },
  { name: "ORBIT", dur: 3, caption: null },
  {
    name: "SCATTER-GATHER",
    dur: 4.8,
    caption: "Pattern detected · SCATTER-GATHER — split apart, gathered again",
  },
] as const;
const SCRIPT_LENGTH = SCRIPT.reduce((sum, p) => sum + p.dur, 0);

function phaseAt(t: number) {
  let local = t % SCRIPT_LENGTH;
  for (const [index, phase] of SCRIPT.entries()) {
    if (local < phase.dur) return { ...phase, local, index };
    local -= phase.dur;
  }
  return { ...SCRIPT[0], local: 0, index: 0 };
}

const smooth = (x: number) => {
  const c = Math.min(Math.max(x, 0), 1);
  return c * c * (3 - 2 * c);
};

function Stream({
  silver,
  gold,
  onCaption,
}: {
  silver: string;
  gold: string;
  onCaption: (caption: string | null) => void;
}) {
  const textures = useMemo(
    () => ({
      silver: CURRENCIES.map((ch) => glyph(ch, silver)),
      gold: CURRENCIES.map((ch) => glyph(ch, gold)),
      silverTail: glow(silver),
      goldTail: glow(gold),
    }),
    [silver, gold],
  );
  const sprites = useRef<(THREE.Sprite | null)[]>([]);
  const history = useMemo(
    () =>
      Array.from({ length: STREAM }, () =>
        Array.from({ length: TAIL * 3 }, () => new THREE.Vector3()),
      ),
    [],
  );
  const stream = useMemo(
    () =>
      Array.from({ length: STREAM }, (_, i) => ({
        offset: (i / STREAM) * Math.PI * 2,
        base: (i * 3) % CURRENCIES.length,
        flagged: i % 6 === 0,
      })),
    [],
  );
  const target = useMemo(() => new THREE.Vector3(), []);
  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const phase = phaseAt(t);
    const pattern = phase.name !== "ORBIT";
    // blend in and out of the formation
    const blend = pattern ? smooth(phase.local / 1.1) * smooth((phase.dur - phase.local) / 0.9) : 0;
    const caught = pattern && phase.local > 1.3 && phase.local < phase.dur - 0.6;
    onCaption(caught ? phase.caption : null);
    // which symbols perform this pattern: the ones nearest the front of the orbit
    const firstActor = Math.floor((((t * 0.18) / (Math.PI * 2)) * STREAM + STREAM * 0.2) % STREAM);
    const n = CURRENCIES.length;

    stream.forEach((s, i) => {
      const a = s.offset + t * 0.18;
      const orbit = new THREE.Vector3(
        Math.cos(a) * RADIUS,
        0,
        Math.sin(a) * RADIUS,
      ).applyQuaternion(TILT);
      const k = (i - firstActor + STREAM) % STREAM; // 0..ACTORS-1 for performers
      const acting = pattern && k < ACTORS;
      let which = (((s.base + Math.floor((a - BEHIND) / (Math.PI * 2))) % n) + n) % n;
      const pos = orbit.clone();
      if (acting) {
        const u = k / (ACTORS - 1); // 0..1 across the performers
        if (phase.name === "FAN-IN") {
          // many senders converge on one account: the coin
          const arrive = smooth((phase.local - 0.3 - k * 0.18) / 1.4);
          target.set(0, 0, 0.7);
          pos.lerp(target, arrive);
        } else if (phase.name === "CYCLE") {
          // a closed loop in front of the coin, changing currency at every hop
          const ang = phase.local * 1.5 + (k / ACTORS) * Math.PI * 2;
          target.set(Math.cos(ang) * 1.05, Math.sin(ang) * 1.05, 1.5);
          pos.lerp(target, blend);
          which = (s.base + Math.floor(phase.local * 2 + k)) % n;
        } else {
          // one source scatters into parallel lanes, then gathers into one destination
          const p = smooth((phase.local - 0.6) / (phase.dur - 1.5));
          const lane = (u - 0.5) * 2.2 * Math.sin(p * Math.PI);
          target.set(-2.4 + 4.8 * p, -0.15 + lane, 1.4);
          pos.lerp(target, blend);
        }
      }
      const h = history[i];
      if (h) {
        h.pop();
        h.unshift(pos.clone());
      }
      const golden = s.flagged || (acting && blend > 0.25);
      for (let j = 0; j <= TAIL; j += 1) {
        const sprite = sprites.current[i * (TAIL + 1) + j];
        if (!sprite) continue;
        const at = j === 0 ? pos : (h?.[j * 3] ?? pos);
        sprite.position.copy(at);
        const map =
          j === 0
            ? (golden ? textures.gold : textures.silver)[which]
            : golden
              ? textures.goldTail
              : textures.silverTail;
        const material = sprite.material;
        if (material.map !== map) {
          material.map = map ?? null;
          material.needsUpdate = true;
        }
        const fade = 1 - j / (TAIL + 1);
        const head = golden ? 0.44 : 0.34;
        const size = j === 0 ? head : 0.14 * fade;
        sprite.scale.set(size, size, 1);
        material.opacity = j === 0 ? 1 : 0.32 * fade;
      }
    });
  });
  return (
    <group>
      {Array.from({ length: STREAM * (TAIL + 1) }, (_, k) => (
        <sprite
          key={k}
          ref={(el) => {
            sprites.current[k] = el;
          }}
        >
          <spriteMaterial transparent depthWrite={false} toneMapped={false} />
        </sprite>
      ))}
    </group>
  );
}

export default function VaultScene({
  still = false,
  onSignal,
}: {
  still?: boolean;
  /** Called every frame with what the page should show around the scene. */
  onSignal?: (signal: StageSignal) => void;
}) {
  const colors = useMemo(
    () => ({
      line: token("--hero-engrave", "#e9dcff"),
      ground: token("--hero-coin", "#1a0f33"),
      metal: token("--hero-metal", "#4a3d6e"),
      gold: token("--hero-flag", "#d9b56a"),
      silver: token("--hero-particle", "#b9bdd8"),
      key: token("--hero-key", "#ff8be9"),
      fill: token("--hero-fill", "#6b7bff"),
    }),
    [],
  );
  const signal = useRef<StageSignal>({ face: 1, caption: null });
  return (
    <Canvas
      camera={{ position: [0, 0, 6.2], fov: 42 }}
      dpr={[1, 2]}
      frameloop={still ? "demand" : "always"}
      gl={{ antialias: true, alpha: true }}
      onCreated={({ gl, scene }) => {
        // studio reflections generated in code (no HDR download), so the metal reads as metal
        scene.environment = new THREE.PMREMGenerator(gl).fromScene(
          new RoomEnvironment(),
          0.04,
        ).texture;
      }}
    >
      <ambientLight intensity={0.3} />
      <pointLight position={[4, 3, 4]} intensity={60} color={colors.key} />
      <pointLight position={[-4, -2, 3]} intensity={45} color={colors.fill} />
      <spotLight position={[0, 6, 2]} intensity={40} angle={0.5} penumbra={1} />
      <Stars radius={60} depth={40} count={1600} factor={3} saturation={0} fade speed={0.4} />
      <Medallion
        line={colors.line}
        ground={colors.ground}
        metal={colors.metal}
        onFace={(face) => {
          signal.current = { ...signal.current, face };
          onSignal?.(signal.current);
        }}
      />
      <Stream
        silver={colors.silver}
        gold={colors.gold}
        onCaption={(caption) => {
          if (signal.current.caption !== caption) signal.current = { ...signal.current, caption };
        }}
      />
      <EffectComposer>
        <Bloom intensity={0.7} luminanceThreshold={0.6} luminanceSmoothing={0.2} />
      </EffectComposer>
    </Canvas>
  );
}
