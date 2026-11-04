"use server";

import type { ModelSelection } from "@agos/core";
import { refresh } from "next/cache";
import { core } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

export async function saveUsagePrefs(prefs: {
  enabled: boolean;
  warnAt: number;
  pauseAt: number;
}): Promise<FormState> {
  await requireAccess();
  const clamp = (n: number) => Math.min(100, Math.max(1, Math.round(n || 0)));
  const result = await attempt(() =>
    core("PUT", "/preferences/usage", {
      enabled: Boolean(prefs.enabled),
      warnAt: clamp(prefs.warnAt),
      pauseAt: clamp(prefs.pauseAt),
    }),
  );
  refresh();
  return result;
}

export async function saveNotifications(
  rules: Record<string, string>,
): Promise<FormState> {
  await requireAccess();
  const allowed = new Set(["instant", "batched", "silent"]);
  const clean = Object.fromEntries(
    Object.entries(rules).filter(([, v]) => allowed.has(v)),
  );
  const result = await attempt(() =>
    core("PUT", "/preferences/notifications", { rules: clean }),
  );
  refresh();
  return result;
}

/** The owner's order of the workspace tabs (the same in every workspace). */
export async function saveTabsOrder(order: string[]): Promise<void> {
  await requireAccess();
  await core("PUT", "/preferences/tabs", { order: order.slice(0, 20) });
  refresh();
}

/** The owner's order of the workspaces (dragged on the rail). */
export async function saveWorkspaceOrder(order: string[]): Promise<void> {
  await requireAccess();
  await core("PUT", "/preferences/workspace-order", {
    order: order.slice(0, 500),
  });
  refresh();
}

/** null: Hermes's own default (a count) or Hermes's own cap (members at once). */
export type HermesLimits = {
  loopOn: boolean;
  sameError: number | null;
  sameToolFailing: number | null;
  noProgress: number | null;
  timeLimitMinutes: number | null;
  membersAtOnce: number | null;
};

/** Written straight into every workspace's Hermes (AGOS keeps no copy). */
export async function saveHermesLimits(
  limits: HermesLimits,
): Promise<FormState> {
  await requireAccess();
  const clamp = (n: number | null, lo: number, hi: number) =>
    n === null || !Number.isFinite(n)
      ? null
      : Math.max(lo, Math.min(hi, Math.round(n)));
  const result = await attempt(() =>
    core("PUT", "/preferences/hermes-limits", {
      loopOn: limits.loopOn,
      sameError: clamp(limits.sameError, 2, 100),
      sameToolFailing: clamp(limits.sameToolFailing, 2, 100),
      noProgress: clamp(limits.noProgress, 2, 100),
      timeLimitMinutes: clamp(limits.timeLimitMinutes, 1, 525_600),
      membersAtOnce: clamp(limits.membersAtOnce, 1, 20),
    }),
  );
  refresh();
  return result;
}

export async function saveCofounderActionsMode(
  mode: "direct" | "ask",
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", "/cofounder-actions/mode", {
      mode: mode === "ask" ? "ask" : "direct",
    }),
  );
  refresh();
  return result;
}

/** His name ("" = his account's), one for every workspace: the Founder's box,
 * his cards, his Inbox and phone notices, the Co-Founder's prompt. */
export async function saveOwnerName(name: string): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", "/preferences/owner-name", { name: name.trim().slice(0, 200) }),
  );
  refresh();
  return result;
}

/** The owner's timezone ("" = not set): the clock times he gives the agents. */
export async function saveTimezone(timezone: string): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", "/preferences/timezone", { timezone: timezone.trim() }),
  );
  refresh();
  return result;
}

/** Hermes key → seconds (only what he changed), and the model that watches
 * videos: written with Hermes's own `hermes config set` into every profile of
 * every workspace (AGOS keeps no copy). */
export async function saveHermesTimeLimits(
  values: Record<string, number>,
): Promise<FormState> {
  await requireAccess();
  const clean = Object.fromEntries(
    Object.entries(values)
      .filter(([key, v]) => /^[A-Za-z0-9_.]+$/.test(key) && Number.isFinite(v))
      .map(([key, v]) => [
        key,
        Math.max(0, Math.min(31_536_000, Math.round(v))),
      ]),
  );
  const result = await attempt(() =>
    core("PUT", "/preferences/hermes-time-limits", {
      values: clean,
    }),
  );
  refresh();
  return result;
}

/** Hermes's helper (auxiliary) models and its image mode: Hermes's own
 * `config set` / `config unset` into its managed settings (AGOS keeps no copy).
 * `picks`: a model picker choice per task (null: "Same as the main model"),
 * turned into Hermes's provider name and model by the core. */
export async function saveHermesHelperModels(
  sets: Record<string, string>,
  unsets: string[],
  picks: Record<string, ModelSelection | null> = {},
): Promise<FormState> {
  await requireAccess();
  const key = /^[A-Za-z0-9_.]+$/;
  const result = await attempt(() =>
    core("PUT", "/preferences/hermes-helper-models", {
      sets: Object.fromEntries(
        Object.entries(sets).filter(([k, v]) => key.test(k) && v.length < 600),
      ),
      unsets: unsets.filter((k) => key.test(k)),
      picks: Object.fromEntries(
        Object.entries(picks)
          .filter(([task]) => /^[a-z0-9_]+$/.test(task))
          .map(([task, pick]) => [
            task,
            pick && {
              provider: pick.provider,
              mode: pick.mode,
              model: pick.model,
            },
          ]),
      ),
    }),
  );
  refresh();
  return result;
}

/** Who hears the owner's voice notes: Hermes's stt.provider and that provider's
 * model (empty: Hermes's default for it), one value for every workspace in
 * Hermes's managed settings (AGOS keeps no copy). */
export async function saveHermesVoice(
  provider: string,
  model: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", "/preferences/hermes-voice", {
      provider: provider.trim(),
      model: model.trim(),
    }),
  );
  refresh();
  return result;
}

/** The fallback models in the owner's order: written with Hermes's own `hermes
 * config set fallback_providers` into every profile of every workspace (AGOS
 * keeps no copy). A picker choice comes with its mode; an entry kept as Hermes
 * has it comes with Hermes's own provider name and no mode. */
export async function saveHermesFallback(
  chain: {
    provider: string;
    mode?: "cli" | "api";
    model: string;
    baseUrl?: string;
  }[],
): Promise<FormState> {
  await requireAccess();
  const clean = chain
    .filter((e) => e.provider.trim() && e.model.trim())
    .map((e) => ({
      provider: e.provider.trim(),
      ...(e.mode === "cli" || e.mode === "api" ? { mode: e.mode } : {}),
      model: e.model.trim(),
      ...(e.baseUrl?.trim() ? { baseUrl: e.baseUrl.trim() } : {}),
    }));
  const result = await attempt(() =>
    core("PUT", "/preferences/hermes-fallback", { chain: clean }),
  );
  refresh();
  return result;
}
