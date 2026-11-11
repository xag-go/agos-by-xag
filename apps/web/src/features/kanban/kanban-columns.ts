/** The owner's words for Hermes's Kanban statuses (presentation only). Which
 * columns exist and their order are Hermes's (the Kanban's `columns`, from the
 * core); a status not here shows with Hermes's own label and no hint. */
const statusWords: { status: string; label: string; hint: string }[] = [
  {
    status: "triage",
    label: "Triage",
    hint: "Rough ideas. The Co-Founder fleshes them out and splits them for the team.",
  },
  {
    status: "todo",
    label: "To do",
    hint: "Waits for the cards before it, or for a member.",
  },
  {
    status: "scheduled",
    label: "Scheduled",
    hint: "Waits for its time.",
  },
  {
    status: "ready",
    label: "Ready",
    hint: "Starts with the next round.",
  },
  {
    status: "running",
    label: "Running",
    hint: "A member is working on it.",
  },
  {
    status: "blocked",
    label: "Blocked",
    hint: "Waits for you or for a fix.",
  },
  {
    status: "review",
    label: "Review",
    hint: "Done, being checked by a reviewer.",
  },
  { status: "done", label: "Done", hint: "Finished." },
  {
    status: "archived",
    label: "Archived",
    hint: "Put away; kept with its history.",
  },
];

export function kanbanStatusLabel(status: string, hermes?: string): string {
  return (
    statusWords.find((c) => c.status === status)?.label ?? hermes ?? status
  );
}

/** How often Hermes's dispatcher runs, in the owner's words ("every minute"). */
function every(seconds: number): string {
  if (seconds % 60 === 0) {
    const minutes = seconds / 60;
    return minutes === 1 ? "every minute" : `every ${String(minutes)} minutes`;
  }
  return seconds === 1 ? "every second" : `every ${String(seconds)} seconds`;
}

/** Hermes's columns (status + its label) with the owner's words and hints.
 * `dispatchSeconds`: Hermes's dispatcher interval (the Kanban's, from the core). */
export function kanbanColumns(
  columns: { status: string; label: string }[],
  dispatchSeconds?: number | null,
): { status: string; label: string; hint: string }[] {
  return columns.map((c) => {
    const words = statusWords.find((w) => w.status === c.status);
    let hint = words?.hint ?? "";
    if (c.status === "ready" && dispatchSeconds)
      hint = `Starts with the next round (it runs ${every(dispatchSeconds)}).`;
    return {
      status: c.status,
      label: words?.label ?? c.label,
      hint,
    };
  });
}
