import "server-only";
import path from "node:path";
import { z } from "zod";
import { dataDir } from "./data-dir";

const envSchema = z.object({
  /** Where the Python core listens (internal network). */
  AGOS_CORE_URL: z.url().default("http://127.0.0.1:8766"),
  /** File holding the token the core accepts from this app (the core writes
   * it at <data folder>/system/internal.token on start). */
  AGOS_INTERNAL_TOKEN_FILE: z
    .string()
    .min(1)
    .refine((file) => path.isAbsolute(file), "must be an absolute path")
    .default(() => path.join(dataDir(), "system", "internal.token")),
});

export type WebEnv = z.infer<typeof envSchema>;

let cached: WebEnv | undefined;

/** Fails loudly on a missing or invalid config; prints names, never values. */
export function webEnv(): WebEnv {
  if (cached) return cached;
  const result = envSchema.safeParse(process.env);
  if (!result.success) {
    const issues = result.error.issues
      .map((issue) => `  - ${issue.path.join(".")}: ${issue.message}`)
      .join("\n");
    throw new Error(`Invalid environment configuration:\n${issues}`);
  }
  cached = result.data;
  return cached;
}
