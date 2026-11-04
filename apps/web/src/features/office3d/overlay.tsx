"use client";

/* Crisp HTML over the 3D scene: status markers over heads, and the name +
 * state of whoever is hovered or selected. Positions come from the ScreenBus. */

import { useEffect, useRef } from "react";
import type { ScreenBus } from "./bus";
import { LABEL } from "./labels";
import type { Activity } from "./controller";

export type OverlayAgent = { key: string; title: string; activity: Activity };

export function Overlay({
  agents,
  bus,
  selected,
  hovered,
}: {
  agents: OverlayAgent[];
  bus: ScreenBus;
  selected: string | null;
  hovered: string | null;
}) {
  const els = useRef(new Map<string, HTMLDivElement>());
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      for (const [key, el] of els.current) {
        const s = bus.spots.get(key);
        if (!s || !s.visible) {
          el.style.visibility = "hidden";
          continue;
        }
        el.style.visibility = "visible";
        el.style.transform = `translate(${s.x.toFixed(1)}px, ${s.y.toFixed(1)}px) translate(-50%, -100%)`;
        el.classList.toggle("is-thinking", s.thinking);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
    };
  }, [bus]);

  return (
    <div
      className="pointer-events-none absolute inset-0 overflow-hidden"
      aria-hidden
    >
      {agents.map((a) => {
        const mark =
          a.activity === "waiting"
            ? "!"
            : a.activity === "blocked"
              ? "?"
              : null;
        const show = selected === a.key || hovered === a.key;
        return (
          <div
            key={a.key}
            ref={(el) => {
              if (el) els.current.set(a.key, el);
              else els.current.delete(a.key);
            }}
            className="office3d-marker absolute top-0 left-0"
            style={{ visibility: "hidden" }}
          >
            {mark ? (
              <span className={`office3d-mark is-${a.activity}`}>{mark}</span>
            ) : (
              <span className="office3d-mark is-thought">…</span>
            )}
            {show && (
              <span className="office3d-label">
                <strong>{a.title}</strong>
                <span>{LABEL[a.activity]}</span>
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
