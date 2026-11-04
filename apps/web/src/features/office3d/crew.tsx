"use client";

/* The people layer: one controller per agent, synced to the live state,
 * plus the papers that fly when work is handed out or finished. */

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { Move, OfficeAgent } from "@/features/office/model";
import type { ScreenBus } from "./bus";
import { looksFor, Person } from "./character";
import { Pet } from "./pet";
import {
  activityOf,
  type Ctl,
  goTo,
  handOff,
  homeSeat,
  makeCtl,
  seatFor,
  setGrid,
  tick,
} from "./controller";
import { mat, PALETTE } from "./furniture-base";
import { OUTPUT_SHELF } from "./layout";
import { makeGrid } from "./nav";

type Paper = {
  id: string;
  from: THREE.Vector3;
  to: THREE.Vector3;
  start: number;
};
const card = new THREE.BoxGeometry(0.2, 0.012, 0.27);

/** The agent's controller, made the first time it is seen (starting in place). */
function ensure(
  map: Map<string, Ctl>,
  a: OfficeAgent,
  i: number,
  members: number,
): Ctl {
  let c = map.get(a.key);
  if (!c) {
    c = makeCtl(a.key, seatFor(a, i, members), homeSeat(i));
    map.set(a.key, c);
  }
  return c;
}

export function Crew({
  agents,
  accents,
  offline,
  moved,
  selected,
  hovered,
  still,
  bus,
  onSelect,
  onHover,
}: {
  hovered: string | null;
  bus: ScreenBus;
  onHover: (key: string | null) => void;
  agents: OfficeAgent[];
  accents: string[];
  offline: boolean;
  moved: Move[];
  selected: string | null;
  still: boolean;
  onSelect: (key: string) => void;
}) {
  const members = Math.max(0, agents.length - 1);
  const grid = useMemo(() => makeGrid(members), [members]);
  setGrid(grid);
  const [ctls] = useState(() => ({ current: new Map<string, Ctl>() }));
  const papers = useRef<Paper[]>([]);
  const paperMeshes = useRef<(THREE.Mesh | null)[]>([]);
  const clock = useRef(0);

  // keep every controller pointed at where the real state says it should be
  useEffect(() => {
    const seen = new Set<string>();
    agents.forEach((a, i) => {
      seen.add(a.key);
      const seat = seatFor(a, i, members);
      const c = ensure(ctls.current, a, i, members);
      c.home = homeSeat(i);
      goTo(c, seat);
      c.activity = activityOf(a, offline);
    });
    for (const k of [...ctls.current.keys()])
      if (!seen.has(k)) ctls.current.delete(k);
  }, [agents, members, offline, ctls]);

  // real events: the Co-Founder walks new work over; finished work flies to the shelf
  useEffect(() => {
    if (moved.length === 0) return;
    const index = new Map(agents.map((a, i) => [a.key, i]));
    const cofounder = ctls.current.get("cofounder");
    for (const m of moved) {
      const i = index.get(m.to);
      if (i === undefined) continue;
      const home = homeSeat(i);
      if (m.done) {
        papers.current.push({
          id: m.id,
          from: new THREE.Vector3(
            home.at.x,
            1.0,
            home.at.z + (home.face === 0 ? 0.6 : -0.6),
          ),
          to: new THREE.Vector3(
            OUTPUT_SHELF.x + 0.3,
            1.3,
            OUTPUT_SHELF.z + 1.6,
          ),
          start: clock.current + papers.current.length * 0.4,
        });
      } else if (
        cofounder &&
        !still &&
        cofounder.phase === "seated" &&
        cofounder.seat.id === cofounder.home.id &&
        agents[0]?.place === "desk"
      ) {
        handOff(cofounder, home, cofounder.home);
      }
    }
    papers.current = papers.current.slice(-6);
  }, [moved, agents, still, ctls]);

  useFrame((_, dt) => {
    const step = Math.min(dt, 0.1);
    clock.current += step;
    const all = [...ctls.current.values()];
    for (const c of all) tick(c, step, all, still);
    papers.current = papers.current.filter(
      (p) => clock.current - p.start < 1.6,
    );
    paperMeshes.current.forEach((mesh, i) => {
      if (!mesh) return;
      const p = papers.current[i];
      const k = p ? (clock.current - p.start) / 1.6 : -1;
      mesh.visible = !!p && k >= 0;
      if (!p || k < 0) return;
      const e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
      mesh.position.lerpVectors(p.from, p.to, e);
      mesh.position.y += Math.sin(Math.PI * k) * 1.2;
      mesh.rotation.y = k * Math.PI * 2;
    });
  });

  return (
    <group>
      {agents.map((a, i) => {
        const c = ensure(ctls.current, a, i, members);
        return (
          <Person
            key={a.key}
            ctl={c}
            looks={looksFor(a.key, accents[i] ?? PALETTE.sage)}
            bus={bus}
            activity={activityOf(a, offline)}
            selected={selected === a.key}
            hovered={hovered === a.key}
            onHover={(on) => {
              onHover(on ? a.key : null);
            }}
            onSelect={() => {
              onSelect(a.key);
            }}
          />
        );
      })}
      {agents.map((a, i) => {
        const c = ctls.current.get(a.key);
        const atDesk = !!c && c.seat.id === c.home.id && c.phase === "seated";
        const act = activityOf(a, offline);
        return (
          <Pet
            key={`pet-${a.key}`}
            kind={a.look.pet}
            home={homeSeat(i)}
            awake={
              atDesk &&
              (act === "working" || act === "waiting" || act === "blocked")
            }
          />
        );
      })}
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <mesh
          key={i}
          ref={(m) => {
            paperMeshes.current[i] = m;
          }}
          geometry={card}
          material={mat(PALETTE.paper, { rough: 0.9 })}
          visible={false}
          castShadow
        />
      ))}
    </group>
  );
}
