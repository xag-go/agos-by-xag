"use client";

import type * as THREE from "three";
import { Plant } from "./furniture";
import { COFOUNDER, plantSpots, station } from "./layout";
import { Workstation, type StationInfo } from "./workstation";
import {
  CofounderCorner,
  FloorLamp,
  Lounge,
  MeetingRoom,
  OutputCorner,
} from "./room-areas";

/** Everything that doesn't walk. */
export function OfficeRoom({
  members,
  stations,
  screens,
  wallScreen,
  done,
  evening,
}: {
  members: number;
  stations: StationInfo[]; // [cofounder, ...members]
  screens: THREE.Material[];
  wallScreen: THREE.Material;
  done: number;
  evening: boolean;
}) {
  return (
    <group>
      <CofounderCorner />
      {stations.map((info, i) => {
        const st = i === 0 ? COFOUNDER : station(i - 1);
        const screen = screens[i] ?? wallScreen;
        return (
          <Workstation
            key={info.key}
            st={st}
            info={info}
            screen={screen}
            evening={evening}
          />
        );
      })}
      {[
        [6.6, 2.0],
        [13.6, 2.0],
      ].map(([x, z]) => (
        <FloorLamp key={x} x={x ?? 0} z={z ?? 0} lit={evening} />
      ))}
      <MeetingRoom screen={wallScreen} members={members} />
      <Lounge members={members} evening={evening} />
      <OutputCorner done={done} />
      {plantSpots(members).map((p) => (
        <Plant
          key={`${String(p.x)}-${String(p.z)}`}
          x={p.x}
          z={p.z}
          size={1.15}
        />
      ))}
    </group>
  );
}
