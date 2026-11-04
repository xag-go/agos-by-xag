"use client";

import { useCallback, useSyncExternalStore } from "react";

const PREFIX = "agos-draft:";
const MAX = 200_000;

// The drafts of this tab (also kept in localStorage, so they survive leaving the
// page, a reload or closing the browser). Memory first: blocked storage still works.
const memory = new Map<string, string>();
const listeners = new Set<() => void>();

function read(key: string): string {
  const known = memory.get(key);
  if (known !== undefined) return known;
  let saved = "";
  try {
    saved = window.localStorage.getItem(PREFIX + key) ?? "";
  } catch {
    saved = "";
  }
  memory.set(key, saved);
  return saved;
}

function write(key: string, value: string): void {
  memory.set(key, value);
  try {
    if (value.trim())
      window.localStorage.setItem(PREFIX + key, value.slice(0, MAX));
    else window.localStorage.removeItem(PREFIX + key);
  } catch {
    // storage full or blocked: the text still stays in the box
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Text being typed that survives leaving the page: kept in this browser under
 * `key` until it's sent. The server render shows an empty box (no clash).
 */
export function useDraft(key: string): {
  text: string;
  setText: (value: string) => void;
  clear: () => void;
} {
  const text = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => "",
  );
  const setText = useCallback(
    (value: string) => {
      write(key, value);
    },
    [key],
  );
  const clear = useCallback(() => {
    write(key, "");
  }, [key]);
  return { text, setText, clear };
}
