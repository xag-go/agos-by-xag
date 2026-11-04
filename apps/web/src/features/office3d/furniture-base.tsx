"use client";

import { RoundedBox } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";
import type { Rect } from "./layout";

export const PALETTE = {
  oak: "#c79a6b",
  oakDark: "#a87c52",
  oakLight: "#dcb48a",
  ivory: "#f3eee6",
  ivoryShade: "#e6dfd3",
  sage: "#9cb59a",
  sageDark: "#7c9a7b",
  charcoal: "#2e3033",
  charcoalSoft: "#45484d",
  brass: "#c9a45c",
  fabric: "#5f6f66",
  fabricWarm: "#c98d6b",
  leaf: "#5c8f5a",
  leafLight: "#7fb070",
  pot: "#d9cfc2",
  glass: "#dfeee9",
  paper: "#fbfaf6",
};

const cache = new Map<string, THREE.Material>();
export function mat(
  color: string,
  opts: {
    rough?: number;
    metal?: number;
    emissive?: string;
    emissiveIntensity?: number;
    opacity?: number;
  } = {},
): THREE.Material {
  const key = JSON.stringify([color, opts]);
  let m = cache.get(key);
  if (!m) {
    m = new THREE.MeshStandardMaterial({
      color,
      roughness: opts.rough ?? 0.7,
      metalness: opts.metal ?? 0,
      emissive: opts.emissive ?? "#000000",
      emissiveIntensity: opts.emissiveIntensity ?? 0,
      transparent: opts.opacity !== undefined,
      opacity: opts.opacity ?? 1,
      depthWrite: opts.opacity === undefined,
    });
    cache.set(key, m);
  }
  return m;
}

export function Box({
  p,
  s,
  m,
  r = 0.03,
  shadow = true,
}: {
  p: [number, number, number];
  s: [number, number, number];
  m: THREE.Material;
  r?: number;
  shadow?: boolean;
}) {
  return (
    <RoundedBox
      args={s}
      radius={Math.min(r, ...s.map((v) => v / 2 - 0.001))}
      smoothness={3}
      position={p}
      material={m}
      castShadow={shadow}
      receiveShadow
    />
  );
}

// ---- room shell ------------------------------------------------------------

function oakTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 512;
  const g = c.getContext("2d");
  if (g) {
    g.fillStyle = "#c99d6e";
    g.fillRect(0, 0, 512, 512);
    const tones = ["#c69a6a", "#cca174", "#c39566", "#d0a679", "#c89c6d"];
    for (let row = 0; row < 16; row++) {
      let x = (row % 3) * -90;
      while (x < 512) {
        const len = 160 + ((row * 37 + x) % 120);
        g.fillStyle =
          tones[(row + Math.floor(x / 40)) % tones.length] ?? "#c99d6e";
        g.fillRect(x + 1, row * 32 + 1, len - 2, 30);
        g.fillStyle = "rgba(90,60,30,.08)";
        for (let k = 0; k < 4; k++)
          g.fillRect(x + 4, row * 32 + 6 + k * 6, len - 10, 1);
        x += len;
      }
    }
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = THREE.RepeatWrapping;
  t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

export function Floor({ w, d }: { w: number; d: number }) {
  const tex = useMemo(() => {
    const t = oakTexture();
    t.repeat.set(w / 4, d / 4);
    return t;
  }, [w, d]);
  return (
    <group>
      <mesh
        rotation-x={-Math.PI / 2}
        position={[w / 2, 0, d / 2]}
        receiveShadow
      >
        <planeGeometry args={[w, d]} />
        <meshStandardMaterial map={tex} roughness={0.62} />
      </mesh>
      {/* the diorama's base */}
      <Box
        p={[w / 2, -0.18, d / 2]}
        s={[w + 0.3, 0.34, d + 0.3]}
        m={mat("#3a3632")}
        r={0.08}
        shadow={false}
      />
    </group>
  );
}

export function Rug({
  r,
  color,
  edge,
}: {
  r: Rect;
  color: string;
  edge: string;
}) {
  return (
    <group position={[r.x + r.w / 2, 0.006, r.z + r.d / 2]}>
      <mesh
        rotation-x={-Math.PI / 2}
        receiveShadow
        material={mat(edge, { rough: 1 })}
      >
        <planeGeometry args={[r.w, r.d]} />
      </mesh>
      <mesh
        rotation-x={-Math.PI / 2}
        position-y={0.002}
        receiveShadow
        material={mat(color, { rough: 1 })}
      >
        <planeGeometry args={[r.w - 0.2, r.d - 0.2]} />
      </mesh>
    </group>
  );
}

export function Walls({
  w,
  d,
  evening,
}: {
  w: number;
  d: number;
  evening: boolean;
}) {
  const glassDay = mat("#cfe9f5", {
    emissive: "#bfe4ff",
    emissiveIntensity: 0.9,
    rough: 0.2,
  });
  const glassNight = mat("#1d2a44", {
    emissive: "#2a3d66",
    emissiveIntensity: 0.6,
    rough: 0.2,
  });
  const H = 2.9;
  return (
    <group>
      {/* back wall */}
      <Box
        p={[w / 2, H / 2, 0.08]}
        s={[w, H, 0.16]}
        m={mat(PALETTE.ivory)}
        r={0.02}
      />
      <Box
        p={[w / 2, 0.06, 0.18]}
        s={[w, 0.12, 0.04]}
        m={mat(PALETTE.sageDark)}
        r={0.01}
        shadow={false}
      />
      {/* left wall */}
      <Box
        p={[0.08, H / 2, d / 2]}
        s={[0.16, H, d]}
        m={mat(PALETTE.ivoryShade)}
        r={0.02}
      />
      <Box
        p={[0.18, 0.06, d / 2]}
        s={[0.04, 0.12, d]}
        m={mat(PALETTE.sageDark)}
        r={0.01}
        shadow={false}
      />
      {/* sage accent band in the studio */}
      <Box
        p={[10.1, 0.65, 0.17]}
        s={[7.8, 1.3, 0.02]}
        m={mat(PALETTE.sage)}
        r={0.005}
        shadow={false}
      />
      {/* windows over the studio */}
      {[7.7, 10, 12.3].map((x) => (
        <group key={x} position={[x, 1.75, 0.17]}>
          <Box
            p={[0, 0, 0]}
            s={[1.5, 1.3, 0.05]}
            m={mat(PALETTE.charcoalSoft, { rough: 0.4 })}
            r={0.02}
            shadow={false}
          />
          <mesh
            position={[0, 0, 0.03]}
            material={evening ? glassNight : glassDay}
          >
            <planeGeometry args={[1.38, 1.18]} />
          </mesh>
          <Box
            p={[0, 0, 0.04]}
            s={[0.04, 1.2, 0.02]}
            m={mat(PALETTE.charcoalSoft)}
            r={0.005}
            shadow={false}
          />
          <Box
            p={[0, -0.7, 0.08]}
            s={[1.6, 0.06, 0.16]}
            m={mat(PALETTE.oakLight)}
            r={0.01}
            shadow={false}
          />
        </group>
      ))}
    </group>
  );
}
