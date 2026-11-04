"use client";

/* A stylised person: a small rig of groups (hips, spine, head, arms, legs)
 * posed every frame from its controller. Geometry is shared by everyone. */

import { type ThreeEvent, useFrame } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import type { ScreenBus } from "./bus";
import * as THREE from "three";
import type { Activity, Ctl } from "./controller";
import { mat, PALETTE } from "./furniture-base";

const G = {
  torso: new THREE.CapsuleGeometry(0.15, 0.26, 6, 16),
  hipsBlock: new THREE.CapsuleGeometry(0.135, 0.06, 4, 14),
  head: new THREE.SphereGeometry(0.15, 24, 18),
  neck: new THREE.CylinderGeometry(0.05, 0.055, 0.1, 10),
  upperArm: new THREE.CapsuleGeometry(0.048, 0.2, 4, 10),
  foreArm: new THREE.CapsuleGeometry(0.042, 0.18, 4, 10),
  hand: new THREE.SphereGeometry(0.048, 12, 10),
  thigh: new THREE.CapsuleGeometry(0.068, 0.28, 4, 12),
  shin: new THREE.CapsuleGeometry(0.056, 0.32, 4, 12),
  shoe: new THREE.BoxGeometry(0.1, 0.06, 0.2),
  eye: new THREE.SphereGeometry(0.018, 8, 6),
  hairCap: new THREE.SphereGeometry(
    0.158,
    24,
    14,
    0,
    Math.PI * 2,
    0,
    Math.PI * 0.55,
  ),
  hairBack: new THREE.CapsuleGeometry(0.13, 0.12, 4, 14),
  bun: new THREE.SphereGeometry(0.075, 14, 10),
  curl: new THREE.SphereGeometry(0.07, 10, 8),
  ring: new THREE.RingGeometry(0.34, 0.42, 40),
  shadow: new THREE.CircleGeometry(0.3, 24),
  mug: new THREE.CylinderGeometry(0.035, 0.03, 0.09, 12),
  card: new THREE.BoxGeometry(0.16, 0.01, 0.22),
};

const SKINS = ["#f3d2b6", "#e8b994", "#cf9a6e", "#a8714b", "#7d5137"];
const HAIRS = [
  "#2b2420",
  "#5b3a22",
  "#a8692f",
  "#d9b56a",
  "#1f2125",
  "#8f949b",
  "#7a3b2e",
];

function hash(s: string, salt: number) {
  let h = salt;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h;
}

export type Looks = {
  skin: string;
  hair: string;
  cut: number; // 0 short, 1 long, 2 bun, 3 curly
  shirt: string;
  pants: string;
};

/** Same name, same person. */
export function looksFor(key: string, accent: string): Looks {
  return {
    skin: SKINS[hash(key, 7) % SKINS.length] ?? "#e8b994",
    hair: HAIRS[hash(key, 13) % HAIRS.length] ?? "#2b2420",
    cut: hash(key, 3) % 4,
    shirt: accent,
    pants: hash(key, 5) % 2 ? "#33373d" : "#4a4f57",
  };
}

type Rig = {
  root: THREE.Group;
  hips: THREE.Group;
  spine: THREE.Group;
  head: THREE.Group;
  armL: THREE.Group;
  armR: THREE.Group;
  elbowL: THREE.Group;
  elbowR: THREE.Group;
  legL: THREE.Group;
  legR: THREE.Group;
  kneeL: THREE.Group;
  kneeR: THREE.Group;
  mug: THREE.Mesh;
  card: THREE.Mesh;
  ring: THREE.Mesh;
};

const STAND_HIPS = 0.86;

const damp = (cur: number, to: number, dt: number, speed = 10) =>
  cur + (to - cur) * (1 - Math.exp(-dt * speed));

