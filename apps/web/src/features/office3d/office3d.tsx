"use client";

import dynamic from "next/dynamic";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import type { KanbanCard, OfficeLook, Team } from "@/data/types";
import { LiveRefresh } from "@/shared/live-refresh";
import {
  doneToday,
  type Move,
  moves,
  officeAgents,
  type OpenStatuses,
  snapshot,
} from "@/features/office/model";
import { cn } from "@/shared/ui/cn";
import { ScreenBus } from "./bus";
import { type Activity, activityOf } from "./controller";
import {
  DEMO_STEP_MS,
  demoAgents,
  demoEvents,
  demoMoves,
  type FeedEvent,
} from "./demo";
import { LABEL } from "./labels";
import { Overlay } from "./overlay";
import type { DeskState } from "./workstation";
import type { CameraApi } from "./stage";
import { Inspector, NoWebGL, SceneLoading } from "./office-hud";
import {
  ACCENTS,
  DOT,
  ago,
  liveFeed,
  noSubscribe,
  useHidden,
  usePrefersReducedMotion,
  webglAvailable,
} from "./office-hooks";

// The whole 3D part (three.js + react-three-fiber) loads on its own, after the
// page: nothing else on the page imports it.
const Scene = dynamic(() => import("./scene").then((m) => m.Scene), {
  ssr: false,
  loading: () => <SceneLoading />,
});

