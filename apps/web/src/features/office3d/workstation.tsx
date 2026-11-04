"use client";

import { RoundedBox } from "@react-three/drei";
import type * as THREE from "three";
import { Books, Plant } from "./furniture";
import {
  Chair,
  Desk,
  DeskLamp,
  Keyboard,
  Monitor,
  Mug,
  PaperStack,
} from "./furniture-desk";
import { mat, PALETTE } from "./furniture-base";
import type { Station } from "./layout";

export type DeskState = "off" | "code" | "alert" | "ask" | "saver" | "think";

export type StationInfo = {
  key: string;
  title: string;
  accent: string;
  screen: DeskState;
};

export function Box({
  p,
  s,
  m,
  r = 0.02,
}: {
  p: [number, number, number];
  s: [number, number, number];
  m: THREE.Material;
  r?: number;
}) {
  return (
    <RoundedBox
      args={s}
      radius={r}
      smoothness={3}
      position={p}
      material={m}
      castShadow
      receiveShadow
    />
  );
}

// ---- role props --------------------------------------------------------------

function RoleProps({
  title,
  st,
  accent,
}: {
  title: string;
  st: Station;
  accent: string;
}) {
  const t = title.toLowerCase();
  const side = st.deskFace === 0 ? 1 : -1; // towards the sitter
  const x = st.desk.x + st.desk.w / 2;
  const z = st.desk.z + st.desk.d / 2;
  const right = x + 0.58;
  const left = x - 0.6;
  const brass = mat(PALETTE.brass, { metal: 0.8, rough: 0.3 });
  const dark = mat(PALETTE.charcoal, { rough: 0.4 });
  if (t.includes("voice")) {
    return (
      <group>
        <group position={[left, 0.74, z]}>
          <mesh position={[0, 0.01, 0]} material={dark}>
            <cylinderGeometry args={[0.06, 0.07, 0.02, 14]} />
          </mesh>
          <mesh position={[0, 0.12, 0]} material={brass}>
            <cylinderGeometry args={[0.008, 0.008, 0.22, 6]} />
          </mesh>
          <mesh position={[0, 0.26, 0]} material={dark} castShadow>
            <capsuleGeometry args={[0.035, 0.07, 6, 12]} />
          </mesh>
        </group>
        <mesh
          position={[right, 0.79, z - side * 0.05]}
          rotation-x={Math.PI / 2}
          material={mat(accent, { rough: 0.6 })}
          castShadow
        >
          <torusGeometry args={[0.08, 0.018, 8, 20, Math.PI]} />
        </mesh>
      </group>
    );
  }
  if (t.includes("idea")) {
    const notes = ["#f6d878", "#f2a7a0", "#a8d5ba", "#f6d878", "#a9c8ec"];
    return (
      <group>
        {notes.map((c, i) => (
          <mesh
            key={i}
            position={[
              left - 0.05 + (i % 3) * 0.09,
              0.752 + i * 0.002,
              z + (i < 3 ? -0.08 : 0.06) * side,
            ]}
            rotation-y={i * 0.3}
            material={mat(c, { rough: 0.9 })}
          >
            <boxGeometry args={[0.08, 0.004, 0.08]} />
          </mesh>
        ))}
        <mesh
          position={[right, 0.86, z]}
          material={mat("#fff7d6", {
            emissive: "#ffd36b",
            emissiveIntensity: 0.6,
          })}
          castShadow
        >
          <sphereGeometry args={[0.06, 16, 12]} />
        </mesh>
        <mesh position={[right, 0.78, z]} material={brass}>
          <cylinderGeometry args={[0.03, 0.04, 0.06, 12]} />
        </mesh>
      </group>
    );
  }
  if (t.includes("media") || t.includes("intake")) {
    return (
      <group position={[left, 0.74, z]}>
        <Box p={[0, 0.06, 0]} s={[0.2, 0.12, 0.12]} m={dark} />
        <mesh
          position={[0, 0.06, 0.08 * side]}
          rotation-x={Math.PI / 2}
          material={mat("#1b1c1e", { rough: 0.2, metal: 0.4 })}
        >
          <cylinderGeometry args={[0.045, 0.05, 0.08, 16]} />
        </mesh>
        <Box p={[0.07, 0.13, 0]} s={[0.04, 0.02, 0.04]} m={brass} r={0.006} />
        <Box
          p={[1.15, 0.01, 0]}
          s={[0.12, 0.02, 0.08]}
          m={mat(accent)}
          r={0.006}
        />
      </group>
    );
  }
  if (t.includes("research") || t.includes("check")) {
    return (
      <group>
        <Books x={left} z={z} />
        <group position={[right, 0.76, z]} rotation-y={0.6}>
          <mesh rotation-x={Math.PI / 2} material={brass}>
            <torusGeometry args={[0.06, 0.01, 8, 20]} />
          </mesh>
          <mesh position={[0.1, 0, 0]} rotation-z={Math.PI / 2} material={dark}>
            <cylinderGeometry args={[0.012, 0.012, 0.1, 8]} />
          </mesh>
        </group>
      </group>
    );
  }
  if (t.includes("script") || t.includes("writ")) {
    return (
      <group>
        <PaperStack x={left} z={z} n={6} rot={0.15} />
        <mesh
          position={[left + 0.02, 0.83, z]}
          rotation-z={Math.PI / 2}
          rotation-y={0.5}
          material={mat(accent)}
        >
          <cylinderGeometry args={[0.007, 0.007, 0.16, 6]} />
        </mesh>
        <Mug x={right} z={z} color={accent} />
      </group>
    );
  }
  if (t.includes("topic") || t.includes("scout")) {
    return (
      <group position={[left, 0.74, z]}>
        <mesh position={[0, 0.02, 0]} material={brass}>
          <cylinderGeometry args={[0.05, 0.06, 0.03, 14]} />
        </mesh>
        <mesh
          position={[0, 0.17, 0]}
          material={mat("#7fb2c8", { rough: 0.5 })}
          castShadow
        >
          <sphereGeometry args={[0.11, 20, 16]} />
        </mesh>
        <mesh position={[0, 0.17, 0]} rotation-z={0.4} material={brass}>
          <torusGeometry args={[0.13, 0.006, 6, 24, Math.PI]} />
        </mesh>
      </group>
    );
  }
  return <Plant x={left} z={z} size={0.4} />;
}

