"use client";

/* Small low-poly pets that live by their owner's desk. They nap when the
 * owner is away or resting, and wag/look around while the owner works. */

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type * as THREE from "three";
import type { OfficeLook } from "@/data/types";
import { mat } from "./furniture-base";
import type { Seat } from "./layout";

const COAT: Record<string, [string, string]> = {
  cat: ["#e39a5a", "#c47a3c"],
  dog: ["#c9935f", "#8a5a36"],
  rabbit: ["#f2f0ec", "#d9d4cc"],
};

export function Pet({
  kind,
  home,
  awake,
}: {
  kind: OfficeLook["pet"];
  home: Seat;
  awake: boolean;
}) {
  const body = useRef<THREE.Group>(null);
  const tail = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const fish = useRef<THREE.Group>(null);
  const wing = useRef<THREE.Group>(null);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    if (tail.current)
      tail.current.rotation.y = awake
        ? Math.sin(t * 7) * 0.5
        : Math.sin(t * 0.8) * 0.08;
    if (head.current)
      head.current.rotation.y = awake ? Math.sin(t * 0.6) * 0.5 : 0;
    if (body.current)
      body.current.scale.y = 1 + Math.sin(t * (awake ? 3 : 1.4)) * 0.03;
    if (fish.current) {
      fish.current.position.x = Math.sin(t * 0.9) * 0.05;
      fish.current.rotation.y = Math.cos(t * 0.9) > 0 ? 0 : Math.PI;
    }
    if (wing.current)
      wing.current.rotation.z = awake ? Math.sin(t * 9) * 0.25 : 0;
  });

  if (kind === "none") return null;
  // on the floor, left of the chair (the right side is the way in and out)
  // the Co-Founder comes in from the other side
  const away = home.id === "desk-cofounder" ? -1 : 1;
  const dirX = Math.cos(home.face) * away;
  const dirZ = -Math.sin(home.face) * away;
  const floor = { x: home.at.x - dirX * 0.6, z: home.at.z - dirZ * 0.6 };
  // on the desk corner for the bowl and the bird
  const fx = Math.sin(home.face);
  const fz = Math.cos(home.face);
  const desk = {
    x: home.at.x + fx * 0.75 - dirX * 0.62,
    z: home.at.z + fz * 0.75 - dirZ * 0.62,
  };

  if (kind === "fish") {
    return (
      <group position={[desk.x, 0.74, desk.z]}>
        <mesh
          position={[0, 0.1, 0]}
          material={mat("#cfeefa", { opacity: 0.45, rough: 0.05 })}
        >
          <sphereGeometry args={[0.11, 20, 16]} />
        </mesh>
        <mesh
          position={[0, 0.07, 0]}
          material={mat("#7cc4e6", { opacity: 0.5, rough: 0.1 })}
        >
          <sphereGeometry
            args={[
              0.09,
              16,
              12,
              0,
              Math.PI * 2,
              Math.PI * 0.45,
              Math.PI * 0.55,
            ]}
          />
        </mesh>
        <group ref={fish} position={[0, 0.08, 0]}>
          <mesh material={mat("#f08a2a", { rough: 0.5 })}>
            <sphereGeometry args={[0.025, 10, 8]} />
          </mesh>
          <mesh
            position={[-0.03, 0, 0]}
            rotation-z={Math.PI / 2}
            material={mat("#f08a2a")}
          >
            <coneGeometry args={[0.018, 0.03, 8]} />
          </mesh>
        </group>
      </group>
    );
  }
  if (kind === "bird") {
    return (
      <group
        position={[desk.x, 0.74, desk.z]}
        rotation-y={home.face + Math.PI / 2}
      >
        <mesh position={[0, 0.07, 0]} material={mat("#8b5e3c")}>
          <cylinderGeometry args={[0.006, 0.006, 0.14, 6]} />
        </mesh>
        <mesh
          position={[0, 0.14, 0]}
          rotation-z={Math.PI / 2}
          material={mat("#8b5e3c")}
        >
          <cylinderGeometry args={[0.006, 0.006, 0.12, 6]} />
        </mesh>
        <group position={[0, 0.19, 0]}>
          <mesh material={mat("#38a6e0", { rough: 0.6 })} castShadow>
            <sphereGeometry args={[0.045, 14, 10]} />
          </mesh>
          <mesh
            position={[0, 0.045, 0.02]}
            material={mat("#38a6e0", { rough: 0.6 })}
          >
            <sphereGeometry args={[0.03, 12, 10]} />
          </mesh>
          <mesh
            position={[0, 0.045, 0.055]}
            rotation-x={Math.PI / 2}
            material={mat("#f2a93b")}
          >
            <coneGeometry args={[0.01, 0.025, 6]} />
          </mesh>
          <group ref={wing} position={[0.04, 0, 0]}>
            <mesh scale={[0.4, 1, 1.2]} material={mat("#1e86c4")}>
              <sphereGeometry args={[0.035, 10, 8]} />
            </mesh>
          </group>
        </group>
      </group>
    );
  }
  const [coat, shade] = COAT[kind] ?? ["#ccc", "#999"];
  const fur = mat(coat, { rough: 0.95 });
  const dark = mat(shade, { rough: 0.95 });
  const eye = mat("#1d1b1f", { rough: 0.3 });
  const facing = home.face + Math.PI / 2;
  return (
    <group position={[floor.x, 0, floor.z]} rotation-y={facing}>
      <mesh
        rotation-x={-Math.PI / 2}
        position-y={0.005}
        material={mat("#000", { opacity: 0.16 })}
      >
        <circleGeometry args={[0.16, 18]} />
      </mesh>
      <group ref={body} position-y={awake ? 0.11 : 0.07}>
        <mesh
          scale={awake ? [0.8, 0.85, 1.25] : [1, 0.6, 1.2]}
          material={fur}
          castShadow
        >
          <sphereGeometry args={[0.1, 16, 12]} />
        </mesh>
        <group ref={head} position={[0, awake ? 0.1 : 0.02, 0.12]}>
          <mesh material={fur} castShadow>
            <sphereGeometry args={[kind === "dog" ? 0.075 : 0.068, 16, 12]} />
          </mesh>
          {kind === "dog" && (
            <mesh position={[0, -0.02, 0.06]} material={dark}>
              <sphereGeometry args={[0.035, 10, 8]} />
            </mesh>
          )}
          {awake &&
            [-1, 1].map((s) => (
              <mesh key={s} position={[s * 0.028, 0.012, 0.062]} material={eye}>
                <sphereGeometry args={[0.009, 8, 6]} />
              </mesh>
            ))}
          {[-1, 1].map((s) =>
            kind === "cat" ? (
              <mesh key={s} position={[s * 0.04, 0.06, 0]} material={fur}>
                <coneGeometry args={[0.025, 0.05, 6]} />
              </mesh>
            ) : kind === "rabbit" ? (
              <mesh
                key={s}
                position={[s * 0.025, 0.1, -0.01]}
                scale={[0.5, 1, 0.35]}
                material={fur}
              >
                <capsuleGeometry args={[0.03, 0.09, 4, 8]} />
              </mesh>
            ) : (
              <mesh
                key={s}
                position={[s * 0.065, 0.0, 0]}
                scale={[0.4, 1, 0.8]}
                material={dark}
              >
                <sphereGeometry args={[0.04, 10, 8]} />
              </mesh>
            ),
          )}
        </group>
        <group ref={tail} position={[0, 0.02, -0.11]}>
          {kind === "rabbit" ? (
            <mesh material={mat("#ffffff")}>
              <sphereGeometry args={[0.03, 10, 8]} />
            </mesh>
          ) : (
            <mesh
              position={[0, 0.05, -0.04]}
              rotation-x={-0.8}
              material={kind === "dog" ? fur : dark}
            >
              <capsuleGeometry args={[0.016, 0.11, 4, 8]} />
            </mesh>
          )}
        </group>
      </group>
    </group>
  );
}
