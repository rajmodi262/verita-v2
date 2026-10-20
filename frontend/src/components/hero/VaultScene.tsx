/* eslint-disable react/no-unknown-property -- react-three-fiber elements take Three.js props */
import { Stars } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { Bloom, EffectComposer, Noise, Vignette } from "@react-three/postprocessing";
import { useMemo, useRef } from "react";
import * as THREE from "three";

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
  texture.center.set(0.5, 0.5);
  texture.rotation = Math.PI / 2; // cylinder caps map u/v a quarter turn round
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

function Medallion({ line, ground, rim }: { line: string; ground: string; rim: string }) {
  const group = useRef<THREE.Group>(null);
  const face = useMemo(() => engraving(line, ground), [line, ground]);
  const edge = useMemo(() => reeding(line), [line]);
  useFrame((state) => {
    const g = group.current;
    if (!g) return;
    const t = state.clock.elapsedTime;
    // sway, never edge-on: the face always turns toward the viewer; lean toward the pointer
    const sway = Math.sin(t * 0.45) * 0.5 + state.pointer.x * 0.25;
    g.rotation.y = THREE.MathUtils.lerp(g.rotation.y, sway, 0.06);
    const tilt = -state.pointer.y * 0.2 + Math.sin(t * 0.3) * 0.06;
    g.rotation.x = THREE.MathUtils.lerp(g.rotation.x, tilt, 0.06);
  });
  return (
    <group ref={group}>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[1.22, 1.22, 0.14, 160]} />
        <meshStandardMaterial
          attach="material-0"
          color={rim}
          bumpMap={edge}
          bumpScale={2}
          emissiveMap={edge}
          emissive={rim}
          emissiveIntensity={0.6}
          metalness={1}
          roughness={0.22}
        />
        {[1, 2].map((slot) => (
          <meshStandardMaterial
            key={slot}
            attach={`material-${String(slot)}`}
            map={face}
            bumpMap={face}
            bumpScale={1.6}
            emissiveMap={face}
            emissive={line}
            emissiveIntensity={1.1}
            metalness={0.9}
            roughness={0.3}
          />
        ))}
      </mesh>
      {/* a soft halo behind the coin so it glows against the night */}
      <mesh position={[0, 0, -0.2]}>
        <circleGeometry args={[1.55, 64]} />
        <meshBasicMaterial color={line} transparent opacity={0.035} toneMapped={false} />
      </mesh>
    </group>
  );
}

/** The orbit: a neon ring with payments travelling along it; one in eight is flagged (gold). */
function Orbit({ neon, flag, pale }: { neon: string; flag: string; pale: string }) {
  const dots = useRef<THREE.InstancedMesh>(null);
  const count = 140;
  const seeds = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => ({
        offset: (i / count) * TAU + Math.sin(i * 12.9898) * 0.08,
        speed: 0.18 + ((i * 7) % 11) * 0.012,
        lift: Math.sin(i * 78.233) * 0.05,
      })),
    [],
  );
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const colored = useRef(false);
  useFrame((state) => {
    const mesh = dots.current;
    if (!mesh) return;
    if (!colored.current) {
      const pc = new THREE.Color(pale);
      const fc = new THREE.Color(flag);
      seeds.forEach((_, i) => {
        mesh.setColorAt(i, i % 8 === 0 ? fc : pc);
      });
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      colored.current = true;
    }
    const t = state.clock.elapsedTime;
    seeds.forEach((s, i) => {
      const a = s.offset + t * s.speed;
      dummy.position.set(Math.cos(a) * 2.45, s.lift, Math.sin(a) * 2.45);
      dummy.scale.setScalar(i % 8 === 0 ? 1.7 : 1);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  });
  return (
    <group rotation={[0.32, 0, -0.28]}>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[2.45, 0.014, 16, 256]} />
        <meshBasicMaterial color={neon} toneMapped={false} />
      </mesh>
      <instancedMesh ref={dots} args={[undefined, undefined, count]}>
        <sphereGeometry args={[0.022, 12, 12]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

export default function VaultScene({ still = false }: { still?: boolean }) {
  const colors = useMemo(
    () => ({
      line: token("--hero-engrave", "#e9dcff"),
      ground: token("--hero-coin", "#2a1650"),
      rim: token("--hero-rim", "#b9a3ff"),
      neon: token("--hero-neon", "#ff4fd8"),
      flag: token("--hero-flag", "#ffd27a"),
      pale: token("--hero-particle", "#d8c8ff"),
      key: token("--hero-key", "#ff8be9"),
      fill: token("--hero-fill", "#6b7bff"),
    }),
    [],
  );
  return (
    <Canvas
      camera={{ position: [0, 0, 6.2], fov: 42 }}
      dpr={[1, 2]}
      frameloop={still ? "demand" : "always"}
      gl={{ antialias: true, alpha: true }}
    >
      <ambientLight intensity={0.3} />
      <pointLight position={[4, 3, 4]} intensity={60} color={colors.key} />
      <pointLight position={[-4, -2, 3]} intensity={45} color={colors.fill} />
      <spotLight position={[0, 6, 2]} intensity={40} angle={0.5} penumbra={1} />
      <Stars radius={60} depth={40} count={2200} factor={3} saturation={0} fade speed={0.4} />
      <Medallion line={colors.line} ground={colors.ground} rim={colors.rim} />
      <Orbit neon={colors.neon} flag={colors.flag} pale={colors.pale} />
      <EffectComposer>
        <Bloom intensity={1.9} luminanceThreshold={0.12} luminanceSmoothing={0.35} mipmapBlur />
        <Noise opacity={0.06} />
        <Vignette offset={0.2} darkness={0.75} />
      </EffectComposer>
    </Canvas>
  );
}
