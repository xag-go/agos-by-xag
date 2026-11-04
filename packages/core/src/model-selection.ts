import { z } from "zod";

/**
 * How the app talks to a provider:
 * - "cli": drives the provider's official CLI, which the owner logged into
 *   themselves (subscription). The app never reads or stores those tokens.
 * - "api": calls the provider's API with a key stored encrypted by the app.
 */
export const providerModeSchema = z.enum(["cli", "api"]);
export type ProviderMode = z.infer<typeof providerModeSchema>;

/**
 * Provider ids are open strings (e.g. "claude", "openai", "gemini") so a new
 * provider is added by registering an adapter, not by editing core.
 */
export const providerIdSchema = z
  .string()
  .regex(/^[a-z][a-z0-9-]{1,31}$/, "invalid provider id");

/**
 * Effort levels differ per provider and model ("low" … "max" for Claude), so
 * core only checks the shape; the provider's model catalog checks the value.
 */
export const effortSchema = z.string().regex(/^[a-z]{1,16}$/, "invalid effort");

/**
 * The model a workspace, task, sub-task or chat runs on. Always chosen by the
 * owner (UI or `/model` command) — the system never picks or switches models
 * by itself.
 */
export const modelSelectionSchema = z
  .object({
    provider: providerIdSchema,
    mode: providerModeSchema,
    model: z.string().min(1).max(128),
    effort: effortSchema,
  })
  .strict();
export type ModelSelection = z.infer<typeof modelSelectionSchema>;
