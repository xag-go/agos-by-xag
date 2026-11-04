// Idempotency-Key for the web's create / run calls to the core (ADR 0026): one key
// per owner action, invisible to him. The core runs a keyed call at most once and
// gives a repeat the first answer, so a call whose connection broke before any
// answer is safe to send again with the same key.

export const IDEMPOTENCY_HEADER = "Idempotency-Key";

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

/** fetch() throws a TypeError when the connection failed (refused, reset); a
 * timeout or an abort is a DOMException and is not sent again (the core may
 * still be working on it). */
function connectionFailed(error: unknown): boolean {
  return error instanceof TypeError;
}

/** `send()`, and once more when its connection failed before any answer. Only
 * for a call that carries an Idempotency-Key. */
export async function sendOnce<T>(
  send: () => Promise<T>,
  retries = 1,
): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await send();
    } catch (error) {
      if (attempt >= retries || !connectionFailed(error)) throw error;
    }
  }
}
