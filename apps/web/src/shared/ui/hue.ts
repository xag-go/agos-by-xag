/** A steady hue (0–359) for a name or id: the same on every render and in
 * both themes, so a workspace or an agent keeps its colour. */
export function steadyHue(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return h % 360;
}

/** CSS variables for a tile on that hue (`--tile`, `--tile-deep`). */
export function tileVars(key: string): React.CSSProperties {
  const hue = steadyHue(key);
  return {
    "--tile": `oklch(0.58 0.13 ${hue})`,
    "--tile-deep": `oklch(0.48 0.13 ${hue})`,
  } as React.CSSProperties;
}

/** The tile's background, from those variables. */
export const TILE_BG =
  "bg-[linear-gradient(145deg,var(--tile),var(--tile-deep))] text-white";
