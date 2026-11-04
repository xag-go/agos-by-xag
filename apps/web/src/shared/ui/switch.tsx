"use client";

import { useState } from "react";
import { cn } from "./cn";

/**
 * On/off toggle. Inside a form, give it a `name`: it submits "on" when on and
 * nothing when off, like a checkbox. `onChange` runs right after a toggle.
 */
export function Switch({
  defaultOn,
  label,
  name,
  onChange,
  disabled = false,
}: {
  defaultOn: boolean;
  label: string;
  name?: string;
  onChange?: (on: boolean) => void | Promise<void>;
  disabled?: boolean;
}) {
  const [on, setOn] = useState(defaultOn);
  return (
    <>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        disabled={disabled}
        onClick={() => {
          const next = !on;
          setOn(next);
          void onChange?.(next);
        }}
        className={cn(
          "relative inline-flex h-6 w-10 shrink-0 items-center rounded-full border transition-colors disabled:opacity-50",
          on ? "border-accent bg-accent" : "border-line-strong bg-sunken",
        )}
      >
        <span
          className={cn(
            "inline-block size-4 rounded-full transition-transform",
            on ? "translate-x-5 bg-accent-ink" : "translate-x-1 bg-ink-3",
          )}
        />
      </button>
      {name && on && <input type="hidden" name={name} value="on" />}
    </>
  );
}
