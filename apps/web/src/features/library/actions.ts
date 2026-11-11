"use server";

import { refresh } from "next/cache";
import type { GithubTokenState, LibraryKind, McpTest } from "@/data/types";
import { core, coreOnce, seg } from "@/server/core";
import { attempt, type FormState } from "@/server/form";
import { requireAccess } from "@/server/access-guard";

const KINDS: LibraryKind[] = ["skill", "agent", "mcp", "plugin", "tool"];

function kindOf(value: string): LibraryKind | null {
  return (KINDS as string[]).includes(value) ? (value as LibraryKind) : null;
}

/** Where a workspace's own items of each kind live in the core. */
const ownedPath = { agent: "agents", mcp: "mcp", skill: "skills" } as const;
type OwnedKind = keyof typeof ownedPath;

export type ItemDraft = {
  name: string;
  title: string;
  summary: string;
  definition: Record<string, unknown>;
};

/** Create (itemId null) or edit an item of the global library, or — with a
 * workspace — one of that workspace's own agents, skills or MCP servers. */
export async function saveLibraryItem(
  kind: string,
  itemId: number | null,
  draft: ItemDraft,
  workspaceId?: string,
): Promise<FormState & { id?: number }> {
  await requireAccess();
  const k = kindOf(kind);
  if (!k || k === "tool") return { error: "Not allowed" };
  const body = {
    name: String(draft.name).trim().slice(0, 63),
    title: String(draft.title),
    summary: String(draft.summary),
    definition: draft.definition,
  };
  let id: number | undefined;
  const result = await attempt(async () => {
    if ((k === "agent" || k === "mcp" || k === "skill") && workspaceId) {
      const base = `/workspaces/${seg(workspaceId)}/${ownedPath[k]}`;
      if (itemId === null) {
        // A new member is a hire: its whole kit and model, the same rules as
        // every hire (made at once: his click is his Approve).
        // A hire carries an Idempotency-Key: a broken connection never hires twice.
        ({ id } =
          k === "agent"
            ? await coreOnce<{ id: number }>(
                `/workspaces/${seg(workspaceId)}/hires`,
                body,
              )
            : await core<{ id: number }>("POST", base, body));
      } else {
        await core("PUT", `${base}/${seg(itemId)}`, body);
        id = itemId;
      }
      return;
    }
    if (itemId === null) {
      ({ id } = await core<{ id: number }>("POST", `/library/${k}`, body));
    } else {
      await core("PUT", `/library/${k}/${seg(itemId)}`, body);
      id = itemId;
    }
  });
  refresh();
  return { ...result, id };
}

export async function duplicateLibraryItem(
  itemId: number,
  name: string,
  workspaceId?: string,
  kind?: LibraryKind,
): Promise<FormState> {
  await requireAccess();
  const body = { name: name.trim().slice(0, 63) };
  const result = await attempt(() =>
    kind === "skill" && workspaceId
      ? core(
          "POST",
          `/workspaces/${seg(workspaceId)}/skills/${seg(itemId)}/duplicate`,
          body,
        )
      : core("POST", `/library/items/${seg(itemId)}/duplicate`, body),
  );
  refresh();
  return result;
}

export async function deleteLibraryItem(
  itemId: number,
  workspaceId?: string,
  kind: OwnedKind = "agent",
): Promise<FormState> {
  await requireAccess();
  const where = ownedPath[kind];
  const result = await attempt(() =>
    workspaceId
      ? core(
          "DELETE",
          `/workspaces/${seg(workspaceId)}/${where}/${seg(itemId)}`,
        )
      : core("DELETE", `/library/items/${seg(itemId)}`),
  );
  refresh();
  return result;
}

/** Only when the owner asks: a copy of another project's agent, as this team's own. */
export async function copyAgentHere(
  workspaceId: string,
  itemId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `/workspaces/${seg(workspaceId)}/agents/copy`, { itemId }),
  );
  refresh();
  return result;
}

/** Connects to the MCP server and lists its tools (a workspace's own credential if given). */
export async function testMcp(
  itemId: number,
  workspaceId?: string,
): Promise<McpTest> {
  await requireAccess();
  try {
    return await core<McpTest>(
      "POST",
      workspaceId
        ? `/workspaces/${seg(workspaceId)}/mcp/${seg(itemId)}/test`
        : `/library/items/${seg(itemId)}/test`,
    );
  } catch (error) {
    return {
      ok: false,
      tools: [],
      error: error instanceof Error ? error.message : "Test failed",
    };
  }
}

