"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "./cn";
import { PANEL } from "./panel";

/**
 * A modal driven by the URL: it is rendered when a search param says so, and
 * closing it navigates to `closeHref`. Uses the native <dialog>, which gives
 * focus trapping, Escape to close and an inert background for free.
 */
export function RouteDialog({
  closeHref,
  label,
  children,
  size = "lg",
}: {
  closeHref: string;
  label: string;
  children: ReactNode;
  size?: "md" | "lg" | "xl";
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const router = useRouter();

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) {
      dialog.showModal();
      // Start focus on the dialog itself, not on its first button.
      dialog.focus();
    }
  }, []);

  return (
    <dialog
      ref={ref}
      aria-label={label}
      tabIndex={-1}
      onClose={() => {
        router.push(closeHref, { scroll: false });
      }}
      onClick={(event) => {
        // A click on the backdrop lands on the <dialog> element itself.
        if (event.target === ref.current) ref.current.close();
      }}
      className={cn(
        PANEL,
        "m-auto max-h-[92dvh] w-[calc(100%-2rem)] overflow-hidden p-0 text-ink shadow-2xl max-sm:max-h-[calc(100dvh-2.5rem)] max-sm:w-[calc(100%-1.25rem)] max-sm:overflow-y-auto",
        size === "xl" ? "max-w-6xl" : size === "lg" ? "max-w-4xl" : "max-w-xl",
      )}
    >
      {children}
    </dialog>
  );
}

/**
 * A modal opened by state (not the URL): shown where the owner is, over the page.
 * Native <dialog>: focus trap, Escape and backdrop click close it (onClose).
 */
export function Modal({
  label,
  onClose,
  children,
  size = "md",
}: {
  label: string;
  onClose: () => void;
  children: ReactNode;
  size?: "md" | "lg";
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={label}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) ref.current.close();
      }}
      className={cn(
        PANEL,
        "m-auto max-h-[92dvh] w-[calc(100%-2rem)] overflow-y-auto p-0 text-ink shadow-2xl max-sm:max-h-[calc(100dvh-2.5rem)] max-sm:w-[calc(100%-1.25rem)]",
        size === "lg" ? "max-w-3xl" : "max-w-xl",
      )}
    >
      {children}
    </dialog>
  );
}

/** Closes the surrounding dialog. A plain button, so it can sit inside a form. */
export function DialogCloseButton() {
  return (
    <button
      type="button"
      aria-label="Close"
      onClick={(event) => {
        event.currentTarget.closest("dialog")?.close();
      }}
      className="grid size-8 place-items-center rounded-lg text-ink-2 hover:bg-sunken hover:text-ink"
    >
      <svg viewBox="0 0 16 16" className="size-4" aria-hidden="true">
        <path
          d="M4 4l8 8M12 4l-8 8"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );
}
