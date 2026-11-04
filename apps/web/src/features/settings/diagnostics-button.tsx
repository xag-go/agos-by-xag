"use client";

import { useState } from "react";
import { getStatus } from "@/shared/get-status";
import { Button } from "@/shared/ui/button";

type Answer =
  | { ok: true; data: { madeAt: string; text: string } }
  | { ok: false; error: string };

/** Copies the redacted diagnostics report (for a GitHub issue) to the clipboard;
 * the same text as `agos doctor --bundle` on the machine. */
export function DiagnosticsButton() {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const copy = async () => {
    setBusy(true);
    setNote("");
    const answer = await getStatus<Answer>("/api/diagnostics");
    setBusy(false);
    if (!answer?.ok) {
      setNote(answer?.error ?? "AGOS didn't answer.");
      return;
    }
    try {
      await navigator.clipboard.writeText(answer.data.text);
      setNote("Copied. Paste it into your GitHub issue.");
    } catch {
      setNote("Couldn't copy here: run agos doctor --bundle instead.");
    }
  };
  return (
    <span className="flex items-center gap-2">
      <Button disabled={busy} onClick={() => void copy()}>
        {busy ? "Working…" : "Copy diagnostics"}
      </Button>
      {note ? (
        <span role="status" className="text-sm text-ink-2">
          {note}
        </span>
      ) : null}
    </span>
  );
}
