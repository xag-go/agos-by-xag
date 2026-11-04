import "server-only";
import fs from "node:fs";
import { webEnv } from "./env";
import { IDEMPOTENCY_HEADER, newIdempotencyKey, sendOnce } from "./idempotency";

// The web app keeps no data: every read and change goes to the Python core
// (ADR 0009), with the internal token that proves the call comes from here.

export class CoreError extends Error {
  constructor(
    readonly status: number,
    /** Safe to show to the owner. */
    readonly detail: string,
  ) {
    super(detail);
    this.name = "CoreError";
  }
}

let token: string | undefined;

function internalToken(): string {
  token ??= fs.readFileSync(webEnv().AGOS_INTERNAL_TOKEN_FILE, "utf8").trim();
  return token;
}

function detailOf(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: a list of problems.
    if (Array.isArray(detail)) return "Some fields are missing or invalid.";
  }
  return status >= 500
    ? "The core had a problem. Try again."
    : "The request was refused.";
}

type Method = "GET" | "POST" | "PUT" | "DELETE";

export async function core<T>(
  method: Method,
  path: string,
  body?: unknown,
  /** How long to wait for the core (a Hermes run can take minutes). */
  timeoutMs = 30_000,
): Promise<T> {
  return request<T>(
    method,
    path,
    body === undefined ? undefined : JSON.stringify(body),
    body === undefined ? undefined : "application/json",
    timeoutMs,
  );
}

/** Like `core`, for a create / run action of the owner: the call carries a new
 * Idempotency-Key, so the core runs it at most once, and a connection that broke
 * before any answer is sent once more with the same key (ADR 0026). */
export async function coreOnce<T>(
  path: string,
  body?: unknown,
  timeoutMs = 30_000,
): Promise<T> {
  const key = newIdempotencyKey();
  return sendOnce(() =>
    request<T>(
      "POST",
      path,
      body === undefined ? undefined : JSON.stringify(body),
      body === undefined ? undefined : "application/json",
      timeoutMs,
      { [IDEMPOTENCY_HEADER]: key },
    ),
  );
}

/** Like `core`, with a file's bytes as the body (the core reads its type from
 * the bytes: the workspace icon). */
export async function coreUpload<T>(
  method: Method,
  path: string,
  file: Blob,
): Promise<T> {
  return request<T>(
    method,
    path,
    file,
    file.type || "application/octet-stream",
  );
}

async function request<T>(
  method: Method,
  path: string,
  body: BodyInit | undefined,
  contentType: string | undefined,
  timeoutMs = 30_000,
  extraHeaders: Record<string, string> = {},
): Promise<T> {
  const response = await fetch(new URL(path, webEnv().AGOS_CORE_URL), {
    method,
    headers: {
      ...extraHeaders,
      "x-agos-internal": internalToken(),
      ...(contentType === undefined ? {} : { "content-type": contentType }),
    },
    body,
    cache: "no-store",
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (response.status === 401) token = undefined; // re-read if the core rotated it
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      // Not JSON (e.g. a plain "Internal Server Error" from the core): never
      // crash the page on it; an error status becomes a readable CoreError.
      if (response.ok)
        throw new CoreError(502, "The core sent an answer the app can't read.");
      parsed = null;
    }
  }
  if (!response.ok)
    throw new CoreError(response.status, detailOf(parsed, response.status));
  return parsed as T;
}

/** The core's raw answer (status, headers, body left as a stream), for route
 * handlers that pass a file or a relayed answer straight on. Same token and
 * 401 re-read as `core`; no timeout, so a download streams as long as it takes. */
export async function coreStream(
  path: string,
  init: {
    method?: Method;
    headers?: Record<string, string>;
    body?: BodyInit;
  } = {},
): Promise<Response> {
  const response = await fetch(new URL(path, webEnv().AGOS_CORE_URL), {
    method: init.method ?? "GET",
    headers: { ...init.headers, "x-agos-internal": internalToken() },
    body: init.body,
    cache: "no-store",
  });
  if (response.status === 401) token = undefined; // re-read if the core rotated it
  return response;
}

/** Like `core`, but a 404 becomes null (for pages that call notFound()). */
export async function coreOrNull<T>(path: string): Promise<T | null> {
  try {
    return await core<T>("GET", path);
  } catch (error) {
    if (error instanceof CoreError && error.status === 404) return null;
    throw error;
  }
}

/** Encodes one path segment (ids come from URLs). */
export const seg = (value: string | number) =>
  encodeURIComponent(String(value));
