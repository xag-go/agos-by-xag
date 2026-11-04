"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import type { Readiness } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { suggestKit } from "./actions";
import type { Kit, KitState, KitTool } from "./kit-types";

const SOURCE_WORDS: Record<string, string> = {
  library: "in the library",
  find: "to find",
  write: "to write",
};

function toolWay(t: KitTool): string {
  if (t.connector) return `connector ${t.connector}`;
  if (t.key) return `API key ${t.key}`;
  return "no connector or API";
}

function Chips({ items }: { items: string[] }) {
  if (items.length === 0) return <span className="text-ink-3">none</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((s) => (
        <span
          key={s}
          className="rounded-md bg-sunken px-1.5 py-0.5 text-xs text-ink-2"
        >
          {s}
        </span>
      ))}
    </span>
  );
}

function Line({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-24 shrink-0 text-ink-3">{label}</span>
      <span className="min-w-0 flex-1 text-ink">{children}</span>
    </div>
  );
}

/** The kit as proposed (read only). */
export function KitView({ kit }: { kit: Kit }) {
  const test = kit.onboarding ?? {};
  return (
    <div className="flex flex-col gap-1">
      <Line label="Tools">
        <Chips
          items={(kit.tools ?? []).map((t) => `${t.name} · ${toolWay(t)}`)}
        />
      </Line>
      <Line label="Kit skills">
        <Chips
          items={(kit.skills ?? []).map(
            (s) => `${s.name} · ${SOURCE_WORDS[s.source ?? "library"] ?? ""}`,
          )}
        />
      </Line>
      <Line label="Docs">
        <Chips
          items={(kit.docs ?? []).map(
            (d) =>
              `${d.kind === "example" ? "Example" : "Doc"}: ${d.title || d.path || d.url || ""}`,
          )}
        />
      </Line>
      {(kit.team?.works_with?.length ?? 0) > 0 || kit.team?.project ? (
        <Line label="Works with">
          {(kit.team?.works_with ?? []).map((n) => `@${n}`).join(", ") || "—"}
          {kit.team?.project && (
            <span className="text-ink-3"> · {kit.team.project}</span>
          )}
        </Line>
      ) : null}
      {test.task && (
        <Line label="First test">
          <span className="whitespace-pre-wrap">{test.task}</span>
          {(test.criteria?.length ?? 0) > 0 && (
            <ul className="mt-0.5 list-disc pl-4 text-ink-2">
              {(test.criteria ?? []).map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}
        </Line>
      )}
    </div>
  );
}

const STATE_WORDS: Record<Readiness["state"], string> = {
  not_ready: "Not ready",
  onboarding: "Onboarding",
  ready: "Ready",
};

/** The member box's chip: Not ready / Onboarding / Ready. */
export function ReadinessChip({
  state,
  className,
}: {
  state: Readiness["state"];
  className?: string;
}) {
  return (
    <span
      className={cn(
        "rounded-md px-1.5 py-0.5 text-11 font-medium",
        state === "ready" && "bg-live/15 text-ink-2",
        state === "onboarding" && "bg-sunken text-ink-2",
        state === "not_ready" && "bg-attention text-attention-ink",
        className,
      )}
    >
      {STATE_WORDS[state]}
    </span>
  );
}

const KIT_WORDS: Record<KitState, string> = {
  none: "No kit yet",
  incomplete: "Kit incomplete",
  whole: "Kit",
};

/** The member box's chip for a member without a whole kit (nothing when whole). */
export function KitChip({
  state,
  className,
}: {
  state: KitState | null | undefined;
  className?: string;
}) {
  if (!state || state === "whole") return null;
  return (
    <span
      className={cn(
        "shrink-0 rounded-md bg-attention px-1.5 py-0.5 text-11 font-medium whitespace-nowrap text-attention-ink",
        className,
      )}
    >
      {KIT_WORDS[state]}
    </span>
  );
}

/** "Suggest kit": the Co-Founder proposes a whole kit for this member from its
 * role and its work; it arrives in the Inbox as "Kit for @member". While one is
 * asked (or waits in the Inbox), a link to its card instead. */
export function SuggestKitButton({
  workspaceId,
  member,
  card,
  className,
}: {
  workspaceId: string;
  member: string;
  card?: string | null;
  className?: string;
}) {
  const [asked, setAsked] = useState<string | null>(card ?? null);
  const [said, setSaid] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  if (asked) {
    return (
      <span className={cn("flex flex-col gap-0.5", className)}>
        <Link
          href={`/w/${encodeURIComponent(workspaceId)}/kanban?card=${encodeURIComponent(asked)}`}
          className="self-start text-sm text-ink-2 underline decoration-line underline-offset-2 hover:decoration-ink"
        >
          Kit asked — see the card
        </Link>
        {said && <span className="text-xs text-ink-3">{said}</span>}
      </span>
    );
  }
  return (
    <span className={cn("flex flex-col gap-1", className)}>
      <Button
        className="self-start"
        disabled={busy}
        onClick={() => {
          setError(null);
          start(async () => {
            const r = await suggestKit(workspaceId, member);
            if (r.error) setError(r.error);
            else {
              setAsked(r.card ?? null);
              setSaid(
                r.created === false
                  ? "Already asked: its kit arrives in your Inbox."
                  : "Asked the Co-Founder: its kit arrives in your Inbox.",
              );
            }
          });
        }}
      >
        {busy ? "Asking…" : "Suggest kit"}
      </Button>
      {error && (
        <span role="alert" className="text-sm text-danger">
          {error}
        </span>
      )}
    </span>
  );
}
