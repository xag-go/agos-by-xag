"use server";

import { headers } from "next/headers";
import { refresh } from "next/cache";
import type {
  AppFlow,
  ComposioAccount,
  ComposioAuthSetup,
  ComposioToolkit,
} from "@/data/types";
import { core, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const APP = /^[a-z0-9][a-z0-9_-]{0,62}$/;

/** Where the app's login page sends the browser back (this AGOS, same host). */
export async function callbackUrl(): Promise<string> {
  const h = await headers();
  const host = h.get("host") ?? "localhost";
  const proto = h.get("x-forwarded-proto") === "https" ? "https" : "http";
  return `${proto}://${host}/connectors/callback`;
}

/** Starts this workspace's own login: returns the app's login page to open. */
export async function connectApp(
  workspaceId: string,
  name: string,
): Promise<FormState & { url?: string }> {
  await requireAccess();
  if (!APP.test(name)) return { error: "Unknown app." };
  let flow: AppFlow | undefined;
  const result = await attempt(async () => {
    flow = await core<AppFlow>(
      "POST",
      `/workspaces/${seg(workspaceId)}/apps/${seg(name)}/connect`,
      { redirectUri: await callbackUrl() },
    );
  });
  if (result.error) return result;
  if (!flow || flow.status === "error")
    return { error: flow?.error ?? "The login didn't start." };
  if (!flow.url) return { error: "The app didn't give a login page." };
  return { error: null, url: flow.url };
}

/** Forgets this workspace's login (other workspaces keep theirs). */
export async function disconnectApp(
  workspaceId: string,
  name: string,
): Promise<FormState> {
  await requireAccess();
  if (!APP.test(name)) return { error: "Unknown app." };
  const result = await attempt(() =>
    core("DELETE", `/workspaces/${seg(workspaceId)}/apps/${seg(name)}/login`),
  );
  refresh();
  return result;
}

export async function setWorkspaceApp(
  workspaceId: string,
  name: string,
  on: boolean,
): Promise<FormState> {
  await requireAccess();
  if (!APP.test(name)) return { error: "Unknown app." };
  const result = await attempt(() =>
    core("PUT", `/workspaces/${seg(workspaceId)}/apps/${seg(name)}`, { on }),
  );
  refresh();
  return result;
}

/** This workspace's own Composio project key: Composio checks it, then Composio
 * is on here. */
export async function setWorkspaceComposioKey(
  workspaceId: string,
  value: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `/workspaces/${seg(workspaceId)}/composio/key`, {
      value: value.trim().slice(0, 500),
    }),
  );
  refresh();
  return result;
}

/** Composio's app list (for the picker). */
export async function composioToolkits(
  workspaceId: string,
): Promise<{ toolkits: ComposioToolkit[]; error: string | null }> {
  await requireAccess();
  try {
    return {
      toolkits: await core<ComposioToolkit[]>(
        "GET",
        `/workspaces/${seg(workspaceId)}/composio/toolkits`,
      ),
      error: null,
    };
  } catch (error) {
    return {
      toolkits: [],
      error: error instanceof Error ? error.message : "Composio didn't answer.",
    };
  }
}

/** This workspace's own Composio accounts (`fresh`: Refresh asks Composio now). */
export async function composioAccounts(
  workspaceId: string,
  fresh = false,
): Promise<{ accounts: ComposioAccount[]; error: string | null }> {
  await requireAccess();
  try {
    return {
      accounts: await core<ComposioAccount[]>(
        "GET",
        `/workspaces/${seg(workspaceId)}/composio/accounts${fresh ? "?fresh=true" : ""}`,
      ),
      error: null,
    };
  } catch (error) {
    return {
      accounts: [],
      error: error instanceof Error ? error.message : "Composio didn't answer.",
    };
  }
}

/** Composio's sign-in page for one app, for this workspace only. */
export async function composioLink(
  workspaceId: string,
  toolkit: string,
): Promise<FormState & { url?: string }> {
  await requireAccess();
  let url: string | undefined;
  const result = await attempt(async () => {
    ({ url } = await core<{ url: string }>(
      "POST",
      `/workspaces/${seg(workspaceId)}/composio/link`,
      { toolkit: toolkit.trim().slice(0, 63) },
    ));
  });
  return { ...result, url };
}

export async function removeComposioAccount(
  workspaceId: string,
  accountId: string,
): Promise<FormState> {
  await requireAccess();
  return attempt(() =>
    core(
      "DELETE",
      `/workspaces/${seg(workspaceId)}/composio/accounts/${seg(accountId)}`,
    ),
  );
}

/** The developer-app fields for an app Composio has no login app for. */
export async function composioAuthSetup(
  workspaceId: string,
  toolkit: string,
): Promise<{ setup: ComposioAuthSetup | null; error: string | null }> {
  await requireAccess();
  try {
    return {
      setup: await core<ComposioAuthSetup>(
        "GET",
        `/workspaces/${seg(workspaceId)}/composio/setup/${seg(toolkit)}`,
      ),
      error: null,
    };
  } catch (error) {
    return {
      setup: null,
      error: error instanceof Error ? error.message : "Composio didn't answer.",
    };
  }
}

/** Saves the owner's developer app for one app in this workspace's project. */
export async function composioSetUp(
  workspaceId: string,
  toolkit: string,
  values: Record<string, string>,
): Promise<FormState> {
  await requireAccess();
  return attempt(() =>
    core(
      "POST",
      `/workspaces/${seg(workspaceId)}/composio/setup/${seg(toolkit)}`,
      { values },
    ),
  );
}
