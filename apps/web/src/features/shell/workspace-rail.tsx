"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { cn } from "@/shared/ui/cn";
import { PlusIcon, WrenchIcon } from "@/shared/ui/icons";
import { TILE_BG, tileVars } from "@/shared/ui/hue";
import { WorkspaceTile } from "@/shared/ui/workspace-tile";
import { AgosByline, AgosMark } from "./agos-logo";
import { RailTip } from "./nav-link";
import { useRailOrder } from "./rail-order";
import { useRailPulse } from "./rail-pulse";
import { SidebarOpenButton } from "./sidebar-shell";
import {
  type SwitcherWorkspace,
  useCurrentWorkspace,
} from "./workspace-current";
import { SectionLinks } from "./workspace-sections";
import { PANEL } from "@/shared/ui/panel";

export type { RailPulse } from "./rail-pulse";

/**
 * The slim column at the left edge: AGOS at the top, then one tile per
 * workspace (its initial on its own colour), "+" for a new one at the bottom.
 * The tile of the
 * workspace you're in is square with a bar at its edge; the others are round
 * and square up on hover. A green dot = agents working there; a red dot =
 * cards waiting for you (the same counts as that workspace's dashboard).
 *
 * With the panel folded, resting on a tile opens a preview beside it: that
 * workspace's name and its sections, so any section of any workspace is one
 * hover and one click away. With the panel open the menu is right there, so
 * tiles only show their name.
 *
 * Drag a tile up or down to change the order (rail-order.ts).
 */
