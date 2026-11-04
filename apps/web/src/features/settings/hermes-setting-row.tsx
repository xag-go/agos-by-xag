"use client";

import Link from "next/link";
import type {
  HermesAllSettings as HermesSettings,
  HermesSettingRow as HermesSetting,
} from "@/data/queries";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import {
  RULE_LABEL,
  cardHref,
  changedFromDefault,
  shownValue,
} from "./hermes-settings-shared";
import { Panel } from "@/shared/ui/panel";

/** The shared home (the owner's own Hermes): read-only, the keys that matter. */
export function SharedHome({
  home,
  rows,
}: {
  home: string;
  rows: HermesSettings["shared"];
}) {
  if (rows.length === 0) return null;
  return (
    <Panel as="details">
      <summary className="cursor-pointer px-5 py-4">
        <span className="font-medium">Your own Hermes</span>
        <span className="ml-2 text-sm text-ink-3">{rows.length}</span>
        <span className="mt-1 block text-sm text-ink-2">
          The shared home <code className="break-all">{home}</code> is no
          workspace&apos;s: this page doesn&apos;t change it. These of its
          settings still matter for AGOS (read-only, with why).
        </span>
      </summary>
      <ul className="divide-y divide-line border-t border-line">
        {rows.map((r) => (
          <li key={r.key} className="flex flex-col gap-1 px-5 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <code className="text-sm break-all">{r.key}</code>
              <span className="text-sm">
                <code className="break-all">
                  {r.set ? shownValue(r.value) : "not set (Hermes's default)"}
                </code>
              </span>
            </div>
            {r.managed !== null && r.managed !== undefined ? (
              <p className="text-xs text-ink-2">
                AGOS&apos;s runs use{" "}
                <code className="break-all">{shownValue(r.managed)}</code> (the
                managed scope).
              </p>
            ) : null}
            <p className="text-xs text-ink-3">{r.reason}</p>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function SettingRow({
  row,
  cards,
  firstWs,
  onEdit,
}: {
  row: HermesSetting;
  cards: Record<string, string>;
  firstWs: string | null;
  onEdit: () => void;
}) {
  const href = row.rule?.card ? cardHref(row.rule.card, firstWs) : null;
  const changed = changedFromDefault(row);
  return (
    <li className="flex flex-col gap-1.5 px-5 py-3" data-key={row.key}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <code className="text-sm font-medium break-all">{row.key}</code>
          {row.source === "env" ? (
            <span className="ml-2 inline-block rounded-full border border-line-strong px-2 py-0.5 text-xs text-ink-2">
              .env
            </span>
          ) : null}
          <p className="text-sm text-ink-2">{row.description}</p>
        </div>
        {row.editable ? (
          <Button
            className="h-8 shrink-0"
            onClick={onEdit}
            aria-label={`Change ${row.key}`}
          >
            Change
          </Button>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2">
        <span>
          {row.same ? "Now (every workspace): " : "Most workspaces: "}
          <code
            className={cn(
              "break-all",
              changed ? "font-semibold text-ink" : "text-ink-2",
            )}
          >
            {shownValue(row.value)}
          </code>
        </span>
        {row.source === "env" ? (
          <span>
            In each profile&apos;s .env
            {row.inDefaults ? "" : " (not in Hermes's list of .env settings)"};
            set in {row.setIn}
          </span>
        ) : (
          <span>
            Hermes default:{" "}
            <code className="break-all">
              {row.inDefaults ? shownValue(row.default) : "none listed"}
            </code>
          </span>
        )}
      </div>
      {!row.same ? (
        <ul className="flex flex-col gap-0.5 rounded-lg bg-sunken px-3 py-2 text-xs">
          {row.workspaces.map((w) => (
            <li key={w.id}>
              <span className="font-medium">{w.name}</span>:{" "}
              <code className="break-all">{shownValue(w.value)}</code>
              {w.members.map((m) => (
                <span key={m.label} className="block pl-4 text-ink-2">
                  {m.label}:{" "}
                  <code className="break-all">{shownValue(m.value)}</code>
                </span>
              ))}
            </li>
          ))}
        </ul>
      ) : null}
      {row.notes.length > 0 ? (
        <ul className="flex flex-col gap-0.5 rounded-lg bg-sunken px-3 py-2 text-xs">
          {row.notes.map((n) => (
            <li key={`${n.label}-${n.value}`}>
              <span className="font-medium">{n.label}</span>:{" "}
              <code className="break-all">{n.value}</code> — {n.reason}
            </li>
          ))}
        </ul>
      ) : null}
      {row.pair ? (
        <p className="text-xs text-ink-2">
          One model choice with{" "}
          <code>
            {row.key === row.pair.provider ? row.pair.model : row.pair.provider}
          </code>
          : changed together with AGOS&apos;s model picker.
        </p>
      ) : null}
      {row.rule ? (
        <p className="text-xs text-ink-2">
          <span
            className={cn(
              "mr-2 inline-block rounded-full border px-2 py-0.5 font-medium",
              row.rule.kind === "forced" || row.rule.kind === "locked"
                ? "border-accent/40 text-ink"
                : "border-line-strong",
            )}
          >
            {RULE_LABEL[row.rule.kind] ?? row.rule.kind}
          </span>
          {row.rule.reason}
          {row.rule.card && href ? (
            <>
              {" "}
              <Link href={href} className="underline">
                Open {cards[row.rule.card] ?? "the card"}
              </Link>
            </>
          ) : null}
        </p>
      ) : null}
    </li>
  );
}
