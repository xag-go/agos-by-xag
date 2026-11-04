import "server-only";

// The header copy the route handlers that pass a core answer on (files, icon,
// export) share around `coreStream`. It owns no fetch and no token; those stay
// in core.ts.

/** Copies the named headers that the core's answer carries onto `into`. */
export function copyHeaders(
  from: Headers,
  keys: readonly string[],
  into: Headers,
): Headers {
  for (const key of keys) {
    const value = from.get(key);
    if (value) into.set(key, value);
  }
  return into;
}

/** The headers a downloaded file keeps from the core. */
export const FILE_HEADERS = [
  "content-type",
  "content-length",
  "content-disposition",
] as const;
