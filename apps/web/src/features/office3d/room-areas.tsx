"use client";

import type * as THREE from "three";
import { Armchair, Books, Plant, Shelf, Sofa } from "./furniture";
import { Chair, Mug, PaperStack } from "./furniture-desk";
import { mat, PALETTE, Rug } from "./furniture-base";
import {
  lounge,
  meetingSeats,
  meetingRoom,
  tableOf,
  barCount,
  barZ,
  OUTPUT_SHELF,
  ZONES,
} from "./layout";
import { Box } from "./workstation";

// ---- rooms ---------------------------------------------------------------------

function GlassWall({
  x,
  z,
  w,
  d,
}: {
  x: number;
  z: number;
  w: number;
  d: number;
}) {
  const frame = mat("#8d948f", { metal: 0.5, rough: 0.35 });
  const glass = mat("#e7f1ee", { opacity: 0.38, rough: 0.15 });
  const along = w > d;
  const len = along ? w : d;
  return (
    <group
      position={[x + w / 2, 0, z + d / 2]}
      rotation-y={along ? 0 : Math.PI / 2}
    >
      <mesh position={[0, 1.3, 0]} material={glass}>
        <boxGeometry args={[len, 2.5, 0.03]} />
      </mesh>
      <mesh
        position={[0, 0.9, 0.02]}
        material={mat("#f6faf8", { opacity: 0.55 })}
      >
        <boxGeometry args={[len, 0.5, 0.005]} />
      </mesh>
      {[0.03, 2.57].map((y) => (
        <mesh key={y} position={[0, y, 0]} material={frame}>
          <boxGeometry args={[len, 0.035, 0.04]} />
        </mesh>
      ))}
      {[-len / 2, len / 2].map((p) => (
        <mesh key={p} position={[p, 1.3, 0]} material={frame}>
          <boxGeometry args={[0.035, 2.6, 0.04]} />
        </mesh>
      ))}
    </group>
  );
}

export function MeetingRoom({
  screen,
  members,
}: {
  screen: THREE.Material;
  members: number;
}) {
  const r = meetingRoom(members);
  const t = tableOf(members);
  return (
    <group>
      <Rug
        r={{ x: r.x + 0.5, z: 0.6, w: r.w - 0.9, d: r.d - 1.1 }}
        color="#c9d5c4"
        edge={PALETTE.sageDark}
      />
      <GlassWall x={14.5} z={0} w={0.15} d={r.d - 2.1} />
      <GlassWall x={14.5} z={r.d - 0.3} w={0.15} d={0.3} />
      <GlassWall x={14.5} z={r.d - 0.1} w={5.5} d={0.15} />
      {/* long table: one more chair each side whenever the team grows */}
      <group position={[t.x, 0, t.z]}>
        <Box
          p={[0, 0.72, 0]}
          s={[t.rx * 2, 0.05, t.rz * 2]}
          m={mat(PALETTE.oakLight, { rough: 0.5 })}
          r={0.2}
        />
        {[-1, 1].map((e) => (
          <mesh
            key={e}
            position={[0, 0.36, e * (t.rz - 0.35)]}
            castShadow
            material={mat(PALETTE.charcoal, { metal: 0.4, rough: 0.4 })}
          >
            <cylinderGeometry args={[0.06, 0.2, 0.7, 16]} />
          </mesh>
        ))}
        <PaperStack x={-0.15} z={-t.rz + 0.5} n={3} y={0.745} rot={0.3} />
        <Mug x={0.2} z={t.rz - 0.5} y={0.745} color={PALETTE.sage} />
      </group>
      {meetingSeats(members).map((s) => (
        <Chair
          key={s.id}
          x={s.at.x}
          z={s.at.z}
          face={s.face}
          color={PALETTE.sageDark}
        />
      ))}
      {/* wall screen */}
      <group position={[17.3, 1.7, 0.2]}>
        <Box
          p={[0, 0, 0]}
          s={[1.9, 1.05, 0.05]}
          m={mat(PALETTE.charcoal, { rough: 0.3 })}
        />
        <mesh position={[0, 0, 0.03]} material={screen}>
          <planeGeometry args={[1.8, 0.95]} />
        </mesh>
      </group>
      <Plant x={19.5} z={0.7} size={1.1} />
    </group>
  );
}

