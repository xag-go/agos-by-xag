"use client";

import { useState, type RefObject } from "react";
import type { useAsk } from "@/shared/ui/confirm";
import { checkAutomation } from "./actions";

type Confirm = ReturnType<typeof useAsk>["confirm"];

/** The owner's Save: ask the core first. Every problem is shown (fix before saving);
 * otherwise how it will run, with Save / Back. Only Save sends the form. */
export function useAutomationReview({
  workspaceId,
  automationId,
  editing,
  form,
  confirm,
}: {
  workspaceId: string;
  automationId: number | null;
  editing: boolean;
  form: RefObject<HTMLFormElement | null>;
  confirm: Confirm;
}) {
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const review = async () => {
    const el = form.current;
    if (!el || !el.reportValidity()) return;
    setChecking(true);
    setError(null);
    try {
      const found = await checkAutomation(
        workspaceId,
        automationId,
        new FormData(el),
      );
      if (found.error) {
        setError(found.error);
      } else if (found.problems.length > 0) {
        await confirm({
          title: "Fix this before saving",
          body: found.problems
            .map((p, i) =>
              found.problems.length > 1 ? `${String(i + 1)}. ${p}` : p,
            )
            .join("\n"),
          confirmLabel: "Back to the form",
          cancelLabel: null,
        });
      } else {
        const warnings =
          found.warnings.length > 0
            ? `\n\nWorth a look (it still saves):\n${found.warnings.map((w) => `- ${w}`).join("\n")}`
            : "";
        const ok = await confirm({
          title: "This is how it will run",
          body: `${found.preview}${warnings}`,
          confirmLabel: editing ? "Save changes" : "Save",
          cancelLabel: "Back",
        });
        if (ok) el.requestSubmit();
      }
    } finally {
      setChecking(false);
    }
  };
  return { review, checking, error };
}