/** A workspace turns an item on/off, with its own allowed tools and notes. */
export async function setConnector(
  workspaceId: string,
  itemId: number,
  on: boolean,
  allowedTools: string[],
  local: string,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("PUT", `/workspaces/${seg(workspaceId)}/connectors/${seg(itemId)}`, {
      on,
      allowedTools: allowedTools.slice(0, 200).map((t) => String(t)),
      local: String(local),
    }),
  );
  refresh();
  return result;
}

/** Only when the owner asks: an independent copy of another workspace's skill,
 * as this workspace's own. */
export async function copySkillHere(
  workspaceId: string,
  itemId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core("POST", `/workspaces/${seg(workspaceId)}/skills/copy`, { itemId }),
  );
  refresh();
  return result;
}

export type CopyableSkill = {
  id: number;
  title: string;
  name: string;
  workspace: string;
};

/** The other workspaces' skills, for "From another workspace" only. */
export async function listCopyableSkills(
  workspaceId: string,
): Promise<{ items: CopyableSkill[]; error: string | null }> {
  await requireAccess();
  try {
    return {
      items: await core<CopyableSkill[]>(
        "GET",
        `/workspaces/${seg(workspaceId)}/skills/copyable`,
      ),
      error: null,
    };
  } catch (error) {
    return {
      items: [],
      error: error instanceof Error ? error.message : "Failed",
    };
  }
}

export type McpSignIn = {
  status: "none" | "starting" | "waiting" | "done" | "error";
  url: string | null;
  error: string | null;
};

/** Starts the OAuth sign-in (Hermes runs it); returns the page to open. */
export async function startMcpSignIn(
  workspaceId: string,
  itemId: number,
): Promise<McpSignIn> {
  await requireAccess();
  try {
    return await core<McpSignIn>(
      "POST",
      `/workspaces/${seg(workspaceId)}/connectors/${seg(itemId)}/signin`,
    );
  } catch (error) {
    return {
      status: "error",
      url: null,
      error: error instanceof Error ? error.message : "Sign-in failed.",
    };
  }
}

export async function mcpSignInStatus(
  workspaceId: string,
  itemId: number,
): Promise<McpSignIn> {
  await requireAccess();
  const result = await core<McpSignIn>(
    "GET",
    `/workspaces/${seg(workspaceId)}/connectors/${seg(itemId)}/signin`,
  );
  if (result.status === "done") refresh();
  return result;
}

export async function mcpSignOut(
  workspaceId: string,
  itemId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "DELETE",
      `/workspaces/${seg(workspaceId)}/connectors/${seg(itemId)}/signin`,
    ),
  );
  refresh();
  return result;
}

/** A workspace's own credential for an MCP server (null removes it). */
export async function setConnectorSecret(
  workspaceId: string,
  itemId: number,
  value: string | null,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "PUT",
      `/workspaces/${seg(workspaceId)}/connectors/${seg(itemId)}/secret`,
      { value: value === null ? null : String(value).slice(0, 4000) },
    ),
  );
  refresh();
  return result;
}

export type FoundItem = {
  kind: LibraryKind;
  name: string;
  title: string;
  summary: string;
  origin: string;
  importable: boolean;
  locked: string | null;
  trust: string;
  inLibrary: boolean;
};

/** Where "on this machine" is asked: a workspace's own MCP servers and skills
 * are added from that workspace. */
function machinePath(k: LibraryKind, workspaceId?: string): string {
  if ((k === "mcp" || k === "skill") && workspaceId)
    return `/workspaces/${seg(workspaceId)}/${k === "mcp" ? "mcp" : "skills"}/machine`;
  return `/library/${k}/machine`;
}

/** Items this machine's Hermes has (skills, approved MCP catalog, plugins). */
export async function listOnThisMachine(
  kind: string,
  workspaceId?: string,
): Promise<{ items: FoundItem[]; error: string | null }> {
  await requireAccess();
  const k = kindOf(kind);
  if (!k) return { items: [], error: "Not allowed" };
  const path = machinePath(k, workspaceId);
  try {
    return {
      items: await core<FoundItem[]>("GET", path),
      error: null,
    };
  } catch (error) {
    return {
      items: [],
      error: error instanceof Error ? error.message : "Failed",
    };
  }
}

export async function importFromMachine(
  kind: string,
  origin: string,
  workspaceId?: string,
): Promise<FormState> {
  await requireAccess();
  const k = kindOf(kind);
  if (!k) return { error: "Not allowed" };
  const path = machinePath(k, workspaceId);
  const result = await attempt(() =>
    core("POST", path, { origin: origin.slice(0, 1000) }),
  );
  refresh();
  return result;
}