function Stool({ x, z }: { x: number; z: number }) {
  return (
    <group position={[x, 0, z]}>
      <mesh
        position={[0, 0.64, 0]}
        castShadow
        material={mat(PALETTE.fabricWarm, { rough: 0.9 })}
      >
        <cylinderGeometry args={[0.18, 0.17, 0.07, 20]} />
      </mesh>
      <mesh
        position={[0, 0.32, 0]}
        material={mat(PALETTE.brass, { metal: 0.8, rough: 0.3 })}
      >
        <cylinderGeometry args={[0.02, 0.02, 0.62, 8]} />
      </mesh>
      <mesh
        position={[0, 0.2, 0]}
        rotation-x={Math.PI / 2}
        material={mat(PALETTE.brass, { metal: 0.8, rough: 0.3 })}
      >
        <torusGeometry args={[0.13, 0.01, 6, 20]} />
      </mesh>
      <mesh position={[0, 0.01, 0]} material={mat(PALETTE.charcoal)}>
        <cylinderGeometry args={[0.16, 0.16, 0.02, 16]} />
      </mesh>
    </group>
  );
}

export function Lounge({
  members,
  evening,
}: {
  members: number;
  evening: boolean;
}) {
  const l = lounge(members);
  return (
    <group>
      <Rug
        r={{ x: l.x + 0.4, z: l.z + 0.1, w: l.w - 0.6, d: l.d - 0.2 }}
        color="#e2c9a8"
        edge="#c79a6b"
      />
      <Sofa x={17.3} z={l.z + 0.67} w={3.0} />
      <Armchair x={15.55} z={l.z + 2.35} face={Math.PI / 2} />
      <Armchair x={19.05} z={l.z + 2.35} face={-Math.PI / 2} />
      {/* coffee table */}
      <group position={[17.3, 0, l.z + 2.25]}>
        <mesh
          position={[0, 0.38, 0]}
          scale={[0.7, 1, 0.4]}
          castShadow
          receiveShadow
          material={mat(PALETTE.oak, { rough: 0.5 })}
        >
          <cylinderGeometry args={[1, 1, 0.04, 32]} />
        </mesh>
        <mesh position={[0, 0.18, 0]} material={mat(PALETTE.charcoal)}>
          <cylinderGeometry args={[0.04, 0.12, 0.36, 12]} />
        </mesh>
        <Books x={-0.25} z={0} rot={1.2} />
      </group>
      {/* high tables with stools: one more row whenever the team needs it */}
      {Array.from({ length: barCount(members) }, (_, k) => (
        <group key={k}>
          {k > 0 && (
            <group position={[17.5, 0, barZ(members, k)]}>
              <Box
                p={[0, 0.48, 0]}
                s={[3.8, 0.96, 0.62]}
                m={mat(PALETTE.sage, { rough: 0.8 })}
                r={0.03}
              />
              <Box
                p={[0, 0.98, 0]}
                s={[3.9, 0.05, 0.7]}
                m={mat(PALETTE.oakLight, { rough: 0.5 })}
                r={0.015}
              />
              <Mug x={-0.9} z={0.05} y={1.0} />
            </group>
          )}
          {[0, 1, 2, 3].map((i) => (
            <Stool key={i} x={16.2 + i * 0.75} z={barZ(members, k) - 0.72} />
          ))}
        </group>
      ))}
      {/* coffee bar */}
      <group position={[17.5, 0, barZ(members, 0)]}>
        <Box
          p={[0, 0.48, 0]}
          s={[3.8, 0.96, 0.62]}
          m={mat(PALETTE.sage, { rough: 0.8 })}
          r={0.03}
        />
        <Box
          p={[0, 0.98, 0]}
          s={[3.9, 0.05, 0.7]}
          m={mat(PALETTE.oakLight, { rough: 0.5 })}
          r={0.015}
        />
        <group position={[-1.2, 1.0, -0.05]}>
          <Box
            p={[0, 0.2, 0]}
            s={[0.36, 0.4, 0.34]}
            m={mat(PALETTE.charcoal, { rough: 0.35, metal: 0.3 })}
            r={0.04}
          />
          <Box
            p={[0, 0.06, 0.12]}
            s={[0.12, 0.03, 0.08]}
            m={mat(PALETTE.brass, { metal: 0.8, rough: 0.3 })}
            r={0.01}
          />
          <mesh
            position={[0.1, 0.34, 0.18]}
            material={mat("#ff8a5c", {
              emissive: "#ff6a3c",
              emissiveIntensity: 1.2,
            })}
          >
            <sphereGeometry args={[0.015, 8, 6]} />
          </mesh>
        </group>
        {[-0.5, -0.35, -0.2].map((x) => (
          <Mug key={x} x={x} z={0.05} y={1.0} />
        ))}
        <mesh
          position={[0.6, 1.08, 0]}
          castShadow
          material={mat("#e9d9b8", { rough: 0.8 })}
        >
          <cylinderGeometry args={[0.16, 0.12, 0.12, 20]} />
        </mesh>
        {[0.45, 0.6, 0.75].map((x, i) => (
          <mesh
            key={x}
            position={[x, 1.16, (i - 1) * 0.04]}
            material={mat(["#e98a54", "#e9c35a", "#b6d36b"][i] ?? "#fff")}
          >
            <sphereGeometry args={[0.05, 12, 10]} />
          </mesh>
        ))}
      </group>
      {/* floor lamp */}
      <group position={[19.5, 0, l.z + 0.6]}>
        <mesh
          position={[0, 0.8, 0]}
          material={mat(PALETTE.brass, { metal: 0.8, rough: 0.3 })}
        >
          <cylinderGeometry args={[0.012, 0.012, 1.6, 8]} />
        </mesh>
        <mesh
          position={[0, 1.62, 0]}
          material={mat("#f3e6cc", {
            emissive: "#ffcf7a",
            emissiveIntensity: evening ? 1.3 : 0.05,
            rough: 0.9,
          })}
        >
          <cylinderGeometry args={[0.16, 0.22, 0.26, 20, 1, true]} />
        </mesh>
        <mesh position={[0, 0.01, 0]} material={mat(PALETTE.charcoal)}>
          <cylinderGeometry args={[0.15, 0.15, 0.02, 16]} />
        </mesh>
      </group>
    </group>
  );
}

