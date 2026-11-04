"use client";

/* Monitor screens: one shared material per state, animated in place. */

import * as THREE from "three";
import type { DeskState } from "./workstation";

function canvas(
  w: number,
  h: number,
  draw: (g: CanvasRenderingContext2D) => void,
) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const g = c.getContext("2d");
  if (g) draw(g);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function codeTexture() {
  const t = canvas(128, 256, (g) => {
    g.fillStyle = "#101820";
    g.fillRect(0, 0, 128, 256);
    const colours = [
      "#7dd3fc",
      "#a7f3d0",
      "#fde68a",
      "#fca5a5",
      "#c4b5fd",
      "#e2e8f0",
    ];
    for (let i = 0; i < 32; i++) {
      const indent = (i * 7) % 4;
      let x = 8 + indent * 8;
      const words = 1 + ((i * 5) % 4);
      for (let k = 0; k < words; k++) {
        const len = 10 + ((i * 13 + k * 7) % 26);
        g.fillStyle = colours[(i + k) % colours.length] ?? "#fff";
        g.fillRect(x, 6 + i * 8, len, 3);
        x += len + 5;
      }
    }
  });
  t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(1, 0.4);
  return t;
}

function signTexture(bg: string, glyph: string) {
  return canvas(128, 72, (g) => {
    g.fillStyle = bg;
    g.fillRect(0, 0, 128, 72);
    g.fillStyle = "#ffffff";
    g.font = "bold 46px system-ui, sans-serif";
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(glyph, 64, 38);
  });
}

function saverTexture() {
  return canvas(128, 72, (g) => {
    const grd = g.createLinearGradient(0, 0, 128, 72);
    grd.addColorStop(0, "#1f2b2a");
    grd.addColorStop(1, "#2f3b4a");
    g.fillStyle = grd;
    g.fillRect(0, 0, 128, 72);
    g.fillStyle = "rgba(156,181,154,.9)";
    g.beginPath();
    g.arc(64, 36, 10, 0, Math.PI * 2);
    g.fill();
  });
}

function thinkTexture() {
  return canvas(128, 72, (g) => {
    g.fillStyle = "#14202a";
    g.fillRect(0, 0, 128, 72);
    g.fillStyle = "#e2e8f0";
    g.fillRect(14, 14, 70, 5);
    g.fillStyle = "#64748b";
    for (let i = 0; i < 4; i++)
      g.fillRect(14, 28 + i * 9, 40 + ((i * 17) % 50), 3);
    g.fillStyle = "#9cb59a";
    g.fillRect(94, 14, 22, 44);
  });
}

function wallTexture() {
  return canvas(256, 136, (g) => {
    g.fillStyle = "#16201f";
    g.fillRect(0, 0, 256, 136);
    g.fillStyle = "#9cb59a";
    g.font = "600 15px system-ui, sans-serif";
    g.fillText("Weekly review", 16, 28);
    const bars = [40, 62, 48, 80, 70, 96];
    bars.forEach((h, i) => {
      g.fillStyle = i === bars.length - 1 ? "#c9a45c" : "#5f7f74";
      g.fillRect(24 + i * 34, 120 - h, 22, h);
    });
  });
}

export type Screens = {
  byState: Record<DeskState, THREE.MeshStandardMaterial>;
  wall: THREE.MeshStandardMaterial;
  code: THREE.CanvasTexture;
  dispose: () => void;
};

export function makeScreens(): Screens {
  const glow = (map: THREE.Texture, intensity: number) =>
    new THREE.MeshStandardMaterial({
      color: "#000000",
      map,
      emissive: "#ffffff",
      emissiveMap: map,
      emissiveIntensity: intensity,
      roughness: 0.35,
      toneMapped: false,
    });
  const code = codeTexture();
  const textures = [
    code,
    signTexture("#d6453b", "!"),
    signTexture("#d9952b", "?"),
    saverTexture(),
    thinkTexture(),
    wallTexture(),
  ];
  const [, alert, ask, saver, think, wall] = textures as [
    THREE.CanvasTexture,
    THREE.CanvasTexture,
    THREE.CanvasTexture,
    THREE.CanvasTexture,
    THREE.CanvasTexture,
    THREE.CanvasTexture,
  ];
  const byState: Record<DeskState, THREE.MeshStandardMaterial> = {
    off: new THREE.MeshStandardMaterial({
      color: "#121417",
      roughness: 0.25,
      metalness: 0.2,
    }),
    code: glow(code, 0.9),
    alert: glow(alert, 0.9),
    ask: glow(ask, 0.9),
    saver: glow(saver, 0.6),
    think: glow(think, 0.8),
  };
  const wallMat = glow(wall, 0.7);
  return {
    byState,
    wall: wallMat,
    code,
    dispose: () => {
      for (const t of textures) t.dispose();
      for (const m of Object.values(byState)) m.dispose();
      wallMat.dispose();
    },
  };
}

/** Per-frame: scroll the code, blink the alerts. */
export function tickScreens(s: Screens, t: number) {
  s.code.offset.y = -((t * 0.08) % 1);
  const blink = Math.sin(t * 4) > -0.2 ? 0.95 : 0.35;
  s.byState.alert.emissiveIntensity = blink;
  s.byState.ask.emissiveIntensity = 0.55 + 0.25 * Math.sin(t * 2);
}