/** The skills hubs (Hermes's `hermes skills search`), for this workspace. */
export async function searchWeb(
  workspaceId: string,
  query: string,
): Promise<{ items: FoundItem[]; error: string | null }> {
  await requireAccess();
  try {
    return {
      items: await core<FoundItem[]>(
        "GET",
        `/workspaces/${seg(workspaceId)}/skills/web?q=${encodeURIComponent(query.slice(0, 100))}`,
      ),
      error: null,
    };
  } catch (error) {
    return {
      items: [],
      error: error instanceof Error ? error.message : "Failed",
    };
  }
}

export async function inspectSkill(
  workspaceId: string,
  identifier: string,
): Promise<{ preview: string; error: string | null }> {
  await requireAccess();
  try {
    const r = await core<{ preview: string }>(
      "POST",
      `/workspaces/${seg(workspaceId)}/skills/web/inspect`,
      { identifier: identifier.slice(0, 300) },
    );
    return { preview: r.preview, error: null };
  } catch (error) {
    return {
      preview: "",
      error: error instanceof Error ? error.message : "Failed",
    };
  }
}

/** Hermes's hub installs it into this workspace's skills (its scan runs).
 * `force` = Hermes's --force: only after its scan blocked it and the owner
 * chose Install anyway. */
export async function installSkill(
  workspaceId: string,
  identifier: string,
  force = false,
): Promise<{ scan: string; error: string | null; blocked: boolean }> {
  await requireAccess();
  const { CoreError } = await import("@/server/core");
  try {
    const r = await core<{ scan: string }>(
      "POST",
      `/workspaces/${seg(workspaceId)}/skills/web/install`,
      { identifier: identifier.slice(0, 300), force },
    );
    refresh();
    return { scan: r.scan, error: null, blocked: false };
  } catch (error) {
    return {
      scan: "",
      error: error instanceof Error ? error.message : "Failed",
      // 423: Hermes's security scan blocked it (the owner may install anyway).
      blocked: error instanceof CoreError && error.status === 423,
    };
  }
}

export async function applySkillUpdate(
  workspaceId: string,
  itemId: number,
): Promise<FormState> {
  await requireAccess();
  const result = await attempt(() =>
    core(
      "POST",
      `/workspaces/${seg(workspaceId)}/skills/${seg(itemId)}/update`,
    ),
  );
  refresh();
  return result;
}

/** A tool's service (from Hermes's list), set up once for every workspace. */
export async function setToolService(
  tool: string,
  provider: string,
  keys: Record<string, string>,
): Promise<FormState & { problems?: string[]; installing?: string | null }> {
  await requireAccess();
  let problems: string[] = [];
  let installing: string | null = null;
  const result = await attempt(async () => {
    const r = await core<{
      ok: boolean;
      problems: string[];
      installing: string | null;
    }>("PUT", `/library/tools/${seg(tool)}/service`, { provider, keys });
    problems = r.problems;
    installing = r.installing;
  });
  refresh();
  return { ...result, problems, installing };
}

type TokenResult = { state: GithubTokenState | null; error: string | null };

async function tokenCall(
  fn: () => Promise<GithubTokenState | null>,
): Promise<TokenResult> {
  const { CoreError } = await import("@/server/core");
  try {
    return { state: await fn(), error: null };
  } catch (error) {
    if (error instanceof CoreError) return { state: null, error: error.detail };
    return { state: null, error: "The engine didn't answer. Try again." };
  }
}

/** What Hermes's Skills Hub uses to read GitHub (its own GitHubAuth). */
export async function githubTokenStatus(): Promise<TokenResult> {
  await requireAccess();
  return tokenCall(() =>
    core<GithubTokenState>("GET", "/library/github-token"),
  );
}

/** Hermes saves it (GITHUB_TOKEN in its .env), only for the library's hub. */
export async function saveGithubToken(token: string): Promise<TokenResult> {
  await requireAccess();
  return tokenCall(() =>
    core<GithubTokenState>("PUT", "/library/github-token", {
      token: token.trim().slice(0, 400),
    }),
  );
}

export async function removeGithubToken(): Promise<TokenResult> {
  await requireAccess();
  return tokenCall(async () => {
    await core("DELETE", "/library/github-token");
    return core<GithubTokenState>("GET", "/library/github-token");
  });
}
