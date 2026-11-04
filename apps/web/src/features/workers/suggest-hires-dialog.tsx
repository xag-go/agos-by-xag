"use client";

import { useEffect, useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { DialogCloseButton, Modal } from "@/shared/ui/dialog";
import { Field, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { suggestHires } from "./actions";

/**
 * "Suggest hires": the owner opens the door himself. An optional note, then a
 * card on the Co-Founder, which proposes each hire it finds the team needs as
 * its own Inbox item (he approves some, rejects others).
 */
export function SuggestHiresDialog({
  workspaceId,
  onClose,
  onAsked,
}: {
  workspaceId: string;
  onClose: () => void;
  onAsked: (words: string) => void;
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  return (
    <Modal label="Suggest hires" onClose={onClose}>
      <form
        className="flex flex-col gap-4 p-6"
        onSubmit={(event) => {
          event.preventDefault();
          if (busy) return;
          setError(null);
          start(async () => {
            const r = await suggestHires(workspaceId, note);
            if (r.error) setError(r.error);
            else
              onAsked(
                r.created === false
                  ? "The Co-Founder is still on your last ask — its suggestions will arrive in your Inbox"
                  : "Asked the Co-Founder — its suggestions will arrive in your Inbox",
              );
          });
        }}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-display text-lg font-semibold">
              Suggest hires
            </h3>
            <p className="mt-1 text-sm text-ink-2">
              The Co-Founder reads the goal and the team, then proposes each
              hire it thinks the team needs now. Each one arrives in your Inbox
              on its own: approve the ones you want, reject the rest.
            </p>
          </div>
          <DialogCloseButton />
        </div>
        <Field label="What should the team do better? (optional)">
          <Textarea
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
            }}
            placeholder="e.g. We post too little on TikTok and nobody edits the videos."
          />
        </Field>
        <FormStatus error={error} />
        <div className="flex justify-end">
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? "Asking…" : "Ask the Co-Founder"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

const NOTICE_MS = 6000;

/** A short line at the bottom of the chart that goes by itself. */
export function Notice({
  words,
  onGone,
}: {
  words: string;
  onGone: (words: null) => void;
}) {
  useEffect(() => {
    const timer = setTimeout(() => {
      onGone(null);
    }, NOTICE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [words, onGone]);
  return (
    <div
      role="status"
      className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-xl border border-line bg-panel px-4 py-2 text-sm shadow-lg"
    >
      {words}
    </div>
  );
}
