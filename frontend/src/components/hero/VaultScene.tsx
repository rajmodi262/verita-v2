/* eslint-disable react/no-unknown-property -- react-three-fiber elements take Three.js props */
import { Stars } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { Bloom, EffectComposer, Noise, Vignette } from "@react-three/postprocessing";
import { useMemo, useRef } from "react";
import * as THREE from "three";

/**
 * The landing hero: the case seal as a slowly turning engraved medallion, circled by a neon
 * orbit of payments (flagged ones in signal red), under a night of transactions. The engraving is
 * the same guilloché maths as the 2D seal. Colours come from the design tokens.
 */

function token(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

const TAU = Math.PI * 2;

/** Guilloché face, drawn once to a canvas and used as the coin's texture. */
function engraving(line: string, ground: string): THREE.CanvasTexture {
  const size = 1024;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const c = size / 2;
    const g = ctx.createRadialGradient(c, c, 0, c, c, c);
    g.addColorStop(0, ground);
    g.addColorStop(1, "#000000");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
    ctx.strokeStyle = line;
    const curve = (r: (t: number) => number, alpha: number, width: number) => {
      ctx.globalAlpha = alpha;
      ctx.lineWidth = width;
      ctx.beginPath();
      for (let s = 0; s <= 720; s += 1) {
        const t = (s / 720) * TAU;
        const rr = r(t) * (size / 420);
        const x = c + rr * Math.cos(t);
        const y = c + rr * Math.sin(t);
        if (s === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    };
    for (let i = 0; i < 22; i += 1) {
      const ph = (i / 22) * TAU;
      curve((t) => 168 + 12 * Math.sin(30 * t + ph) + 4 * Math.sin(3 * t - ph), 0.55, 1.2);
    }
    for (let i = 0; i < 26; i += 1) {
      const ph = (i / 26) * (TAU / 9);
      curve((t) => 100 + 32 * Math.sin(9 * t + ph) * Math.cos(3 * t - ph * 2), 0.75, 1.4);
    }
    for (let i = 0; i < 14; i += 1) {
      const ph = (i / 14) * TAU;
      curve((t) => 58 + 7 * Math.sin(16 * t + ph), 0.85, 1.2);
    }
    ctx.globalAlpha = 1;
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  return texture;
}

function Medallion({ line, ground, rim }: { line: string; ground: string; rim: string }) {
  const group = useRef<THREE.Group>(null);
  const face = useMemo(() => engraving(line, ground), [line, ground]);
  useFrame((state, delta) => {
    const g = group.current;
    if (!g) return;
    g.rotation.y += delta * 0.25;
    // lean toward the pointer, gently
    g.rotation.x = THREE.MathUtils.lerp(g.rotation.x, 0.25 - state.pointer.y * 0.25, 0.05);
    g.rotation.z = THREE.MathUtils.lerp(g.rotation.z, -state.pointer.x * 0.15, 0.05);
  });
  return (
    <group ref={group}>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[1.22, 1.22, 0.13, 128]} />
        <meshStandardMaterial attach="material-0" color={rim} metalness={1} roughness={0.25} />
        <meshStandardMaterial
          attach="material-1"
          map={face}
          emissiveMap={face}
          emissive={line}
          emissiveIntensity={0.55}
          metalness={0.85}
          roughness={0.35}
        />
        <meshStandardMaterial
          attach="material-2"
          map={face}
          emissiveMap={face}
          emissive={line}
          emissiveIntensity={0.55}
          metalness={0.85}
          roughness={0.35}
        />
      </mesh>
    </group>
  );
}

/** The orbit: a neon ring with payments travelling along it; one in eight is flagged. */
function Orbit({ neon, flag, pale }: { neon: string; flag: string; pale: string }) {
  const ring = useRef<THREE.Group>(null);
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
      const scale = i % 8 === 0 ? 1.7 : 1;
      dummy.scale.setScalar(scale);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  });
  return (
    <group ref={ring} rotation={[0.32, 0, -0.28]}>
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
      flag: token("--hero-flag", "#ff3b3b"),
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
      <ambientLight intensity={0.25} />
      <pointLight position={[4, 3, 4]} intensity={60} color={colors.key} />
      <pointLight position={[-4, -2, 3]} intensity={45} color={colors.fill} />
      <spotLight position={[0, 6, 2]} intensity={40} angle={0.5} penumbra={1} />
      <Stars radius={60} depth={40} count={2200} factor={3} saturation={0} fade speed={0.4} />
      <Medallion line={colors.line} ground={colors.ground} rim={colors.rim} />
      <Orbit neon={colors.neon} flag={colors.flag} pale={colors.pale} />
      <EffectComposer>
        <Bloom intensity={1.4} luminanceThreshold={0.15} luminanceSmoothing={0.3} mipmapBlur />
        <Noise opacity={0.06} />
        <Vignette offset={0.2} darkness={0.75} />
      </EffectComposer>
    </Canvas>
  );
}
