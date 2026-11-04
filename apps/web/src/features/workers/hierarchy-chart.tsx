"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { Founder, Scorecard } from "@/data/types";
import { cn } from "@/shared/ui/cn";
import { founderInitial } from "./founder-box";
import { KitChip, ReadinessChip } from "./kit-chips";
import { ShiftChip } from "./shift-chip";
import { phoneFit, rootXOf, useChartTouch, type Drag } from "./chart-touch";
import { ScoreChip } from "./scorecard";
import {
  BOX_H,
  BOX_W,
  GAP_Y,
  MAX_ZOOM,
  MIN_ZOOM,
  PAD,
  STATUS_WORDS,
  keyOf,
  type Node,
  type Placed,
  type Status,
} from "./hierarchy-layout";

/**
 * The chart's canvas: drag to pan, wheel (or the buttons) to zoom, Fit to see
 * the whole team. Starts fitted.
 */
export function Chart({
  placed,
  width,
  height,
  workspaceName,
  cards,
  onPick,
  founder = null,
  founderAt = null,
  onPickFounder,
}: {
  placed: Placed[];
  width: number;
  height: number;
  workspaceName: string;
  cards: Map<string, Scorecard>;
  onPick: (node: Node) => void;
  founder?: Founder | null;
  founderAt?: { x: number; y: number } | null;
  onPickFounder?: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<Drag | null>(null);
  const moved = useRef(false);
  // Fingers on the canvas (touch): one pans, two pinch-zoom the chart.
  const touch = useChartTouch(drag, moved, view, setView);
  const rootX = rootXOf(placed);

  const fit = useCallback(() => {
    const el = box.current;
    if (!el) return;
    const cw = el.clientWidth;
    const ch = el.clientHeight;
    const k = Math.min(1, (cw - PAD * 2) / width, (ch - PAD * 2) / height);
    const phone = phoneFit(rootX, width, cw, k);
    if (phone) {
      setView(phone);
      return;
    }
    setView({
      k,
      x: (cw - width * k) / 2,
      y: Math.max(PAD, (ch - height * k) / 2),
    });
  }, [rootX, width, height]);

  useLayoutEffect(fit, [fit]);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => {
      ro.disconnect();
    };
  }, [fit]);

  const zoomBy = useCallback((factor: number, cx?: number, cy?: number) => {
    setView((v) => {
      const el = box.current;
      const px = cx ?? (el?.clientWidth ?? 0) / 2;
      const py = cy ?? (el?.clientHeight ?? 0) / 2;
      const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.k * factor));
      const r = k / v.k;
      return { k, x: px - (px - v.x) * r, y: py - (py - v.y) * r };
    });
  }, []);

  // A wheel listener React can't make non-passive; the page must not scroll.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const r = el.getBoundingClientRect();
      zoomBy(
        Math.exp(-event.deltaY * 0.0015),
        event.clientX - r.left,
        event.clientY - r.top,
      );
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", onWheel);
    };
  }, [zoomBy]);

  const byNode = new Map(placed.map((p) => [p.node, p]));

  return (
    <div
      ref={box}
      className={cn(
        "org-chart relative min-h-0 flex-1 touch-none overflow-hidden rounded-2xl border border-line bg-paper select-none",
        "cursor-grab active:cursor-grabbing",
      )}
      onPointerDownCapture={touch.down}
      onPointerDown={touch.mouseDown}
      onPointerMove={touch.move}
      onPointerUp={touch.up}
      onPointerCancel={touch.cancel}
    >
      <div
        className="absolute top-0 left-0 origin-top-left"
        style={{
          width,
          height,
          transform: `translate(${String(view.x)}px, ${String(view.y)}px) scale(${String(view.k)})`,
        }}
      >
        <svg
          aria-hidden
          className="pointer-events-none absolute inset-0 overflow-visible"
          width={width}
          height={height}
        >
          {placed.map(({ node, x, y }) => {
            if (node.children.length === 0) return null;
            const px = x + BOX_W / 2;
            const top = y + BOX_H;
            const mid = top + GAP_Y / 2;
            const kids = node.children
              .map((c) => byNode.get(c))
              .filter((p): p is Placed => p !== undefined);
            const xs = kids.map((p) => p.x + BOX_W / 2);
            const d = [
              `M${String(px)} ${String(top)}V${String(mid)}`,
              xs.length > 1
                ? `M${String(Math.min(...xs))} ${String(mid)}H${String(Math.max(...xs))}`
                : "",
              ...xs.map(
                (cx) =>
                  `M${String(cx)} ${String(mid)}V${String(mid + GAP_Y / 2)}`,
              ),
            ].join("");
            return (
              <path
                key={keyOf(node)}
                d={d}
                fill="none"
                stroke="var(--line-strong)"
                strokeWidth={1.5}
              />
            );
          })}
          {founderAt && placed[0] && (
            <path
              d={`M${String(founderAt.x + BOX_W)} ${String(founderAt.y + BOX_H / 2)}H${String(placed[0].x)}`}
              fill="none"
              stroke="var(--line-strong)"
              strokeWidth={1.5}
              strokeDasharray="4 4"
            />
          )}
        </svg>
        {founder && founderAt && (
          <button
            type="button"
            onPointerDown={(event) => {
              event.stopPropagation();
            }}
            onClick={() => {
              if (!moved.current) onPickFounder?.();
            }}
            aria-label={`${founder.name || "You"}, ${founder.title}: ${String(founder.openCount)} open task${founder.openCount === 1 ? "" : "s"}`}
            data-founder
            style={{
              left: founderAt.x,
              top: founderAt.y,
              width: BOX_W,
              height: BOX_H,
            }}
            className="absolute flex cursor-pointer items-center gap-3.5 rounded-2xl border border-ink/40 bg-panel px-4 text-left transition-[border-color,box-shadow,transform] hover:-translate-y-px hover:border-line-strong hover:shadow-chart-node active:scale-[0.96]"
          >
            <span className="grid size-11 shrink-0 place-items-center rounded-full bg-ink font-display text-base font-semibold text-paper">
              {founderInitial(founder)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-display text-15 leading-tight font-semibold text-ink">
                {founder.name || "You"}
              </span>
              <span className="mt-0.5 block truncate text-xs leading-snug text-ink-2">
                {founder.title}
              </span>
              <span
                className={cn(
                  "mt-1 inline-block rounded px-1.5 py-px text-11 font-medium tabular-nums",
                  founder.openCount > 0
                    ? "bg-attention text-attention-ink"
                    : "bg-sunken text-ink-3",
                )}
              >
                {founder.openCount > 0
                  ? `${String(founder.openCount)} open task${founder.openCount === 1 ? "" : "s"}`
                  : "Nothing waits on you"}
              </span>
            </span>
          </button>
        )}
        {placed.map(({ node, x, y }) => (
          <button
            key={keyOf(node)}
            type="button"
            onPointerDown={(event) => {
              event.stopPropagation();
            }}
            onClick={() => {
              if (!moved.current) onPick(node);
            }}
            aria-label={`${node.worker.title}: ${STATUS_WORDS[node.status]}`}
            data-status={node.status}
            style={{ left: x, top: y, width: BOX_W, height: BOX_H }}
            className={cn(
              "absolute flex cursor-pointer items-center gap-3.5 rounded-2xl border bg-panel px-4 text-left transition-[border-color,box-shadow,transform] hover:-translate-y-px hover:border-line-strong hover:shadow-chart-node",
              node.lead ? "border-ink/40" : "border-line",
              node.status === "pending" &&
                "border-dashed border-attention-ink/50 bg-panel/70 text-ink-2",
              node.status === "paused" && "opacity-70",
            )}
          >
            <span className="relative grid size-11 shrink-0 place-items-center rounded-full bg-sunken font-display text-base font-semibold text-ink">
              {node.worker.title.trim().charAt(0).toUpperCase()}
              <StatusDot status={node.status} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-display text-15 leading-tight font-semibold text-ink">
                {node.worker.title}
              </span>
              <span className="mt-0.5 block truncate text-xs leading-snug text-ink-2">
                {node.worker.name ? `@${node.worker.name}` : workspaceName}
                {node.status !== "active" && (
                  <span
                    className={cn(
                      "ml-1.5 rounded px-1 py-px text-10 font-medium",
                      node.status === "pending" &&
                        "bg-attention text-attention-ink",
                      node.status === "working" && "bg-live/15 text-live",
                      node.status === "paused" && "bg-sunken text-ink-3",
                    )}
                  >
                    {STATUS_WORDS[node.status]}
                  </span>
                )}
                {/* One chip fits the box: a kit missing a part says so first. */}
                {node.worker.readiness &&
                  (!node.worker.kit || node.worker.kit === "whole") && (
                    <ReadinessChip
                      state={node.worker.readiness}
                      className="ml-1.5 px-1 py-px text-10"
                    />
                  )}
                {node.status !== "pending" && (
                  <KitChip
                    state={node.worker.kit}
                    className="ml-1.5 px-1 py-px text-10"
                  />
                )}
                {node.worker.shift && node.status !== "pending" && (
                  <ShiftChip
                    state={node.worker.shift}
                    compact
                    className="ml-1.5 px-1 text-10"
                  />
                )}
              </span>
              {node.model && (
                <span className="mt-0.5 block truncate font-mono text-11 text-ink-3">
                  {node.model}
                </span>
              )}
              {node.status !== "pending" && (
                <ScoreChip card={cards.get(node.worker.name || "cofounder")} />
              )}
            </span>
            <ChainBadge node={node} />
          </button>
        ))}
      </div>

      <div className="absolute top-3 right-3 flex flex-col gap-1">
        <button
          type="button"
          aria-label="Zoom in"
          onPointerDown={(e) => {
            e.stopPropagation();
          }}
          onClick={() => {
            zoomBy(1.25);
          }}
          className="grid size-9 place-items-center rounded-lg border border-line bg-panel text-lg leading-none text-ink hover:bg-sunken max-md:size-11"
        >
          +
        </button>
        <button
          type="button"
          aria-label="Zoom out"
          onPointerDown={(e) => {
            e.stopPropagation();
          }}
          onClick={() => {
            zoomBy(0.8);
          }}
          className="grid size-9 place-items-center rounded-lg border border-line bg-panel text-lg leading-none text-ink hover:bg-sunken max-md:size-11"
        >
          −
        </button>
        <button
          type="button"
          onPointerDown={(e) => {
            e.stopPropagation();
          }}
          onClick={fit}
          className="grid h-9 place-items-center rounded-lg border border-line bg-panel px-2 text-xs font-semibold text-ink hover:bg-sunken max-md:h-11 max-md:min-w-11"
        >
          Fit
        </button>
      </div>
    </div>
  );
}

/** Chain health on a box: the team this lead stalls, or the lead that stalls
 * this member. */
function ChainBadge({ node }: { node: Node }) {
  const stalls = node.org?.stalls.length ?? 0;
  const words =
    stalls > 0
      ? `Stalls ${String(stalls)}`
      : node.org?.stalled
        ? "Stalled"
        : "";
  if (!words) return null;
  const why =
    stalls > 0
      ? `Its team can't move: ${(node.org?.stalls ?? []).map((m) => `@${m}`).join(", ")}`
      : (node.org?.stalled?.words ?? "");
  return (
    <span
      title={why}
      className="absolute -top-2 right-3 rounded-md bg-attention px-1.5 py-px text-10 font-semibold text-attention-ink"
    >
      {words}
    </span>
  );
}

function StatusDot({ status }: { status: Status }) {
  return (
    <span
      aria-hidden
      className={cn(
        "absolute -right-0.5 -bottom-0.5 size-3 rounded-full ring-3 ring-panel",
        status === "working" && "bg-live",
        status === "active" && "bg-ink-3/60",
        status === "paused" && "bg-ink-3/30",
        status === "pending" &&
          "border border-dashed border-attention-ink bg-attention",
      )}
    />
  );
}
