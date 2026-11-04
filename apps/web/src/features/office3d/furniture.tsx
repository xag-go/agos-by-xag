"use client";

import { useMemo } from "react";
import type { Rect } from "./layout";
import { Box, PALETTE, mat } from "./furniture-base";

// ---- props -------------------------------------------------------------------

export function Plant({
  x,
  z,
  size = 1,
}: {
  x: number;
  z: number;
  size?: number;
}) {
  const leaves = useMemo(
    () =>
      Array.from({ length: 7 }, (_, i) => {
        const a = (i / 7) * Math.PI * 2 + i;
        const r = i === 0 ? 0 : 0.14;
        return {
          p: [Math.sin(a) * r, 0.62 + (i % 3) * 0.12, Math.cos(a) * r] as [
            number,
            number,
            number,
          ],
          s: 0.17 + (i % 2) * 0.05,
          c: i % 2 ? PALETTE.leaf : PALETTE.leafLight,
        };
      }),
    [],
  );
  return (
    <group position={[x, 0, z]} scale={size}>
      <mesh
        position={[0, 0.2, 0]}
        castShadow
        receiveShadow
        material={mat(PALETTE.pot, { rough: 0.85 })}
      >
        <cylinderGeometry args={[0.2, 0.15, 0.4, 20]} />
      </mesh>
      {leaves.map((l, i) => (
        <mesh
          key={i}
          position={l.p}
          castShadow
          material={mat(l.c, { rough: 0.8 })}
        >
          <icosahedronGeometry args={[l.s, 1]} />
        </mesh>
      ))}
    </group>
  );
}

export function Books({
  x,
  z,
  rot = 0,
}: {
  x: number;
  z: number;
  rot?: number;
}) {
  const colors = [
    "#c98d6b",
    PALETTE.sageDark,
    "#d9c38f",
    PALETTE.charcoalSoft,
    "#b45f4d",
  ];
  return (
    <group position={[x, 0.74, z]} rotation-y={rot}>
      {colors.map((c, i) => (
        <Box
          key={c}
          p={[i * 0.045 - 0.09, 0.1 - (i % 2) * 0.015, 0]}
          s={[0.04, 0.2 - (i % 2) * 0.03, 0.15]}
          m={mat(c)}
          r={0.004}
        />
      ))}
    </group>
  );
}

export function Shelf({ rect, height = 1.9 }: { rect: Rect; height?: number }) {
  const wood = mat(PALETTE.oakDark, { rough: 0.6 });
  const along = rect.w >= rect.d;
  const len = along ? rect.w : rect.d;
  const depth = along ? rect.d : rect.w;
  return (
    <group
      position={[rect.x + rect.w / 2, 0, rect.z + rect.d / 2]}
      rotation-y={along ? 0 : Math.PI / 2}
    >
      {[0, 1, 2, 3].map((i) => (
        <Box
          key={i}
          p={[0, 0.05 + (i * (height - 0.1)) / 3, 0]}
          s={[len, 0.04, depth]}
          m={wood}
          r={0.01}
        />
      ))}
      {[-1, 1].map((s) => (
        <Box
          key={s}
          p={[(s * len) / 2, height / 2, 0]}
          s={[0.04, height, depth]}
          m={wood}
          r={0.01}
        />
      ))}
    </group>
  );
}

export function Sofa({
  x,
  z,
  w = 3,
  color = PALETTE.fabric,
}: {
  x: number;
  z: number;
  w?: number;
  color?: string;
}) {
  const m = mat(color, { rough: 0.95 });
  return (
    <group position={[x, 0, z]}>
      <Box p={[0, 0.22, 0]} s={[w, 0.3, 0.9]} m={m} r={0.08} />
      <Box p={[0, 0.58, -0.36]} s={[w, 0.5, 0.2]} m={m} r={0.08} />
      {[-1, 1].map((s) => (
        <Box
          key={s}
          p={[(s * (w - 0.18)) / 2, 0.42, 0]}
          s={[0.18, 0.4, 0.9]}
          m={m}
          r={0.07}
        />
      ))}
      {[-1, 0, 1].map((i) => (
        <Box
          key={i}
          p={[i * ((w - 0.4) / 3), 0.42, 0.05]}
          s={[(w - 0.45) / 3, 0.12, 0.72]}
          m={mat(color, { rough: 1 })}
          r={0.05}
        />
      ))}
    </group>
  );
}

export function Armchair({
  x,
  z,
  face,
  color = PALETTE.fabricWarm,
}: {
  x: number;
  z: number;
  face: number;
  color?: string;
}) {
  const m = mat(color, { rough: 0.95 });
  return (
    <group position={[x, 0, z]} rotation-y={face}>
      <Box p={[0, 0.22, 0]} s={[0.78, 0.3, 0.74]} m={m} r={0.08} />
      <Box p={[0, 0.55, -0.3]} s={[0.78, 0.45, 0.16]} m={m} r={0.07} />
      {[-1, 1].map((s) => (
        <Box
          key={s}
          p={[s * 0.32, 0.42, 0]}
          s={[0.14, 0.32, 0.74]}
          m={m}
          r={0.06}
        />
      ))}
    </group>
  );
}
