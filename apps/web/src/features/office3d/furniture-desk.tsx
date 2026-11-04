"use client";

import type * as THREE from "three";
import type { Rect } from "./layout";
import { Box, PALETTE, mat } from "./furniture-base";

// ---- desks and chairs ------------------------------------------------------

export function Desk({
  rect,
  accent,
  twin = false,
}: {
  rect: Rect;
  accent: string;
  twin?: boolean;
}) {
  const cx = rect.x + rect.w / 2;
  const cz = rect.z + rect.d / 2;
  const top = 0.74;
  const leg = mat(PALETTE.brass, { rough: 0.35, metal: 0.7 });
  return (
    <group position={[cx, 0, cz]}>
      <Box
        p={[0, top - 0.025, 0]}
        s={[rect.w, 0.05, rect.d]}
        m={mat(PALETTE.oak, { rough: 0.55 })}
        r={0.02}
      />
      {[-1, 1].flatMap((sx) =>
        [-1, 1].map((sz) => (
          <mesh
            key={`${String(sx)}${String(sz)}`}
            position={[
              sx * (rect.w / 2 - 0.07),
              (top - 0.05) / 2,
              sz * (rect.d / 2 - 0.07),
            ]}
            material={leg}
            castShadow
          >
            <cylinderGeometry args={[0.022, 0.018, top - 0.05, 10]} />
          </mesh>
        )),
      )}
      {/* modesty panel in the accent colour */}
      <Box
        p={[0, 0.42, 0]}
        s={[rect.w - 0.2, 0.3, 0.02]}
        m={mat(accent, { rough: 0.8 })}
        r={0.008}
        shadow={false}
      />
      {twin && (
        <Box
          p={[rect.w / 2 - 0.35, top + 0.01, 0.1]}
          s={[0.3, 0.02, 0.22]}
          m={mat(PALETTE.charcoalSoft)}
          r={0.005}
        />
      )}
    </group>
  );
}

/** A monitor on a desk, screen facing `face`. The screen material comes from the caller. */
export function Monitor({
  x,
  z,
  face,
  screen,
  wide = false,
}: {
  x: number;
  z: number;
  face: number;
  screen: THREE.Material;
  wide?: boolean;
}) {
  const w = wide ? 0.78 : 0.62;
  return (
    <group position={[x, 0.74, z]} rotation-y={face + Math.PI}>
      <Box
        p={[0, 0.02, 0]}
        s={[0.22, 0.02, 0.16]}
        m={mat(PALETTE.charcoal, { metal: 0.3, rough: 0.4 })}
        r={0.008}
      />
      <Box
        p={[0, 0.16, 0.03]}
        s={[0.04, 0.26, 0.03]}
        m={mat(PALETTE.charcoal, { metal: 0.3, rough: 0.4 })}
        r={0.01}
      />
      <Box
        p={[0, 0.36, 0]}
        s={[w, 0.38, 0.035]}
        m={mat(PALETTE.charcoal, { rough: 0.35 })}
        r={0.015}
      />
      <mesh position={[0, 0.36, -0.019]} rotation-y={Math.PI} material={screen}>
        <planeGeometry args={[w - 0.05, 0.33]} />
      </mesh>
    </group>
  );
}

export function Keyboard({
  x,
  z,
  face,
}: {
  x: number;
  z: number;
  face: number;
}) {
  return (
    <group position={[x, 0.755, z]} rotation-y={face}>
      <Box
        p={[-0.05, 0, 0]}
        s={[0.42, 0.018, 0.13]}
        m={mat("#e9e6e0", { rough: 0.6 })}
        r={0.006}
        shadow={false}
      />
      <Box
        p={[0.28, 0, 0.01]}
        s={[0.07, 0.022, 0.1]}
        m={mat("#e9e6e0", { rough: 0.6 })}
        r={0.02}
        shadow={false}
      />
    </group>
  );
}

/** An upholstered office chair whose seat centre is (x, z), facing `face`. */
export function Chair({
  x,
  z,
  face,
  color,
}: {
  x: number;
  z: number;
  face: number;
  color: string;
}) {
  const metal = mat(PALETTE.charcoal, { metal: 0.5, rough: 0.35 });
  return (
    <group position={[x, 0, z]} rotation-y={face}>
      <Box
        p={[0, 0.44, 0]}
        s={[0.5, 0.09, 0.48]}
        m={mat(color, { rough: 0.95 })}
        r={0.04}
      />
      <Box
        p={[0, 0.78, -0.24]}
        s={[0.46, 0.56, 0.08]}
        m={mat(color, { rough: 0.95 })}
        r={0.04}
      />
      <mesh position={[0, 0.22, 0]} material={metal}>
        <cylinderGeometry args={[0.025, 0.025, 0.4, 8]} />
      </mesh>
      {[0, 1, 2, 3, 4].map((i) => {
        const a = (i / 5) * Math.PI * 2;
        return (
          <mesh
            key={i}
            position={[Math.sin(a) * 0.17, 0.04, Math.cos(a) * 0.17]}
            rotation-y={a}
            material={metal}
          >
            <boxGeometry args={[0.04, 0.03, 0.34]} />
          </mesh>
        );
      })}
    </group>
  );
}

export function DeskLamp({
  x,
  z,
  lit,
}: {
  x: number;
  z: number;
  lit: boolean;
}) {
  const brass = mat(PALETTE.brass, { metal: 0.8, rough: 0.3 });
  return (
    <group position={[x, 0.74, z]}>
      <mesh position={[0, 0.01, 0]} material={brass}>
        <cylinderGeometry args={[0.07, 0.08, 0.02, 16]} />
      </mesh>
      <mesh position={[0, 0.17, 0]} material={brass}>
        <cylinderGeometry args={[0.008, 0.008, 0.32, 6]} />
      </mesh>
      <mesh position={[0.05, 0.33, 0]} rotation-z={-0.8} material={brass}>
        <coneGeometry args={[0.07, 0.12, 16, 1, true]} />
      </mesh>
      <mesh
        position={[0.08, 0.3, 0]}
        material={mat("#fff4d6", {
          emissive: "#ffcf7a",
          emissiveIntensity: lit ? 2.4 : 0.2,
        })}
      >
        <sphereGeometry args={[0.025, 10, 8]} />
      </mesh>
    </group>
  );
}

export function Mug({
  x,
  z,
  y = 0.74,
  color = PALETTE.paper,
}: {
  x: number;
  z: number;
  y?: number;
  color?: string;
}) {
  return (
    <mesh
      position={[x, y + 0.05, z]}
      castShadow
      material={mat(color, { rough: 0.5 })}
    >
      <cylinderGeometry args={[0.04, 0.035, 0.1, 14]} />
    </mesh>
  );
}

export function PaperStack({
  x,
  z,
  n,
  y = 0.74,
  rot = 0,
}: {
  x: number;
  z: number;
  n: number;
  y?: number;
  rot?: number;
}) {
  return (
    <group position={[x, y, z]} rotation-y={rot}>
      {Array.from({ length: Math.max(0, Math.min(n, 12)) }, (_, i) => (
        <mesh
          key={i}
          position={[(i % 2) * 0.008, 0.006 + i * 0.012, 0]}
          rotation-y={(i % 3) * 0.04}
          material={mat(PALETTE.paper, { rough: 0.9 })}
          castShadow
        >
          <boxGeometry args={[0.21, 0.01, 0.29]} />
        </mesh>
      ))}
    </group>
  );
}
