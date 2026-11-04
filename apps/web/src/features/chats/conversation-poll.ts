import type { ChatMessage, ChatTurn } from "@/data/types";

/**
 * GET a JSON view over XMLHttpRequest, stopped by `signal`.
 *
 * The chat long-poll uses this instead of fetch: browser extensions that wrap
 * window.fetch (Similarweb, for one) re-throw the AbortError of a stopped
 * request where no one catches it, and Next's dev overlay shows that as a
 * crash. Stopping an XHR never produces a rejected fetch, so nothing leaks.
 */
/**
 * Stops the live loop when the chat closes. Not an AbortController: aborting
 * one surfaces an "AbortError" in the dev overlay even though nothing failed.
 */
export class Stopper {
  stopped = false;
  private readonly callbacks = new Set<() => void>();
  onStop(callback: () => void): () => void {
    this.callbacks.add(callback);
    return () => {
      this.callbacks.delete(callback);
    };
  }
  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    for (const callback of this.callbacks) callback();
    this.callbacks.clear();
  }
}

export function getJson<T>(url: string, signal: Stopper): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    if (signal.stopped) {
      reject(new Error("stopped"));
      return;
    }
    const xhr = new XMLHttpRequest();
    const stop = () => {
      xhr.abort();
    };
    const done = signal.onStop(stop);
    xhr.open("GET", url);
    xhr.onload = () => {
      done();
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(String(xhr.status)));
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as T);
      } catch (error) {
        reject(error instanceof Error ? error : new Error("bad json"));
      }
    };
    xhr.onerror =
      xhr.onabort =
      xhr.ontimeout =
        () => {
          done();
          reject(new Error("request stopped or failed"));
        };
    xhr.send();
  });
}

/** Resolves at once while the tab is shown; while it is hidden, when it is
 * shown again (or the chat closes). */
export function untilShown(signal: Stopper): Promise<void> {
  return new Promise((resolve) => {
    if (signal.stopped || document.visibilityState !== "hidden") {
      resolve();
      return;
    }
    const shown = () => {
      if (document.visibilityState !== "hidden") finish();
    };
    const finish = () => {
      document.removeEventListener("visibilitychange", shown);
      forget();
      resolve();
    };
    const forget = signal.onStop(finish);
    document.addEventListener("visibilitychange", shown);
  });
}

export function sleep(ms: number, signal: Stopper): Promise<void> {
  return new Promise((resolve) => {
    if (signal.stopped) {
      resolve();
      return;
    }
    const forget = signal.onStop(() => {
      clearTimeout(timer);
      resolve();
    });
    const timer = setTimeout(() => {
      forget();
      resolve();
    }, ms);
  });
}

// ---- timeline -----------------------------------------------------------------

type Item =
  | { kind: "owner"; message: ChatMessage }
  | {
      kind: "agent";
      key: string;
      turn: ChatTurn | null;
      reply: ChatMessage | null;
    };

/** Messages in order; each reply keeps its turn (proposals, failure). A
 * stopped or failed turn without a reply sits after what it answered. */
export function timeline(messages: ChatMessage[], turns: ChatTurn[]): Item[] {
  const byReply = new Map(
    turns.filter((t) => t.replyId).map((t) => [t.replyId, t]),
  );
  const noReply = turns.filter(
    (t) => !t.replyId && (t.status === "stopped" || t.status === "failed"),
  );
  const items: Item[] = [];
  for (const m of messages) {
    if (m.from === "owner") {
      items.push({ kind: "owner", message: m });
    } else {
      items.push({
        kind: "agent",
        key: `r${String(m.id)}`,
        turn: byReply.get(m.id) ?? null,
        reply: m,
      });
    }
    for (const t of noReply) {
      if (t.askedUpTo === m.id) {
        items.push({
          kind: "agent",
          key: `n${String(t.id)}`,
          turn: t,
          reply: null,
        });
      }
    }
  }
  return items;
}