export function WorkspaceRail({
  workspaces,
  order,
}: {
  workspaces: SwitcherWorkspace[];
  /** The sections' order (Settings → General), for the preview. */
  order: string[];
}) {
  const pathname = usePathname();
  const current = useCurrentWorkspace(workspaces);
  const pulse = useRailPulse();
  const inNew = pathname === "/new";
  const preview = useRailPreview();
  const arrange = useRailOrder(workspaces, preview.close);
  const shown = preview.id
    ? (workspaces.find((w) => w.id === preview.id) ?? null)
    : null;

  return (
    <nav
      aria-label="Workspaces"
      className="agos-rail flex h-full w-16 shrink-0 flex-col items-center gap-2 overflow-visible py-3"
    >
      <div
        role="img"
        aria-label="AGOS by XAG"
        className="flex flex-col items-center gap-1"
      >
        <span className="grid size-10 place-items-center">
          <AgosMark id="agos-mark-rail" className="size-7" />
        </span>
        <AgosByline className="-mt-1" />
      </div>
      <span aria-hidden className="my-0.5 h-px w-8 rounded-full bg-ink/15" />
      <SidebarOpenButton />

      <ul className="flex min-h-0 flex-1 flex-col items-center gap-2 overflow-visible py-0.5">
        {arrange.shown.map((w, index) => {
          const dragged = arrange.dragging === w.id;
          const shift = arrange.offset(index);
          const here = w.id === current?.id && !inNew;
          const p = pulse[w.id];
          const working = p?.working ?? 0;
          const waiting = p?.waiting ?? 0;
          const status = [
            working > 0 && `${working} working`,
            waiting > 0 && `${waiting} waiting for you`,
          ]
            .filter(Boolean)
            .join(" · ");
          return (
            <li
              key={w.id}
              className={cn(
                "relative touch-manipulation select-none [-webkit-touch-callout:none]",
                arrange.dragging !== null &&
                  !dragged &&
                  "transition-transform duration-200 ease-glide",
                dragged && "z-50 cursor-grabbing",
              )}
              style={
                shift ? { transform: `translateY(${shift}px)` } : undefined
              }
              onPointerDown={(event) => {
                arrange.onPointerDown(w.id, event);
              }}
              onClickCapture={arrange.onClickCapture}
              onContextMenu={(event) => {
                if (arrange.dragging !== null) event.preventDefault();
              }}
              onMouseEnter={(event) => {
                // Only with the panel folded: open, the menu is right there.
                if (arrange.dragging !== null) return;
                if (event.currentTarget.closest("[data-rail]") !== null)
                  preview.open(w.id, event.currentTarget);
                else preview.close();
              }}
              onMouseLeave={preview.leave}
            >
              <Link
                href={`/w/${w.id}`}
                aria-label={status ? `${w.name} (${status})` : w.name}
                aria-current={here ? "true" : undefined}
                aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"
                draggable={false}
                onKeyDown={(event) => {
                  arrange.onKeyDown(w.id, event);
                }}
                className="group/item relative block outline-none"
              >
                {/* The bar at the rail's edge: tall when you're in it, short on hover. */}
                <span
                  aria-hidden
                  className={cn(
                    "absolute top-1/2 -left-3 w-1 -translate-y-1/2 rounded-r-full bg-ink transition-[height,opacity] duration-200",
                    here
                      ? "h-8 opacity-100"
                      : "h-0 opacity-0 group-hover/item:h-4 group-hover/item:opacity-70 group-focus-visible/item:h-4 group-focus-visible/item:opacity-70",
                  )}
                />
                <span
                  aria-hidden
                  style={tileVars(w.id)}
                  className={cn(
                    TILE_BG,
                    "grid size-10 place-items-center overflow-hidden font-display text-15 font-semibold uppercase shadow-tile-rest transition-[border-radius,transform,box-shadow] duration-200 ease-glide group-hover/item:rounded-14 group-focus-visible/item:rounded-14 group-focus-visible/item:ring-2 group-focus-visible/item:ring-ink group-active/item:scale-95",
                    here ? "rounded-14 shadow-tile-current" : "rounded-full",
                    dragged && "scale-110 rounded-14 shadow-tile-up",
                  )}
                >
                  <WorkspaceTile workspace={w} />
                </span>
                {(working > 0 || waiting > 0) && (
                  <span
                    aria-hidden
                    className="absolute -right-0.5 -bottom-0.5 flex items-center gap-0.5 rounded-full bg-paper p-0.5"
                  >
                    {working > 0 && (
                      <span className="relative grid size-2.5 place-items-center">
                        <span className="absolute inset-0 animate-ping rounded-full bg-live/60" />
                        <span className="size-2.5 rounded-full bg-live" />
                      </span>
                    )}
                    {waiting > 0 && (
                      <span className="size-2.5 rounded-full bg-danger" />
                    )}
                  </span>
                )}
                {preview.id !== w.id && arrange.dragging === null && (
                  <RailTip always>
                    {w.name}
                    {status && (
                      <span className="block text-11 font-normal opacity-75">
                        {status}
                      </span>
                    )}
                  </RailTip>
                )}
              </Link>
            </li>
          );
        })}
      </ul>

      <span aria-hidden className="my-0.5 h-px w-8 rounded-full bg-ink/15" />
      <Link
        href="/new"
        aria-label="New workspace"
        aria-current={inNew ? "true" : undefined}
        className={cn(
          "group/item relative grid size-10 place-items-center rounded-full border border-dashed border-ink/35 text-ink-2 transition-[border-radius,color,border-color,background-color] duration-200 hover:rounded-14 hover:border-ink hover:bg-ink/6 hover:text-ink",
          inNew && "rounded-14 border-solid border-ink bg-ink/[0.07] text-ink",
        )}
      >
        <PlusIcon />
        <RailTip always>New workspace</RailTip>
      </Link>

      {shown && (
        <RailPreview
          workspace={shown}
          order={order}
          status={statusOf(pulse[shown.id])}
          anchor={preview.anchor}
          onEnter={preview.keep}
          onLeave={preview.leave}
          onNavigate={preview.close}
        />
      )}
    </nav>
  );
}

