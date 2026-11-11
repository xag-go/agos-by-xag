"use client";

import { useTransition, type RefObject } from "react";
import type { Automation } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { useAsk } from "@/shared/ui/confirm";
import { FormStatus } from "@/shared/ui/form-status";
import { deleteAutomation } from "./actions";
import { useAutomationReview } from "./use-automation-review";

/** The automation dialog's footer: the status line, Delete (editing) and the save
 * button, which first shows the problems or how it will run (use-automation-review). */
export function AutomationFooter({
  workspaceId,
  automation,
  pending,
  saveError,
  form,
}: {
  workspaceId: string;
  automation: Automation | null;
  pending: boolean;
  saveError: string | null;
  form: RefObject<HTMLFormElement | null>;
}) {
  const { dialog, confirm } = useAsk();
  const [deleting, startDelete] = useTransition();
  const { review, checking, error } = useAutomationReview({
    workspaceId,
    automationId: automation?.id ?? null,
    editing: automation !== null,
    form,
    confirm,
  });
  return (
    <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
      {dialog}
      <FormStatus error={error ?? saveError} className="mr-auto" />
      {automation && (
        <Button
          type="button"
          variant="ghost"
          disabled={deleting}
          onClick={() => {
            void (async () => {
              const ok = await confirm({
                title: "Delete this automation?",
                body: `“${automation.name}” stops and is removed.`,
                confirmLabel: "Delete",
                danger: true,
              });
              if (!ok) return;
              startDelete(async () => {
                await deleteAutomation(workspaceId, automation.id);
              });
            })();
          }}
        >
          Delete
        </Button>
      )}
      <Button
        type="submit"
        variant="primary"
        className="ml-auto"
        disabled={pending || checking}
        onClick={(event) => {
          event.preventDefault();
          void review();
        }}
      >
        {automation ? "Save changes" : "Create automation"}
      </Button>
    </footer>
  );
}
