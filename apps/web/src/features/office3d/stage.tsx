"use client";

/* The 3D stage: renderer, orthographic camera with bounded pan/zoom, the two
 * lighting presets, and the static room. Characters are passed as children. */

import { MapControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import {
  forwardRef,
  type ComponentRef,
  type ReactNode,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
} from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { Floor, Walls } from "./furniture-base";
import { floorSize } from "./layout";
import { OfficeRoom } from "./rooms";
import { type StationInfo } from "./workstation";
import { makeScreens, type Screens, tickScreens } from "./screens";

type MapControlsImpl = ComponentRef<typeof MapControls>;

export type CameraApi = { reset: () => void; zoomBy: (k: number) => void };

const VIEW_DIR = new THREE.Vector3(1, 1.15, 1.3).normalize();

function Environment({ evening }: { evening: boolean }) {
  const { gl, scene } = useThree();
  useEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl);
    const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = env;
    scene.environmentIntensity = evening ? 0.12 : 0.35;
    return () => {
      scene.environment = null;
      env.dispose();
      pmrem.dispose();
    };
  }, [gl, scene, evening]);
  return null;
}

/** Fits the whole floor in view; pan and zoom stay inside sensible limits. */
const Rig = forwardRef<CameraApi, { w: number; d: number }>(function Rig(
  { w, d },
  ref,
) {
  const { camera, size, invalidate } = useThree();
  const controls = useRef<MapControlsImpl>(null);
  const centre = useMemo(() => new THREE.Vector3(w / 2, 0.6, d / 2), [w, d]);
  const fit = useMemo(() => {
    // project the floor's corners (and wall tops) onto the view plane
    const cam = new THREE.OrthographicCamera();
    cam.position.copy(centre).addScaledVector(VIEW_DIR, 40);
    cam.lookAt(centre);
    cam.updateMatrixWorld();
    const inv = cam.matrixWorldInverse;
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const [x, y, z] of [
      [0, 0, 0],
      [w, 0, 0],
      [0, 0, d],
      [w, 0, d],
      [0, 3, 0],
      [w, 3, 0],
      [0, 3, d],
    ] as const) {
      const p = new THREE.Vector3(x, y, z).applyMatrix4(inv);
      minX = Math.min(minX, p.x);
      maxX = Math.max(maxX, p.x);
      minY = Math.min(minY, p.y);
      maxY = Math.max(maxY, p.y);
    }
    return (
      Math.min(size.width / (maxX - minX), size.height / (maxY - minY)) * 0.96
    );
  }, [centre, w, d, size.width, size.height]);

  const target = useRef({ zoom: fit, centre: centre.clone(), moving: false });

  const place = (zoom: number, c: THREE.Vector3) => {
    target.current = { zoom, centre: c.clone(), moving: true };
    invalidate();
  };

  useEffect(() => {
    camera.position.copy(centre).addScaledVector(VIEW_DIR, 40);
    camera.lookAt(centre);
    (camera as THREE.OrthographicCamera).zoom = fit;
    camera.near = 0.1;
    camera.far = 200;
    camera.updateProjectionMatrix();
    controls.current?.target.copy(centre);
    controls.current?.update();
    target.current = { zoom: fit, centre: centre.clone(), moving: false };
  }, [camera, centre, fit]);

  useImperativeHandle(ref, () => ({
    reset: () => {
      place(fit, centre);
    },
    zoomBy: (k: number) => {
      const c = controls.current?.target ?? centre;
      place(
        THREE.MathUtils.clamp(
          (camera as THREE.OrthographicCamera).zoom * k,
          fit * 0.85,
          fit * 3.2,
        ),
        c,
      );
    },
  }));

  useFrame((_, dt) => {
    const cam = camera as THREE.OrthographicCamera;
    const ctl = controls.current;
    if (!ctl) return;
    const t = target.current;
    if (t.moving) {
      const k = 1 - Math.exp(-dt * 9);
      cam.zoom += (t.zoom - cam.zoom) * k;
      const shift = t.centre.clone().sub(ctl.target).multiplyScalar(k);
      ctl.target.add(shift);
      cam.position.add(shift);
      cam.updateProjectionMatrix();
      if (Math.abs(t.zoom - cam.zoom) < 0.01 && shift.length() < 0.001)
        t.moving = false;
    }
    // keep the office in view
    const tx = THREE.MathUtils.clamp(ctl.target.x, 0, w);
    const tz = THREE.MathUtils.clamp(ctl.target.z, 0, d);
    if (
      tx !== ctl.target.x ||
      tz !== ctl.target.z ||
      ctl.target.y !== centre.y
    ) {
      const fix = new THREE.Vector3(
        tx - ctl.target.x,
        centre.y - ctl.target.y,
        tz - ctl.target.z,
      );
      ctl.target.add(fix);
      cam.position.add(fix);
    }
  });

  return (
    <MapControls
      ref={controls}
      makeDefault
      enableRotate={false}
      enableDamping
      dampingFactor={0.12}
      minZoom={fit * 0.85}
      maxZoom={fit * 3.2}
      screenSpacePanning
      zoomToCursor
    />
  );
});