export function FloorLamp({
  x,
  z,
  lit,
}: {
  x: number;
  z: number;
  lit: boolean;
}) {
  return (
    <group position={[x, 0, z]}>
      <mesh
        position={[0, 0.8, 0]}
        material={mat(PALETTE.brass, { metal: 0.8, rough: 0.3 })}
      >
        <cylinderGeometry args={[0.012, 0.012, 1.6, 8]} />
      </mesh>
      <mesh
        position={[0, 1.62, 0]}
        material={mat("#f3e6cc", {
          emissive: "#ffcf7a",
          emissiveIntensity: lit ? 1.3 : 0.05,
          rough: 0.9,
        })}
      >
        <cylinderGeometry args={[0.16, 0.22, 0.26, 20, 1, true]} />
      </mesh>
      <mesh position={[0, 0.01, 0]} material={mat(PALETTE.charcoal)}>
        <cylinderGeometry args={[0.15, 0.15, 0.02, 16]} />
      </mesh>
    </group>
  );
}

export function OutputCorner({ done }: { done: number }) {
  const perShelf = 8;
  return (
    <group>
      <Rug
        r={{ x: 0.6, z: 6.9, w: 4.6, d: 3.9 }}
        color="#d7ddd2"
        edge={PALETTE.sageDark}
      />
      <Shelf rect={OUTPUT_SHELF} height={1.9} />
      {Array.from({ length: Math.min(done, perShelf * 3) }, (_, i) => {
        const shelf = Math.floor(i / perShelf);
        const k = i % perShelf;
        return (
          <mesh
            key={i}
            position={[
              0.5,
              0.1 + ((shelf + 1) * 1.8) / 3 - 0.48,
              7.6 + k * 0.36,
            ]}
            rotation-x={-0.08}
            castShadow
            material={mat(
              k % 3 === 0
                ? PALETTE.sage
                : k % 3 === 1
                  ? PALETTE.paper
                  : "#e9d9b8",
              { rough: 0.9 },
            )}
          >
            <boxGeometry args={[0.28, 0.34, 0.05]} />
          </mesh>
        );
      })}
      {/* printer table + printer */}
      <group position={[4.1, 0, 9.6]}>
        <Box
          p={[0, 0.36, 0]}
          s={[1.4, 0.05, 0.7]}
          m={mat(PALETTE.oak, { rough: 0.55 })}
        />
        {[-0.62, 0.62].map((x) => (
          <Box
            key={x}
            p={[x, 0.17, 0]}
            s={[0.05, 0.34, 0.6]}
            m={mat(PALETTE.charcoal)}
            r={0.01}
          />
        ))}
        <Box
          p={[-0.2, 0.52, 0]}
          s={[0.6, 0.28, 0.48]}
          m={mat("#ecebe7", { rough: 0.5 })}
          r={0.04}
        />
        <Box
          p={[-0.2, 0.67, 0.05]}
          s={[0.4, 0.02, 0.3]}
          m={mat(PALETTE.paper)}
          r={0.005}
        />
        <PaperStack x={0.38} z={0} n={4} y={0.385} />
      </group>
      {/* water cooler */}
      <group position={[5.05, 0, 6.85]}>
        <Box
          p={[0, 0.5, 0]}
          s={[0.36, 1.0, 0.36]}
          m={mat("#e8e6e1", { rough: 0.5 })}
          r={0.04}
        />
        <mesh
          position={[0, 1.2, 0]}
          material={mat("#bfe3f2", { opacity: 0.7, rough: 0.1 })}
        >
          <cylinderGeometry args={[0.15, 0.15, 0.4, 20]} />
        </mesh>
      </group>
    </group>
  );
}

