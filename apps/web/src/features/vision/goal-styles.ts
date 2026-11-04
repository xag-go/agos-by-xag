/** The goal parts' shared class names: small controls, section labels, step chips, a project card. */
export const small = "h-8 text-xs";
export const sectionLabel =
  "text-xs font-medium tracking-wide text-ink-3 uppercase";

export const ghost =
  "!h-8 gap-1.5 !rounded-9 !px-2.5 !text-12.5 font-semibold text-ink-2 !shadow-none [&_svg]:size-[13px]";

export const STEP: Record<string, { label: string; tone: string }> = {
  running: { label: "Running", tone: "bg-accent-soft text-accent" },
  review: {
    label: "Review",
    tone: "bg-review-soft text-review-ink",
  },
  blocked: { label: "Blocked", tone: "bg-danger-soft text-danger" },
  done: { label: "Done", tone: "bg-success-soft text-success" },
};
export const TODO = { label: "To do", tone: "bg-sunken text-ink-3" };

/** A project card's own frame (its <li>, given by the folder list). */
export const PROJECT_CARD =
  "relative flex min-h-[132px] min-w-0 scroll-mt-6 flex-col gap-3 rounded-2xl bg-goal-mini px-[18px] pt-4 pb-3.5 shadow-inset-goal-mini transition-shadow duration-150 has-[a.goal-open:hover]:shadow-inset-line-strong";