function Lights({ evening, w, d }: { evening: boolean; w: number; d: number }) {
  const sun = useRef<THREE.DirectionalLight>(null);
  useEffect(() => {
    const s = sun.current;
    if (!s) return;
    s.target.position.set(w / 2, 0, d / 2);
    s.target.updateMatrixWorld();
    const cam = s.shadow.camera;
    const half = Math.max(w, d) * 0.75;
    cam.left = -half;
    cam.right = half;
    cam.top = half;
    cam.bottom = -half;
    cam.near = 1;
    cam.far = 80;
    cam.updateProjectionMatrix();
    s.shadow.needsUpdate = true;
  }, [w, d, evening]);
  return (
    <>
      <hemisphereLight
        args={
          evening ? ["#8fa3c8", "#3b2a20", 0.55] : ["#fff4e2", "#b08a66", 1.25]
        }
      />
      <directionalLight
        ref={sun}
        position={
          evening ? [w / 2 + 14, 22, d / 2 + 6] : [w / 2 - 6, 20, d / 2 + 14]
        }
        intensity={evening ? 0.35 : 2.1}
        color={evening ? "#9fb3e0" : "#fff1d6"}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0004}
        shadow-normalBias={0.03}
        shadow-radius={4}
      />
      {evening && (
        <>
          {[
            [6.6, 1.7, 2.0],
            [13.6, 1.7, 2.0],
            [10, 2.4, 4.2],
            [2.4, 1.3, 2.4],
            [19.3, 1.5, d - 5.7],
            [17.3, 2.3, 3.0],
            [17.5, 2.0, d - 2.0],
          ].map(([x, y, z]) => (
            <pointLight
              key={`${String(x)}-${String(z)}`}
              position={[x ?? 0, y ?? 2, z ?? 0]}
              intensity={4.2}
              distance={6}
              decay={1.6}
              color="#ffc98a"
            />
          ))}
        </>
      )}
    </>
  );
}

function Ticker({ screens }: { screens: Screens }) {
  useFrame(({ clock }) => {
    tickScreens(screens, clock.elapsedTime);
  });
  return null;
}

export type StageProps = {
  members: number;
  stations: StationInfo[];
  done: number;
  evening: boolean;
  paused: boolean;
  children?: ReactNode;
  onMissed?: () => void;
};

export const Stage = forwardRef<CameraApi, StageProps>(function Stage(
  { members, stations, done, evening, paused, children, onMissed },
  ref,
) {
  const f = floorSize(members);
  const screens = useMemo(() => makeScreens(), []);
  useEffect(
    () => () => {
      screens.dispose();
    },
    [screens],
  );
  return (
    <Canvas
      orthographic
      shadows="soft"
      dpr={[1, 1.75]}
      frameloop={paused ? "never" : "always"}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      onPointerMissed={onMissed}
      camera={{ zoom: 40, near: 0.1, far: 200, position: [30, 30, 30] }}
    >
      <color attach="background" args={[evening ? "#141518" : "#1b1c1f"]} />
      <Environment evening={evening} />
      <Lights evening={evening} w={f.w} d={f.d} />
      <Rig ref={ref} w={f.w} d={f.d} />
      <Ticker screens={screens} />
      <Floor w={f.w} d={f.d} />
      <Walls w={f.w} d={f.d} evening={evening} />
      <OfficeRoom
        members={members}
        stations={stations}
        screens={stations.map((s) => screens.byState[s.screen])}
        wallScreen={screens.wall}
        done={done}
        evening={evening}
      />
      {children}
    </Canvas>
  );
});
