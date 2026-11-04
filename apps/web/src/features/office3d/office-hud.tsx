"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type { KanbanCard, OfficeLook } from "@/data/types";
import { saveOfficeLook } from "@/features/office/actions";
import { type OfficeAgent, ownerOf } from "@/features/office/model";
import { cn } from "@/shared/ui/cn";
import type { Activity } from "./controller";
import { LABEL } from "./labels";
import { ACCENTS, DOT, ago } from "./office-hooks";

const PETS: OfficeLook["pet"][] = [
  "none",
  "cat",
  "dog",
  "rabbit",
  "bird",
  "fish",
];

export function SceneLoading() {
  return (
    <div className="grid h-full place-items-center text-sm text-hud-stone">
      <span className="office3d-loading">Setting up the office…</span>
    </div>
  );
}

export function NoWebGL() {
  return (
    <div className="grid h-full place-items-center p-6 text-center text-sm text-hud-sand">
      <p className="max-w-sm">
        This browser can’t draw the 3D office (WebGL is off). Your team and what
        they’re doing are in the list beside it.
      </p>
    </div>
  );
}

export function Inspector({
  agent,
  activity,
  cards,
  workspaceId,
  base,
  demo,
  onClose,
}: {
  agent: OfficeAgent;
  activity: Activity;
  cards: KanbanCard[];
  workspaceId: string;
  base: string;
  demo: boolean;
  onClose: () => void;
}) {
  const [look, setLook] = useState<OfficeLook>(agent.look);
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [customise, setCustomise] = useState(false);
  const changed = JSON.stringify(look) !== JSON.stringify(agent.look);
  const recent = cards
    .filter((c) => ownerOf(c) === agent.key && c.status === "done")
    .sort((a, b) => (b.completedAt ?? 0) - (a.completedAt ?? 0))
    .slice(0, 3);
  const latest = cards
    .filter((c) => ownerOf(c) === agent.key)
    .sort(
      (a, b) =>
        Math.max(b.completedAt ?? 0, b.startedAt ?? 0, b.createdAt) -
        Math.max(a.completedAt ?? 0, a.startedAt ?? 0, a.createdAt),
    )[0];
  const message = agent.dmChatId
    ? `${base}/messages?c=${String(agent.dmChatId)}`
    : `${base}/messages`;
  const card = agent.current;

  return (
    <section
      aria-label={`${agent.title} details`}
      className="office3d-inspector absolute inset-x-0 bottom-0 z-20 max-h-[70%] overflow-x-hidden overflow-y-auto rounded-t-2xl border border-white/8 bg-hud-night/95 p-4 shadow-2xl backdrop-blur sm:inset-x-auto sm:top-3 sm:right-3 sm:bottom-auto sm:max-h-[calc(100%-1.5rem)] sm:w-80 sm:rounded-2xl"
    >
      <div className="flex items-start gap-3">
        <span
          className="mt-1.5 size-3 shrink-0 rounded-full"
          style={{ background: ACCENTS[look.colour] }}
        />
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-base font-semibold text-hud-cream-light">
            {agent.title}
          </h3>
          <p className="line-clamp-2 text-xs text-hud-stone">{agent.role}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="office3d-icon"
        >
          ×
        </button>
      </div>

      <dl className="mt-4 grid min-w-0 grid-cols-1 gap-3 text-sm [&>div]:min-w-0">
        <div>
          <dt className="office3d-dt">State</dt>
          <dd className="flex flex-wrap items-center gap-1.5 text-hud-cream">
            <span
              className="size-2 rounded-full"
              style={{ background: DOT[activity] }}
            />
            {LABEL[activity]}
            {activity === "blocked" && (
              <span className="text-xs text-hud-amber">
                · stuck until someone answers it
              </span>
            )}
            {activity === "waiting" && (
              <span className="text-xs text-hud-alarm-soft">
                · needs your review or answer
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="office3d-dt">Current task</dt>
          <dd className="text-hud-cream [overflow-wrap:anywhere]">
            {card ? (
              demo ? (
                card.title
              ) : (
                <Link
                  href={`${base}/kanban?card=${encodeURIComponent(card.id)}`}
                  className="hover:underline"
                >
                  {card.title}
                </Link>
              )
            ) : (
              <span className="text-hud-stone">None</span>
            )}
            {agent.open.length > 1 && (
              <span className="ml-1 text-xs text-hud-stone">
                +{agent.open.length - 1} more
              </span>
            )}
          </dd>
        </div>
        {!demo && latest && (
          <div>
            <dt className="office3d-dt">Latest activity</dt>
            <dd className="text-xs text-hud-sand [overflow-wrap:anywhere]">
              {latest.status === "done"
                ? "Finished"
                : latest.startedAt
                  ? "Started"
                  : "Got"}{" "}
              “{latest.title}” ·{" "}
              {ago(
                Math.max(
                  latest.completedAt ?? 0,
                  latest.startedAt ?? 0,
                  latest.createdAt,
                ),
              )}{" "}
              ago
            </dd>
          </div>
        )}
        {recent.length > 0 && (
          <div>
            <dt className="office3d-dt">Recent output</dt>
            <dd>
              <ul className="flex min-w-0 flex-col gap-1">
                {recent.map((c) => (
                  <li key={c.id} className="min-w-0">
                    <Link
                      href={`${base}/kanban?card=${encodeURIComponent(c.id)}`}
                      className="block truncate text-xs text-hud-sand hover:text-hud-cream-light"
                    >
                      ✓ {c.title}
                    </Link>
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        )}
        {demo && (
          <p className="text-xs text-hud-gold">
            Demo Mode: this task is sample data.
          </p>
        )}
      </dl>

      <div className="mt-4 flex gap-2">
        <Link href={message} className="office3d-btn is-primary">
          Message
        </Link>
        <Link href={`${base}/kanban`} className="office3d-btn">
          Kanban
        </Link>
        <button
          type="button"
          className="office3d-btn ml-auto"
          aria-expanded={customise}
          onClick={() => {
            setCustomise((c) => !c);
          }}
        >
          Customise
        </button>
      </div>

      {customise && (
        <div className="mt-4 grid gap-3 border-t border-white/[0.07] pt-4">
          <fieldset>
            <legend className="office3d-dt mb-1.5">Colour</legend>
            <div className="flex flex-wrap gap-1.5">
              {(Object.keys(ACCENTS) as OfficeLook["colour"][]).map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-label={c}
                  aria-pressed={look.colour === c}
                  onClick={() => {
                    setLook({ ...look, colour: c });
                  }}
                  className={cn(
                    "size-6 rounded-full ring-offset-2 ring-offset-hud-night",
                    look.colour === c && "ring-2 ring-hud-cream-light",
                  )}
                  style={{ background: ACCENTS[c] }}
                />
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend className="office3d-dt mb-1.5">Pet</legend>
            <div className="flex flex-wrap gap-1.5">
              {PETS.map((p) => (
                <button
                  key={p}
                  type="button"
                  aria-pressed={look.pet === p}
                  onClick={() => {
                    setLook({ ...look, pet: p });
                  }}
                  className={cn(
                    "office3d-btn capitalize",
                    look.pet === p && "is-on",
                  )}
                >
                  {p}
                </button>
              ))}
            </div>
          </fieldset>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!changed || pending}
              className="office3d-btn is-primary disabled:opacity-40"
              onClick={() => {
                start(async () => {
                  const r = await saveOfficeLook(workspaceId, agent.key, look);
                  setError(r.error);
                });
              }}
            >
              {pending ? "Saving…" : "Save"}
            </button>
            {error && <p className="text-xs text-hud-alarm-soft">{error}</p>}
          </div>
        </div>
      )}
    </section>
  );
}
