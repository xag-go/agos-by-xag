/**
 * A light hint while the owner types a schedule: only that there is one, and
 * the form's length. The real check is Hermes's own schedule parser
 * (cron/jobs.py parse_schedule: 5-6 cron fields, "30m", "every monday 9am"),
 * which core runs when the automation is saved; its answer is shown then. The
 * web never judges the fields itself, so it can't refuse what Hermes takes.
 */
export function scheduleHint(schedule: string): string | null {
  const text = schedule.trim();
  if (!text) return "say when it runs";
  if (text.length > 100) return "keep it under 100 characters";
  return null;
}
