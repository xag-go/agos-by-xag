"use client";

/* The 3D studio (stage + crew) in one module that office3d.tsx loads on its own
 * (next/dynamic). three.js and react-three-fiber (~860 KB raw) are then fetched
 * and parsed only for the scene, so the Office's header, feed and inspector
 * work before the WebGL code arrives. */

import type { ComponentProps } from "react";
import { Crew } from "./crew";
import { Stage } from "./stage";

export function Scene({
  crew,
  ...stage
}: Omit<ComponentProps<typeof Stage>, "children"> & {
  crew: ComponentProps<typeof Crew>;
}) {
  return (
    <Stage {...stage}>
      <Crew {...crew} />
    </Stage>
  );
}
