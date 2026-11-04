"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Button } from "./button";
import { Input } from "./field";
import { PANEL } from "./panel";

type Ask = {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  /** Set to ask for a value (e.g. a name); the answer is the typed text. */
  input?: { label: string; initial?: string };
};

type Pending = Ask & { resolve: (answer: string | null) => void };

/**
 * The app's own confirm / prompt popup (never the browser's). Render `dialog`
 * once in the component, then `await ask({...})`: it resolves to the typed
 * text (or "" when there is no input) on confirm, and null on cancel.
 */
export function useAsk(): {
  dialog: ReactNode;
  ask: (question: Ask) => Promise<string | null>;
  confirm: (question: Ask) => Promise<boolean>;
} {
  const [pending, setPending] = useState<Pending | null>(null);
  const ask = useCallback(
    (question: Ask) =>
      new Promise<string | null>((resolve) => {
        setPending({ ...question, resolve });
      }),
    [],
  );
  const confirm = useCallback(
    async (question: Ask) => (await ask(question)) !== null,
    [ask],
  );
  const dialog = pending ? (
    <AskDialog
      key={pending.title}
      question={pending}
      onDone={(answer) => {
        pending.resolve(answer);
        setPending(null);
      }}
    />
  ) : null;
  return { dialog, ask, confirm };
}

function AskDialog({
  question: q,
  onDone,
}: {
  question: Ask;
  onDone: (answer: string | null) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const answered = useRef(false);
  const [value, setValue] = useState(q.input?.initial ?? "");

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  const finish = (answer: string | null) => {
    if (answered.current) return;
    answered.current = true;
    ref.current?.close();
    onDone(answer);
  };

  return (
    <dialog
      ref={ref}
      aria-label={q.title}
      onClose={() => {
        finish(null);
      }}
      onClick={(event) => {
        if (event.target === ref.current) finish(null);
      }}
      className={`${PANEL} m-auto w-[calc(100%-2rem)] max-w-md p-0 text-ink shadow-2xl`}
    >
      <form
        method="dialog"
        className="flex flex-col gap-4 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (q.input && !value.trim()) return;
          finish(q.input ? value.trim() : "");
        }}
      >
        <h2 className="font-display text-lg font-semibold">{q.title}</h2>
        {q.body && (
          <div className="text-sm whitespace-pre-line text-ink-2">{q.body}</div>
        )}
        {q.input && (
          <Input
            autoFocus
            aria-label={q.input.label}
            placeholder={q.input.label}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
            }}
          />
        )}
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            autoFocus={!q.input}
            onClick={() => {
              finish(null);
            }}
          >
            Cancel
          </Button>
          <Button type="submit" variant={q.danger ? "danger" : "primary"}>
            {q.confirmLabel ?? "OK"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