// ---- workstations ----------------------------------------------------------------

export function Workstation({
  st,
  info,
  screen,
  evening,
}: {
  st: Station;
  info: StationInfo;
  screen: THREE.Material;
  evening: boolean;
}) {
  const cofounder = st.index < 0;
  const fx = Math.sin(st.deskFace);
  const fz = Math.cos(st.deskFace);
  const kbX = st.seat.at.x + fx * 0.5;
  const kbZ = st.seat.at.z + fz * 0.5;
  // across the desk, perpendicular to the way the sitter looks
  const side = (d: number) => ({
    x: st.monitor.x - fz * d,
    z: st.monitor.z + fx * d,
  });
  return (
    <group>
      <Desk rect={st.desk} accent={info.accent} twin={cofounder} />
      {cofounder ? (
        <>
          <Monitor {...side(-0.42)} face={st.deskFace - 0.12} screen={screen} />
          <Monitor {...side(0.42)} face={st.deskFace + 0.12} screen={screen} />
          <DeskLamp {...side(-1.0)} lit={evening} />
          <Books {...side(1.0)} rot={st.deskFace} />
          <Mug x={kbX - fz * 0.45} z={kbZ + fx * 0.45} color={PALETTE.sage} />
        </>
      ) : (
        <>
          <Monitor
            x={st.monitor.x}
            z={st.monitor.z}
            face={st.deskFace}
            screen={screen}
          />
          <RoleProps title={info.title} st={st} accent={info.accent} />
        </>
      )}
      <Keyboard x={kbX} z={kbZ} face={st.deskFace} />
      <Chair
        x={st.seat.at.x}
        z={st.seat.at.z}
        face={st.deskFace}
        color={cofounder ? "#3f4a45" : PALETTE.fabric}
      />
    </group>
  );
}