export function Office3D({
  workspaceId,
  workspaceName,
  team,
  cards,
  open,
  looks,
  connected,
  stamp,
}: {
  workspaceId: string;
  workspaceName: string;
  team: Team;
  cards: KanbanCard[];
  open: string[];
  looks: Record<string, OfficeLook>;
  connected: boolean;
  /** The fingerprint of the data above; the live refresh re-renders the page
   * only when the Office's stamp route answers a different one. */
  stamp: string;
}) {
  // The page used to re-render every 2 s from the server; the times shown
  // ("5m", done today, the feed) still move every 2 s, from here.
  const [, setClock] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") setClock((n) => n + 1);
    }, 2000);
    return () => {
      clearInterval(timer);
    };
  }, []);
  const openSet: OpenStatuses = useMemo(() => new Set(open), [open]);
  const real = useMemo(
    () => officeAgents(team, cards, looks, openSet),
    [team, cards, looks, openSet],
  );
  const [demo, setDemo] = useState(false);
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (!demo) return;
    const timer = setInterval(() => {
      setStep((s) => s + 1);
    }, DEMO_STEP_MS);
    return () => {
      clearInterval(timer);
    };
  }, [demo]);
  const agents = useMemo(
    () => (demo ? demoAgents(real, step) : real),
    [demo, real, step],
  );

  // live events → moves (Co-Founder hand-offs, finished work)
  const snap = useMemo(() => snapshot(cards), [cards]);
  const [seen, setSeen] = useState(snap);
  const [liveMoved, setLiveMoved] = useState<Move[]>([]);
  if (seen !== snap) {
    setSeen(snap);
    setLiveMoved(moves(seen, snap, openSet));
  }
  const moved = useMemo(
    () => (demo ? demoMoves(real, step) : liveMoved),
    [demo, real, step, liveMoved],
  );

  const names = useMemo(
    () => new Map(real.map((a) => [a.key, a.title])),
    [real],
  );
  const [demoFeed, setDemoFeed] = useState<FeedEvent[]>([]);
  const [lastStep, setLastStep] = useState(-1);
  if (demo && step !== lastStep) {
    setLastStep(step);
    setDemoFeed((f) => [...demoEvents(real, step), ...f].slice(0, 30));
  }
  const feed = demo ? demoFeed : liveFeed(cards, names);

  const offline = !demo && !connected;
  const reduceOS = usePrefersReducedMotion();
  const [motion, setMotion] = useState<"auto" | "full" | "reduced">("auto");
  const still = motion === "reduced" || (motion === "auto" && reduceOS);
  const hidden = useHidden();
  const [evening, setEvening] = useState(() => {
    const h = new Date().getHours();
    return h >= 19 || h < 6;
  });
  const gl = useSyncExternalStore(noSubscribe, webglAvailable, () => null);

  const cam = useRef<CameraApi>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [feedOpen, setFeedOpen] = useState(true);
  const [bus] = useState(() => new ScreenBus());
  const chosen = agents.find((a) => a.key === selected) ?? null;
  const base = `/w/${encodeURIComponent(workspaceId)}`;
  const accents = agents.map((a) => ACCENTS[a.look.colour]);
  const activities = agents.map((a) => activityOf(a, offline));
  const counts = activities.reduce<Record<string, number>>((m, a) => {
    m[a] = (m[a] ?? 0) + 1;
    return m;
  }, {});
  const screen = (i: number): DeskState => {
    const a = agents[i];
    if (!a || offline || a.place !== "desk") return "off";
    if (a.status === "working") return "code";
    if (a.status === "waiting") return "alert";
    if (a.status === "blocked") return "ask";
    return "saver";
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <div className="office3d flex flex-col overflow-hidden rounded-2xl">
      {!demo && (
        <LiveRefresh
          active
          everyMs={2000}
          stampUrl={`/api/w/${encodeURIComponent(workspaceId)}/office/stamp`}
          stamp={stamp}
        />
      )}
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-white/[0.07] px-4 py-3">
        <div className="min-w-0">
          <p className="text-10 font-semibold tracking-caps-wide text-hud-stone uppercase">
            Office
          </p>
          <h2 className="truncate font-display text-lg font-semibold">
            {workspaceName}
          </h2>
        </div>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
            demo
              ? "border-hud-brass/50 bg-hud-brass/10 text-hud-gold"
              : connected
                ? "border-white/10 text-hud-sand"
                : "border-hud-alarm/40 bg-hud-alarm/10 text-hud-alarm-soft",
          )}
          role="status"
        >
          <span
            className="size-1.5 rounded-full"
            style={{
              background: demo ? "#c9a45c" : connected ? "#5fbf7f" : "#e0574c",
            }}
          />
          {demo
            ? "Demo Mode · sample activity"
            : connected
              ? "Live · Hermes"
              : "Disconnected · last known state"}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-3 text-xs text-hud-sand-dim">
          {(
            ["working", "waiting", "blocked", "meeting", "break"] as Activity[]
          ).map((k) =>
            counts[k] ? (
              <span key={k} className="inline-flex items-center gap-1.5">
                <span
                  className="size-1.5 rounded-full"
                  style={{ background: DOT[k] }}
                />
                {counts[k]} {LABEL[k].toLowerCase()}
              </span>
            ) : null,
          )}
          {!demo && <span>{doneToday(cards, new Date())} done today</span>}
          <button
            type="button"
            aria-pressed={demo}
            onClick={() => {
              setDemo((d) => !d);
              setStep(0);
              setLastStep(-1);
              setDemoFeed([]);
            }}
            className="office3d-btn"
          >
            {demo ? "Exit demo" : "Demo"}
          </button>
        </div>
      </header>

      <div className="grid min-h-0 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div className="relative h-[60dvh] min-h-[360px] lg:h-[min(74vh,760px)] lg:min-h-[420px]">
          {gl === false ? (
            <NoWebGL />
          ) : gl === null ? (
            <SceneLoading />
          ) : (
            <Scene
              ref={cam}
              members={agents.length - 1}
              stations={agents.map((a, i) => ({
                key: a.key,
                title: a.title,
                accent: accents[i] ?? "#9cb59a",
                screen: screen(i),
              }))}
              done={demo ? 4 + (step % 6) : doneToday(cards, new Date())}
              evening={evening}
              paused={hidden}
              onMissed={() => {
                setSelected(null);
              }}
              crew={{
                agents,
                accents,
                offline,
                moved,
                selected,
                hovered,
                bus,
                onHover: setHovered,
                still,
                onSelect: setSelected,
              }}
            />
          )}
          {gl && (
            <Overlay
              agents={agents.map((a, i) => ({
                key: a.key,
                title: a.title,
                activity: activities[i] ?? "idle",
              }))}
              bus={bus}
              selected={selected}
              hovered={hovered}
            />
          )}

          {gl && (
            <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-1 rounded-xl border border-white/8 bg-hud-night/90 p-1 backdrop-blur">
              <button
                type="button"
                className="office3d-icon"
                aria-label="Zoom in"
                title="Zoom in"
                onClick={() => cam.current?.zoomBy(1.25)}
              >
                +
              </button>
              <button
                type="button"
                className="office3d-icon"
                aria-label="Zoom out"
                title="Zoom out"
                onClick={() => cam.current?.zoomBy(0.8)}
              >
                −
              </button>
              <button
                type="button"
                className="office3d-btn"
                onClick={() => cam.current?.reset()}
              >
                Reset view
              </button>
              <span className="mx-1 h-5 w-px bg-white/10" />
              <button
                type="button"
                className="office3d-btn"
                aria-pressed={evening}
                onClick={() => {
                  setEvening((e) => !e);
                }}
              >
                {evening ? "☾ Evening" : "☀ Daylight"}
              </button>
              <button
                type="button"
                className="office3d-btn"
                title="Auto follows your system's reduced-motion setting"
                onClick={() => {
                  setMotion((m) =>
                    m === "auto"
                      ? reduceOS
                        ? "full"
                        : "reduced"
                      : m === "reduced"
                        ? "full"
                        : "auto",
                  );
                }}
              >
                Motion:{" "}
                {motion === "auto"
                  ? reduceOS
                    ? "Auto (reduced)"
                    : "Auto"
                  : motion === "full"
                    ? "Full"
                    : "Reduced"}
              </button>
            </div>
          )}

          {chosen && (
            <Inspector
              key={chosen.key}
              agent={chosen}
              activity={activityOf(chosen, offline)}
              cards={demo ? [] : cards}
              workspaceId={workspaceId}
              base={base}
              demo={demo}
              onClose={() => {
                setSelected(null);
              }}
            />
          )}
        </div>

        <aside className="flex min-h-0 flex-col border-t border-white/[0.07] lg:max-h-[min(74vh,760px)] lg:border-t-0 lg:border-l">
          <section aria-label="Team" className="p-3">
            <h3 className="px-1 pb-2 text-10 font-semibold tracking-caps-wide text-hud-stone uppercase">
              Team
            </h3>
            <ul className="flex flex-col gap-0.5">
              {agents.map((a, i) => {
                const act = activities[i] ?? "idle";
                return (
                  <li key={a.key}>
                    <button
                      type="button"
                      aria-pressed={selected === a.key}
                      onClick={() => {
                        setSelected(selected === a.key ? null : a.key);
                      }}
                      onMouseEnter={() => {
                        setHovered(a.key);
                      }}
                      onMouseLeave={() => {
                        setHovered(null);
                      }}
                      className={cn(
                        "flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors duration-150 hover:bg-white/5",
                        selected === a.key && "bg-white/8",
                      )}
                    >
                      <span
                        className="size-2.5 shrink-0 rounded-full"
                        style={{ background: accents[i] }}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-13 text-hud-cream">
                          {a.title}
                        </span>
                        <span className="block truncate text-11 text-hud-stone">
                          {a.current && act !== "break" && act !== "idle"
                            ? a.current.title
                            : LABEL[act]}
                        </span>
                      </span>
                      <span
                        className="inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-10 text-hud-sand-light"
                        style={{ background: `${DOT[act]}26` }}
                      >
                        <span
                          className="size-1.5 rounded-full"
                          style={{ background: DOT[act] }}
                        />
                        {LABEL[act]}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
          <section
            aria-label="Activity"
            className="flex min-h-0 flex-1 flex-col border-t border-white/[0.07]"
          >
            <button
              type="button"
              aria-expanded={feedOpen}
              onClick={() => {
                setFeedOpen((o) => !o);
              }}
              className="flex items-center justify-between px-4 py-2.5 text-10 font-semibold tracking-caps-wide text-hud-stone uppercase hover:text-hud-cream"
            >
              {demo ? "Activity · demo" : "Activity"}
              <span aria-hidden>{feedOpen ? "−" : "+"}</span>
            </button>
            {feedOpen && (
              <ol className="max-h-80 min-h-0 flex-1 overflow-y-auto px-3 pb-3 lg:max-h-none">
                {feed.length === 0 && (
                  <li className="px-1 text-xs text-hud-stone">Nothing yet.</li>
                )}
                {feed.map((e, i) => (
                  <li
                    key={`${String(e.at)}-${String(i)}`}
                    className="flex gap-2 rounded-md px-1 py-1.5 text-xs"
                  >
                    <span
                      className="mt-1 size-1.5 shrink-0 rounded-full"
                      style={{
                        background:
                          e.kind === "done"
                            ? "#5fbf7f"
                            : e.kind === "handoff" || e.kind === "new"
                              ? "#c9a45c"
                              : "#8f9be0",
                      }}
                    />
                    <span className="min-w-0 flex-1 text-hud-sand">
                      <strong className="font-medium text-hud-cream">
                        {e.who}
                      </strong>{" "}
                      {e.text}
                    </span>
                    <span className="shrink-0 text-hud-stone-deep tabular-nums">
                      {ago(e.at)}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