export function CofounderCorner() {
  const z = ZONES.cofounder;
  return (
    <group>
      <Rug
        r={{ x: 0.6, z: 0.6, w: z.w - 1.0, d: z.d - 1.0 }}
        color="#d8c7ae"
        edge="#b48c64"
      />
      <Shelf rect={{ x: 0.5, z: 0.25, w: 1.7, d: 0.35 }} height={2.0} />
      {[0.5, 0.95, 1.4].map((y, row) =>
        [0.7, 0.85, 1.0, 1.15, 1.55, 1.7].map((x, i) => (
          <mesh
            key={`${String(y)}-${String(x)}`}
            position={[x, y + 0.13 + (i % 2) * 0.01, 0.42]}
            castShadow
            material={mat(
              [
                "#b45f4d",
                PALETTE.sageDark,
                "#d9c38f",
                PALETTE.charcoalSoft,
                "#c98d6b",
              ][(i + row) % 5] ?? "#999",
            )}
          >
            <boxGeometry args={[0.1, 0.24 - (i % 2) * 0.04, 0.26]} />
          </mesh>
        )),
      )}
      <Armchair x={1.3} z={4.9} face={Math.PI * 0.75} color="#7d8f7c" />
      <Armchair x={4.0} z={4.9} face={-Math.PI * 0.75} color="#7d8f7c" />
      <mesh
        position={[2.65, 0.3, 5.0]}
        castShadow
        material={mat(PALETTE.oak, { rough: 0.5 })}
      >
        <cylinderGeometry args={[0.35, 0.35, 0.04, 28]} />
      </mesh>
      <mesh position={[2.65, 0.15, 5.0]} material={mat(PALETTE.charcoal)}>
        <cylinderGeometry args={[0.03, 0.1, 0.28, 10]} />
      </mesh>
      {/* nameplate on the wall */}
      <Box
        p={[3.6, 1.7, 0.19]}
        s={[1.3, 0.5, 0.03]}
        m={mat(PALETTE.charcoal, { rough: 0.4 })}
      />
      <Box
        p={[3.6, 1.7, 0.21]}
        s={[1.1, 0.04, 0.01]}
        m={mat(PALETTE.brass, { metal: 0.8, rough: 0.3 })}
        r={0.004}
      />
    </group>
  );
}