export function Person({
  ctl,
  looks,
  activity,
  selected,
  hovered,
  onHover,
  onSelect,
  bus,
}: {
  bus: ScreenBus;
  ctl: Ctl;
  looks: Looks;
  activity: Activity;
  selected: boolean;
  hovered: boolean;
  onHover: (on: boolean) => void;
  onSelect: () => void;
}) {
  const [r] = useState<{ current: Partial<Rig> }>(() => ({ current: {} }));
  const set =
    <K extends keyof Rig>(k: K) =>
    (v: Rig[K] | null) => {
      if (v) r.current[k] = v;
    };
  const m = useMemo(
    () => ({
      skin: mat(looks.skin, { rough: 0.75 }),
      hair: mat(looks.hair, { rough: 0.85 }),
      shirt: mat(looks.shirt, { rough: 0.9 }),
      pants: mat(looks.pants, { rough: 0.9 }),
      shoe: mat("#26272b", { rough: 0.6 }),
      eye: mat("#1d1b1f", { rough: 0.3 }),
      ring: mat(looks.shirt, {
        emissive: looks.shirt,
        emissiveIntensity: 0.6,
        opacity: 0.9,
      }),
      shadow: mat("#000000", { opacity: 0.18 }),
    }),
    [looks],
  );
  const pose = useRef({
    hips: STAND_HIPS,
    lean: 0,
    thigh: [0, 0],
    knee: [0, 0],
    arm: [0, 0],
    armZ: [0.08, -0.08],
    elbow: [0, 0],
    headY: 0,
    headX: 0,
  });

  const head = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ clock, camera, size }, dt) => {
    const g = r.current as Rig;
    if (!g.root) return;
    const t = clock.elapsedTime;
    const p = pose.current;
    g.root.position.set(ctl.pos.x, 0, ctl.pos.z);
    g.root.rotation.y = ctl.heading;
    g.root.visible = activity !== "offline";

    const seated =
      ctl.phase === "seated" || ctl.phase === "sitDown"
        ? true
        : ctl.phase === "standUp"
          ? ctl.t < 0.25
          : false;
    const walking = ctl.phase === "walk";
    const seatY = ctl.seat.kind === "stand" ? 0 : ctl.seat.seatY;
    const breathe = Math.sin(t * 1.6 + ctl.walk) * 0.012;
    const f = ctl.fidget.kind;
    head
      .set(ctl.pos.x, ctl.phase === "seated" ? 1.55 : 1.9, ctl.pos.z)
      .project(camera);
    bus.set(ctl.key, {
      x: (head.x * 0.5 + 0.5) * size.width,
      y: (-head.y * 0.5 + 0.5) * size.height,
      visible: activity !== "offline",
      thinking:
        f === "think" && activity === "working" && ctl.phase === "seated",
    });
    const settled = ctl.phase === "seated";

    // targets
    let hips = seated ? seatY + 0.05 : STAND_HIPS;
    let lean = 0;
    const thigh = [0, 0];
    const knee = [0, 0];
    const arm = [0, 0];
    const armZ = [0.1, -0.1];
    const elbow = [-0.15, -0.15];
    let headY = 0;
    let headX = 0;

    if (walking) {
      const s = Math.sin(ctl.walk);
      thigh[0] = s * 0.5;
      thigh[1] = -s * 0.5;
      knee[0] = Math.max(0, -Math.cos(ctl.walk)) * 0.7;
      knee[1] = Math.max(0, Math.cos(ctl.walk)) * 0.7;
      arm[0] = -s * 0.4;
      arm[1] = s * 0.4;
      elbow[0] = elbow[1] = -0.35;
      hips += Math.abs(Math.cos(ctl.walk)) * 0.025;
      lean = 0.05;
    } else if (seated) {
      thigh[0] = thigh[1] = -1.5;
      knee[0] = knee[1] = 1.45;
    }

    if (ctl.carrying) {
      arm[1] = -0.85;
      elbow[1] = -0.6;
    } else if (settled) {
      switch (activity) {
        case "working": {
          const tap = Math.sin(t * 14 + ctl.walk) * 0.05;
          arm[0] = -0.8 + tap;
          arm[1] = -0.8 - tap;
          elbow[0] = elbow[1] = -0.75;
          armZ[0] = 0.18;
          armZ[1] = -0.18;
          lean = 0.12;
          headX = 0.12;
          if (Math.sin(t * 0.37 + ctl.walk * 3) > 0.92) arm[1] = -0.7; // mouse
          break;
        }
        case "waiting":
          lean = -0.1;
          arm[0] = arm[1] = -0.35;
          elbow[0] = elbow[1] = -0.9;
          headY = Math.sin(t * 0.5) * 0.25;
          break;
        case "blocked":
          lean = 0.05;
          headX = 0.25;
          arm[1] = -2.2;
          elbow[1] = -1.6;
          armZ[1] = -0.3;
          break;
        case "meeting":
          arm[0] = arm[1] = -0.55;
          elbow[0] = elbow[1] = -0.8;
          headY = Math.sin(t * 0.4 + ctl.walk) * 0.35;
          break;
        case "break":
          lean = ctl.seat.kind === "sofa" ? -0.18 : 0;
          arm[1] = -0.5;
          elbow[1] = -1.3;
          headY = Math.sin(t * 0.3 + ctl.walk) * 0.3;
          break;
        case "thinking":
        case "idle":
        case "offline":
          arm[0] = arm[1] = seated ? -0.4 : 0;
          elbow[0] = elbow[1] = seated ? -0.7 : -0.15;
      }
      if (f === "glance")
        headY = Math.sin((ctl.t - ctl.fidget.until) * 2.2) * 0.6;
      if (f === "think") {
        arm[1] = -1.1;
        elbow[1] = -2.25;
        armZ[1] = 0.2;
        headX = -0.08;
        headY = 0.15;
      }
      if (f === "stretch") {
        arm[0] = arm[1] = -2.9;
        elbow[0] = elbow[1] = -0.3;
        armZ[0] = 0.25;
        armZ[1] = -0.25;
        lean = -0.15;
      }
      if (f === "sip") {
        arm[1] = -1.0;
        elbow[1] = -2.2;
        headX = -0.15;
      }
      if (f === "gesture") {
        arm[0] = -1.3 + Math.sin(t * 5) * 0.2;
        elbow[0] = -0.6;
        armZ[0] = 0.35;
      }
    } else if (!walking && ctl.phase === "stand" && activity === "break") {
      arm[1] = -0.5;
      elbow[1] = -1.3;
    }
    if (ctl.phase === "stand" && ctl.plan[0]?.kind === "visit") {
      arm[1] = -1.15;
      elbow[1] = -0.35;
    }

    const k = walking ? 20 : 9;
    p.hips = damp(p.hips, hips, dt, k);
    p.lean = damp(p.lean, lean, dt, 8);
    p.headY = damp(p.headY, headY, dt, 5);
    p.headX = damp(p.headX, headX, dt, 5);
    for (let i = 0; i < 2; i++) {
      p.thigh[i] = damp(p.thigh[i] ?? 0, thigh[i] ?? 0, dt, k);
      p.knee[i] = damp(p.knee[i] ?? 0, knee[i] ?? 0, dt, k);
      p.arm[i] = damp(p.arm[i] ?? 0, arm[i] ?? 0, dt, k);
      p.armZ[i] = damp(p.armZ[i] ?? 0, armZ[i] ?? 0, dt, k);
      p.elbow[i] = damp(p.elbow[i] ?? 0, elbow[i] ?? 0, dt, k);
    }

    g.hips.position.y = p.hips;
    g.spine.rotation.x = p.lean;
    g.spine.scale.y = 1 + breathe;
    g.head.rotation.set(p.headX, p.headY, 0);
    g.legL.rotation.x = p.thigh[0] ?? 0;
    g.legR.rotation.x = p.thigh[1] ?? 0;
    g.kneeL.rotation.x = p.knee[0] ?? 0;
    g.kneeR.rotation.x = p.knee[1] ?? 0;
    g.armL.rotation.set(p.arm[0] ?? 0, 0, p.armZ[0] ?? 0);
    g.armR.rotation.set(p.arm[1] ?? 0, 0, p.armZ[1] ?? 0);
    g.elbowL.rotation.x = p.elbow[0] ?? 0;
    g.elbowR.rotation.x = p.elbow[1] ?? 0;
    g.mug.visible = (activity === "break" && !walking) || f === "sip";
    g.card.visible = ctl.carrying;
    g.ring.visible = selected || hovered;
    (g.ring.material as THREE.MeshStandardMaterial).opacity = selected
      ? 0.95
      : 0.45;
  });

  const over = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    onHover(true);
    document.body.style.cursor = "pointer";
  };
  const out = () => {
    onHover(false);
    document.body.style.cursor = "";
  };

  const hair = (
    <group>
      <mesh
        geometry={G.hairCap}
        material={m.hair}
        position={[0, 0.012, -0.01]}
        rotation-x={-0.25}
        castShadow
      />
      {looks.cut === 1 && (
        <mesh
          geometry={G.hairBack}
          material={m.hair}
          position={[0, -0.1, -0.07]}
          castShadow
        />
      )}
      {looks.cut === 2 && (
        <mesh
          geometry={G.bun}
          material={m.hair}
          position={[0, 0.14, -0.08]}
          castShadow
        />
      )}
      {looks.cut === 3 &&
        [0, 1, 2, 3, 4, 5].map((i) => {
          const a = (i / 6) * Math.PI * 2;
          return (
            <mesh
              key={i}
              geometry={G.curl}
              material={m.hair}
              position={[
                Math.sin(a) * 0.11,
                0.07 + (i % 2) * 0.03,
                Math.cos(a) * 0.09 - 0.03,
              ]}
              castShadow
            />
          );
        })}
    </group>
  );

  const limb = (side: 1 | -1) => (
    <group
      ref={set(side === 1 ? "armL" : "armR")}
      position={[side * 0.2, 0.42, 0]}
    >
      <mesh
        geometry={G.upperArm}
        material={m.shirt}
        position={[0, -0.13, 0]}
        castShadow
      />
      <group
        ref={set(side === 1 ? "elbowL" : "elbowR")}
        position={[0, -0.27, 0]}
      >
        <mesh
          geometry={G.foreArm}
          material={m.skin}
          position={[0, -0.12, 0]}
          castShadow
        />
        <mesh
          geometry={G.hand}
          material={m.skin}
          position={[0, -0.25, 0]}
          castShadow
        />
        {side === -1 && (
          <>
            <mesh
              ref={set("mug")}
              geometry={G.mug}
              material={mat(PALETTE.paper, { rough: 0.5 })}
              position={[0, -0.27, 0.05]}
              castShadow
            />
            <mesh
              ref={set("card")}
              geometry={G.card}
              material={mat(PALETTE.paper, { rough: 0.9 })}
              position={[0, -0.29, 0.06]}
              rotation-x={Math.PI / 2}
              castShadow
            />
          </>
        )}
      </group>
    </group>
  );

  const leg = (side: 1 | -1) => (
    <group
      ref={set(side === 1 ? "legL" : "legR")}
      position={[side * 0.085, 0, 0]}
    >
      <mesh
        geometry={G.thigh}
        material={m.pants}
        position={[0, -0.2, 0]}
        castShadow
      />
      <group ref={set(side === 1 ? "kneeL" : "kneeR")} position={[0, -0.4, 0]}>
        <mesh
          geometry={G.shin}
          material={m.pants}
          position={[0, -0.2, 0]}
          castShadow
        />
        <mesh
          geometry={G.shoe}
          material={m.shoe}
          position={[0, -0.42, 0.04]}
          castShadow
        />
      </group>
    </group>
  );

  return (
    <group
      ref={set("root")}
      onPointerOver={over}
      onPointerOut={out}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
    >
      <mesh
        geometry={G.shadow}
        material={m.shadow}
        rotation-x={-Math.PI / 2}
        position-y={0.012}
      />
      <mesh
        ref={set("ring")}
        geometry={G.ring}
        material={m.ring}
        rotation-x={-Math.PI / 2}
        position-y={0.015}
        visible={false}
      />
      <group ref={set("hips")} position-y={STAND_HIPS}>
        <mesh
          geometry={G.hipsBlock}
          material={m.pants}
          rotation-z={Math.PI / 2}
          position-y={0.02}
          castShadow
        />
        {leg(1)}
        {leg(-1)}
        <group ref={set("spine")}>
          <mesh
            geometry={G.torso}
            material={m.shirt}
            position={[0, 0.25, 0]}
            castShadow
          />
          <mesh geometry={G.neck} material={m.skin} position={[0, 0.5, 0]} />
          {limb(1)}
          {limb(-1)}
          <group ref={set("head")} position={[0, 0.66, 0]}>
            <mesh geometry={G.head} material={m.skin} castShadow />
            <mesh
              geometry={G.eye}
              material={m.eye}
              position={[-0.052, 0.01, 0.138]}
            />
            <mesh
              geometry={G.eye}
              material={m.eye}
              position={[0.052, 0.01, 0.138]}
            />
            {hair}
          </group>
        </group>
      </group>
    </group>
  );
}
