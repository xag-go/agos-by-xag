"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { ExternalObject } from "@/data/types";
import { cn } from "./cn";

/** The live state of the outside objects (PRs, issues, tickets) the text around
 * links, read once by a provider above (the card): url → its chip. */
export const LinkChips = createContext<ReadonlyMap<string, ExternalObject>>(
  new Map(),
);

const LOGO: Record<ExternalObject["kind"], string> = {
  github_pr: "PR",
  github_issue: "Issue",
  linear: "Linear",
  jira: "Jira",
};

function tone(chip: ExternalObject): string {
  if (!chip.ok) return "bg-sunken text-ink-3";
  if (chip.state === "merged") return "bg-accent/15 text-accent";
  if (chip.done) return "bg-sunken text-ink-2";
  if (chip.state === "draft") return "bg-sunken text-ink-3";
  return "bg-success/15 text-success";
}

/** A link in Markdown: a chip with the object's live title and state when the
 * provider above knows it, else the plain link. */
export function MarkdownLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  const chip = useContext(LinkChips).get(href);
  if (!chip) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
      >
        {children}
      </a>
    );
  }
  const why =
    chip.why === "no_key"
      ? "add the app's key in Settings → Keys to see its state"
      : chip.why === "private"
        ? "not visible with this workspace's key"
        : "couldn't be read just now";
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      title={
        chip.ok
          ? `${chip.key} · ${chip.stateLabel}`
          : `${chip.key || href}: ${why}`
      }
      className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-line px-1.5 py-0.5 align-middle text-xs no-underline hover:border-ink-3"
    >
      <span className="font-semibold text-ink-3">{LOGO[chip.kind]}</span>
      <span className="font-mono text-ink-2">{chip.key}</span>
      {chip.title && <span className="truncate text-ink">{chip.title}</span>}
      {chip.ok && (
        <span className={cn("rounded px-1 py-px font-medium", tone(chip))}>
          {chip.stateLabel || chip.state}
        </span>
      )}
    </a>
  );
}
