"use client";

import { useState, useTransition } from "react";
import type { Chat } from "@/data/types";
import { cn } from "@/shared/ui/cn";
import { setChatAccess } from "./actions";
import { MenuBackdrop } from "@/shared/ui/menu-backdrop";
import { Panel } from "@/shared/ui/panel";

/** "Ask me" / "Full access" for this chat. Only the owner's click changes it. */
export function AccessSwitch({
  workspaceId,
  chat,
  onError,
}: {
  workspaceId: string;
  chat: Chat;
  onError: (message: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, start] = useTransition();
  const locked = chat.workspaceFull ?? false;
  const full = locked || chat.access === "full";
  function pick(access: "ask" | "full") {
    setOpen(false);
    if (access === chat.access) return;
    start(async () => {
      const result = await setChatAccess(workspaceId, chat.id, access);
      if (result.error) onError(result.error);
    });
  }
  return (
    <div className="relative">
      <button
        type="button"
        disabled={busy || locked}
        title={
          locked
            ? "The workspace is on Full access (Workspace settings): every chat runs commands without asking."
            : undefined
        }
        onClick={() => {
          setOpen((o) => !o);
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cn(
          "flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors disabled:opacity-60",
          full
            ? "bg-attention text-attention-ink"
            : "text-ink-2 hover:bg-canvas hover:text-ink",
        )}
      >
        <svg
          viewBox="0 0 16 16"
          className="size-3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          aria-hidden
        >
          {full ? (
            <path
              d="M8 1.75 2.75 3.75v4c0 3.2 2.2 5.5 5.25 6.5 3.05-1 5.25-3.3 5.25-6.5v-4L8 1.75Z"
              strokeLinejoin="round"
            />
          ) : (
            <>
              <path
                d="M8 1.75 2.75 3.75v4c0 3.2 2.2 5.5 5.25 6.5 3.05-1 5.25-3.3 5.25-6.5v-4L8 1.75Z"
                strokeLinejoin="round"
              />
              <path
                d="m5.75 8 1.5 1.5 3-3"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </>
          )}
        </svg>
        {full ? "Full access" : "Ask me"}
        <svg viewBox="0 0 12 12" className="size-2.5 opacity-60" aria-hidden>
          <path
            d="m3 4.5 3 3 3-3"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </button>
      {open && (
        <>
          <MenuBackdrop
            onClose={() => {
              setOpen(false);
            }}
          />
          <Panel
            role="menu"
            className="absolute bottom-10 left-0 z-30 w-72 p-1.5 shadow-popover"
          >
            <AccessOption
              checked={!full}
              title="Ask me first"
              hint="Risky commands wait for Allow once / Deny."
              onClick={() => {
                pick("ask");
              }}
            />
            <AccessOption
              checked={full}
              title="Full access"
              hint="Runs commands without asking — inside this workspace's sandbox only. Only catastrophic commands (like wiping the whole disk) stay blocked."
              onClick={() => {
                pick("full");
              }}
            />
          </Panel>
        </>
      )}
    </div>
  );
}

function AccessOption({
  checked,
  title,
  hint,
  onClick,
}: {
  checked: boolean;
  title: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={checked}
      onClick={onClick}
      className="flex w-full items-start gap-2.5 rounded-xl px-3 py-2 text-left hover:bg-canvas"
    >
      <span
        className={cn(
          "mt-1 flex size-3.5 shrink-0 items-center justify-center rounded-full border",
          checked ? "border-accent" : "border-line-strong",
        )}
      >
        {checked && <span className="size-1.5 rounded-full bg-accent" />}
      </span>
      <span className="flex flex-col">
        <span className="text-sm text-ink">{title}</span>
        <span className="text-xs text-ink-3">{hint}</span>
      </span>
    </button>
  );
}
