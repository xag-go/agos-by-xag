"use client";

import { useState, useTransition } from "react";
import type { ChatActivity } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { answerApproval, retryChat } from "./actions";

export function ApprovalCard({
  workspaceId,
  chatId,
  item,
}: {
  workspaceId: string;
  chatId: number;
  item: ChatActivity;
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  function answer(choice: "once" | "deny") {
    start(async () => {
      const result = await answerApproval(workspaceId, chatId, choice);
      if (result.error) setError(result.error);
    });
  }
  return (
    <div className="max-w-xl rounded-2xl border border-attention/40 bg-attention-soft px-4 py-3 text-sm">
      <p className="font-medium text-ink">
        The agent wants to run a command that needs your OK
      </p>
      {item.detail && (
        <pre className="mt-2 overflow-x-auto rounded-lg bg-panel/70 px-2.5 py-1.5 font-mono text-xs whitespace-pre-wrap text-ink">
          {item.detail}
        </pre>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          className="h-8"
          disabled={busy}
          onClick={() => {
            answer("once");
          }}
        >
          Allow once
        </Button>
        <Button
          className="h-8"
          disabled={busy}
          onClick={() => {
            answer("deny");
          }}
        >
          Deny
        </Button>
        <span className="text-xs text-ink-2">
          {item.title.includes("your rule")
            ? "This is one of your Ask me rules (Settings → Autonomy)."
            : "Tired of this? Switch the chat to Full access below."}
        </span>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function RetryButton({
  workspaceId,
  chatId,
}: {
  workspaceId: string;
  chatId: number;
}) {
  const [busy, start] = useTransition();
  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => {
        start(async () => {
          await retryChat(workspaceId, chatId);
        });
      }}
      className="text-xs font-medium text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink disabled:opacity-50"
    >
      Try again
    </button>
  );
}
