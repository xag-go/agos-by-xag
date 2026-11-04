"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/shared/ui/button";
import { Textarea } from "@/shared/ui/field";
import { PANEL } from "@/shared/ui/panel";

export type EditChoice = { text: string; reanswer: boolean };

/**
 * Edit one of your messages (the app's own popup). When the agent already
 * answered it, two choices: just save, or save and get a new answer now.
 */
export function EditMessageDialog({
  initial,
  answered,
  busy,
  onDone,
}: {
  initial: string;
  /** The agent already answered this message. */
  answered: boolean;
  /** The agent is answering right now (a new answer must wait). */
  busy: boolean;
  onDone: (choice: EditChoice | null) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const done = useRef(false);
  const [text, setText] = useState(initial);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  const finish = (choice: EditChoice | null) => {
    if (done.current) return;
    done.current = true;
    ref.current?.close();
    onDone(choice);
  };
  const empty = !text.trim();

  return (
    <dialog
      ref={ref}
      aria-label="Edit your message"
      onClose={() => {
        finish(null);
      }}
      onClick={(event) => {
        if (event.target === ref.current) finish(null);
      }}
      className={`${PANEL} m-auto w-[calc(100%-2rem)] max-w-xl p-0 text-ink shadow-2xl`}
    >
      <form
        method="dialog"
        className="flex flex-col gap-4 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (!empty)
            finish({ text: text.trim(), reanswer: answered && !busy });
        }}
      >
        <h2 className="font-display text-lg font-semibold">
          Edit your message
        </h2>
        <Textarea
          autoFocus
          aria-label="Message"
          value={text}
          rows={Math.min(12, Math.max(3, text.split("\n").length + 1))}
          onChange={(e) => {
            setText(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
        />
        {answered && (
          <p className="text-xs text-ink-3">
            {busy
              ? "The agent is answering right now: you can save, and ask for a new answer once it's done."
              : "Save & answer again: the agent answers the new version now. Save only: it follows the new version from your next message."}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              finish(null);
            }}
          >
            Cancel
          </Button>
          {answered && !busy && (
            <Button
              type="button"
              variant="secondary"
              disabled={empty}
              onClick={() => {
                if (!empty) finish({ text: text.trim(), reanswer: false });
              }}
            >
              Save only
            </Button>
          )}
          <Button type="submit" variant="primary" disabled={empty}>
            {answered && !busy ? "Save & answer again" : "Save"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
