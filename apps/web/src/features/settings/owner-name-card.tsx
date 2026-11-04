"use client";

import { useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/field";
import { saveOwnerName } from "./preferences-actions";

/** His name, one for every workspace: the Founder box beside the Co-Founder, his
 * cards' member slot, his Inbox and phone notices, the Co-Founder's prompt. */
export function OwnerNameCard({ initial }: { initial: string }) {
  const [value, setValue] = useState(initial);
  const [saved, setSaved] = useState(initial);
  const [note, setNote] = useState<string | null>(null);
  const [busy, start] = useTransition();

  const save = () => {
    setNote(null);
    start(async () => {
      const r = await saveOwnerName(value);
      if (r.error) setNote(r.error);
      else {
        setSaved(value.trim());
        setNote("Saved.");
      }
    });
  };

  return (
    <form
      className="flex flex-wrap items-center gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <Input
        aria-label="Your name"
        value={value}
        maxLength={64}
        placeholder="Your name"
        disabled={busy}
        onChange={(e) => {
          setValue(e.target.value);
          setNote(null);
        }}
        className="h-9 w-72"
      />
      <Button
        type="submit"
        variant="primary"
        disabled={busy || value.trim() === saved}
      >
        Save
      </Button>
      {note ? (
        <span role="status" className="text-sm text-ink-2">
          {note}
        </span>
      ) : null}
    </form>
  );
}
