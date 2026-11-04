import "server-only";
import { refresh } from "next/cache";
import { requireAccess } from "./access-guard";
import { CoreError } from "./core";
import { attempt, type FormState } from "./form";

// The two result shapes every server action returns, and the one wrapper for
// each: `act` for a change made from a form or a button (FormState, then the
// page refreshes), `carry` for a call whose answer the card shows (Answer<T>).
// Both check the owner first; a refusal from the core becomes the error text.
// Not a "use server" file: these are helpers, never action endpoints.

/** What a card's call returns: the core's answer, or why it was refused. */
export type Answer<T> = { ok: true; data: T } | { ok: false; error: string };

/** Owner check, the core call, then the page's data read again. */
export async function act(job: () => Promise<unknown>): Promise<FormState> {
  await requireAccess();
  const result = await attempt(job);
  refresh();
  return result;
}

/** Owner check and the core call; a core refusal comes back as `error`. */
export async function carry<T>(work: () => Promise<T>): Promise<Answer<T>> {
  await requireAccess();
  try {
    return { ok: true, data: await work() };
  } catch (error) {
    if (!(error instanceof CoreError)) throw error;
    return { ok: false, error: error.detail };
  }
}