function statusOf(p: { working: number; waiting: number } | undefined) {
  if (!p) return "";
  return [
    p.working > 0 && `${p.working} working`,
    p.waiting > 0 && `${p.waiting} waiting for you`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Below this the sidebar is the small screens' menu: nothing to preview. */
const DESKTOP_MIN_WIDTH = 1024;
/** Leaving a tile for the preview crosses a small gap; the preview waits this
 * long before closing, so the pointer gets there. */
const CLOSE_GRACE_MS = 60;

/** Which tile's preview is open and where its tile sits (viewport px). */
function useRailPreview() {
  const [state, setState] = useState<{
    id: string;
    anchor: { left: number; centre: number };
  } | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const keep = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
  }, []);
  const close = useCallback(() => {
    keep();
    setState(null);
  }, [keep]);
  const leave = useCallback(() => {
    keep();
    closeTimer.current = setTimeout(() => {
      setState(null);
    }, CLOSE_GRACE_MS);
  }, [keep]);
  const open = useCallback(
    (id: string, tile: HTMLElement) => {
      if (window.innerWidth < DESKTOP_MIN_WIDTH) return;
      keep();
      const rect = tile.getBoundingClientRect();
      setState({
        id,
        anchor: { left: rect.right + 10, centre: rect.top + rect.height / 2 },
      });
    },
    [keep],
  );
  useEffect(() => {
    if (!state) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [state, close]);
  useEffect(() => keep, [keep]);
  return {
    id: state?.id ?? null,
    anchor: state?.anchor ?? { left: 0, centre: 0 },
    open,
    keep,
    leave,
    close,
  };
}

/**
 * The preview beside a tile: the workspace's name (and its settings), what its
 * agents are up to, and its sections. Pinned next to the tile, its arrow
 * pointing at it, and never past the top or bottom of the window.
 */
function RailPreview({
  workspace,
  order,
  status,
  anchor,
  onEnter,
  onLeave,
  onNavigate,
}: {
  workspace: SwitcherWorkspace;
  order: string[];
  status: string;
  anchor: { left: number; centre: number };
  onEnter: () => void;
  onLeave: () => void;
  onNavigate: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  // Centred on the tile where there is room; otherwise slid to stay in view.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const height = el.offsetHeight;
    const wanted = anchor.centre - 44;
    const top = Math.max(8, Math.min(wanted, window.innerHeight - 8 - height));
    el.style.top = `${top}px`;
    el.style.setProperty("--pointer-y", `${anchor.centre - top}px`);
  }, [anchor, workspace.id, order]);
  return (
    <div
      ref={box}
      role="dialog"
      aria-label={`${workspace.name} menu`}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={{ left: anchor.left, top: Math.max(8, anchor.centre - 44) }}
      className={`${PANEL} agos-rail-preview fixed z-50 flex w-[236px] flex-col gap-3 p-3 text-ink shadow-rail-flyout`}
    >
      <div className="flex items-center gap-2.5 pl-0.5">
        <span
          aria-hidden
          style={tileVars(workspace.id)}
          className={cn(
            TILE_BG,
            "grid size-8 shrink-0 place-items-center overflow-hidden rounded-10 font-display text-13 font-semibold uppercase",
          )}
        >
          <WorkspaceTile workspace={workspace} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-display text-15 leading-tight font-semibold tracking-tight">
            {workspace.name}
          </span>
          {status && (
            <span className="block truncate text-11 leading-tight text-ink-3">
              {status}
            </span>
          )}
        </span>
        <Link
          href={`/w/${workspace.id}/settings`}
          aria-label={`${workspace.name} settings`}
          title="Workspace settings"
          onClick={onNavigate}
          className="grid size-8 shrink-0 place-items-center rounded-lg text-ink-3 transition-colors hover:bg-ink/4.5 hover:text-ink"
        >
          <WrenchIcon />
        </Link>
      </div>
      <SectionLinks
        workspace={workspace}
        order={order}
        onNavigate={onNavigate}
      />
    </div>
  );
}
