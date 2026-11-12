import type { components } from "./core-api";
import type {
  AutonomyView,
  Learned,
} from "@/features/proactive/proactive-settings";
import "server-only";
import { cache } from "react";
import { core, coreOrNull, seg } from "@/server/core";
import type {
  Artifacts,
  Founder,
  Inbox,
  ReviewSettings,
  KanbanBoard,
  KanbanCardDetail,
  Proposal,
  Team,
  ActivityItem,
  Automation,
  AutomationCost,
  AutomationEvent,
  AutomationRevision,
  AutomationRun,
  AutomationRunGroup,
  FolderKind,
  ListFolder,
  Heartbeat,
  WorkHours,
  HiresAsked,
  Scorecards,
  SkillGrowth,
  TicketPreset,
  WorkspaceIdentity,
  BoardCounters,
  CatalogProvider,
  ConnectorCatalogRow,
  Chat,
  AccountLimitView,
  BackupStatus,
  ChannelConnection,
  ChatAddress,
  Connector,
  WorkspaceApp,
  NotificationRule,
  PushDevice,
  RemoteAccess,
  TabsOrder,
  UsagePrefs,
  LibraryItem,
  LibraryKind,
  SkillTests,
  SkillVersion,
  ProviderConnection,
  TrashedWorkspace,
  VisionView,
  SearchPage,
  StatusPage,
  PipelineRule,
  CardService,
  McpToken,
  Workspace,
  WorkspaceFolder,
} from "./types";

// The only entry point pages use to read data — all from the Python core.
// Reads that the layouts, both sidebars and the page all make are wrapped in
// React's cache(): one core call per server render instead of one per caller
// (Next doesn't dedupe these fetches because they carry a timeout signal).
// Outside a render (server actions, route handlers) cache() just calls through,
// so a read after a change is always fresh.

/** Parses a positive integer id from a URL, or null. */
export function parseId(value: unknown): number | null {
  if (typeof value !== "string" || !/^\d{1,12}$/.test(value)) return null;
  const n = Number(value);
  return n > 0 ? n : null;
}

const ws = (id: string) => `/workspaces/${seg(id)}`;

export const getWorkspaces = cache(() =>
  core<Workspace[]>("GET", "/workspaces"),
);
export const getArchivedWorkspaces = () =>
  core<Workspace[]>("GET", "/workspaces-archived");
export const getTrashedWorkspaces = () =>
  core<TrashedWorkspace[]>("GET", "/trash");
export const getWorkspace = cache((id: string) =>
  coreOrNull<Workspace>(ws(id)),
);
export const getWorkspaceFolders = (id: string) =>
  core<WorkspaceFolder[]>("GET", `${ws(id)}/folders`);
/** The workspace's Kanban (Hermes's Kanban); null when Hermes doesn't answer. */
export async function getKanban(id: string): Promise<KanbanBoard | null> {
  try {
    return await core<KanbanBoard>("GET", `${ws(id)}/kanban`);
  } catch {
    return null;
  }
}
export const getKanbanCard = (id: string, cardId: string) =>
  coreOrNull<KanbanCardDetail>(`${ws(id)}/kanban/${seg(cardId)}`);
/** The workspace's card labels (Settings → Labels; the Kanban has them too). */
export const getLabels = (id: string) =>
  core<components["schemas"]["Label"][]>("GET", `${ws(id)}/labels`);
export const getReviewSettings = (id: string) =>
  coreOrNull<ReviewSettings>(`${ws(id)}/review-settings`);
export const getBoardCounters = (id: string) =>
  core<BoardCounters>("GET", `${ws(id)}/counters`);
export const getChats = (id: string) => core<Chat[]>("GET", `${ws(id)}/chats`);
export const getTeam = (id: string) => core<Team>("GET", `${ws(id)}/workers`);
/** The owner's "Suggest hires" card still open on Hermes's Kanban (Hierarchy). */
export const getHiresAsked = (id: string) =>
  core<HiresAsked>("GET", `${ws(id)}/team/suggest-hires`);
/** The Vision page in one read: the plan with its rollup, today, the rhythm. */
export const getVision = (id: string) =>
  core<VisionView>("GET", `${ws(id)}/vision`);
/** The workspace search (every type, best first) in one read. */
export const getSearch = (id: string, q: string, types: string[]) => {
  const params = new URLSearchParams({ q });
  if (types.length) params.set("types", types.join(","));
  return core<SearchPage>("GET", `${ws(id)}/search?${params.toString()}`);
};
/** The Status page in one read: the cards, their summaries and revisions. */
export const getStatusCards = (id: string) =>
  core<StatusPage>("GET", `${ws(id)}/status-cards`);
/** Everything waiting for the owner: proposals, card asks, card questions. */
export const getInbox = (id: string) => core<Inbox>("GET", `${ws(id)}/inbox`);
/** The proposals waiting (the Team page shows pending hires in their place). */
export const getProposals = (id: string) =>
  core<Proposal[]>("GET", `${ws(id)}/proposals`);
/** The Office page's data in one read (team, Hermes's Kanban, looks) and its
 * fingerprint, so the page and its live refresh compare the same thing. */
export const getOfficeView = (id: string) =>
  core<components["schemas"]["OfficeView"]>("GET", `${ws(id)}/office/view`);
/** The Office's fingerprint, kept by the core while none of the stores it comes
 * from moved: what its live refresh asks every 2 s. */
export const getOfficeStamp = (id: string) =>
  core<components["schemas"]["OfficeStamp"]>("GET", `${ws(id)}/office/stamp`);
/** The Dashboard: this workspace's own channels, usage, automations, chats. */
export const getWorkspaceOverview = (id: string) =>
  core<components["schemas"]["WorkspaceOverview"]>("GET", `${ws(id)}/overview`);
/** This workspace's own agents (its team), nobody else's. */
export const getWorkspaceAgents = (id: string) =>
  core<LibraryItem[]>("GET", `${ws(id)}/agents`);
export const getCopyableAgents = (id: string) =>
  core<{ id: number; title: string; name: string; workspace: string }[]>(
    "GET",
    `${ws(id)}/agents/copyable`,
  );
export const getChat = (id: string, chatId: number) =>
  coreOrNull<Chat>(`${ws(id)}/chats/${seg(chatId)}`);
export const getIdentity = (id: string) =>
  core<WorkspaceIdentity>("GET", `${ws(id)}/identity`);
export type Ongoing = components["schemas"]["Ongoing"];
/** Hermes's own settings for a workspace (read from its Hermes, never kept in AGOS). */
export const getHermesSettings = (id: string) =>
  core<{ values: Record<string, string>; defaults: Record<string, string> }>(
    "GET",
    `${ws(id)}/hermes-settings`,
  );
export const getOngoing = (id: string) =>
  core<Ongoing>("GET", `${ws(id)}/ongoing`);
export const getAutomations = (id: string) =>
  core<Automation[]>("GET", `${ws(id)}/automations`);
/** The folders of one list (Automations, Skills, Projects), each with its items' ids. */
export const getFolders = (id: string, kind: FolderKind) =>
  core<ListFolder[]>("GET", `${ws(id)}/list-folders?kind=${kind}`);
export const getAutomationRuns = (id: string, automationId: number) =>
  core<AutomationRun[]>(
    "GET",
    `${ws(id)}/automations/${seg(automationId)}/runs`,
  );
export const getAutomationEvents = (id: string, automationId: number) =>
  core<AutomationEvent[]>(
    "GET",
    `${ws(id)}/automations/${seg(automationId)}/events`,
  );
export const getHooksAddress = async () =>
  (await core<{ publicUrl: string }>("GET", "/settings/hooks")).publicUrl;
export const getAutomation = (id: string, automationId: number) =>
  coreOrNull<Automation>(`${ws(id)}/automations/${seg(automationId)}`);
/** The Revisions tab: every saved version with its diff (one read). */
export const getAutomationRevisions = (id: string, automationId: number) =>
  core<AutomationRevision[]>(
    "GET",
    `${ws(id)}/automations/${seg(automationId)}/revisions`,
  );
/** The run history: each run's cards, grouped by run id, with its status. */
export const getAutomationRunHistory = (id: string) =>
  core<AutomationRunGroup[]>("GET", `${ws(id)}/automation-runs`);
/** What each automation's runs used this month and last month (UTC). */
export const getAutomationCosts = (id: string) =>
  core<AutomationCost[]>("GET", `${ws(id)}/automation-costs`);
/** The ticket on-ramp presets (Linear / Jira / Asana / GitHub). */
export const getTicketPresets = () =>
  core<TicketPreset[]>("GET", "/ticket-presets");
/** Every member's heartbeat and the Co-Founder's (agent ""), last run included. */
export const getHeartbeats = (id: string) =>
  core<Heartbeat[]>("GET", `${ws(id)}/heartbeats`);
/** Work hours: the week, who stays on today, each agent's state now. */
export const getWorkHours = (id: string) =>
  coreOrNull<WorkHours>(`${ws(id)}/work-hours`);
/** The Founder's box: the owner himself, his tasks on Hermes's Kanban. */
export const getFounder = (id: string) =>
  core<Founder>("GET", `${ws(id)}/founder`);
/** His name (Settings → General), one for every workspace. */
export const getOwnerName = () =>
  core<{ name: string }>("GET", "/preferences/owner-name");
/** This week's per-member scorecard, derived from Hermes's Kanban (Step 63). */
export const getScorecards = (id: string) =>
  core<Scorecards>("GET", `${ws(id)}/scorecards`);
/** Find-skills requests, the weekly skill review and its candidates (Step 63). */
export const getSkillGrowth = (id: string) =>
  core<SkillGrowth>("GET", `${ws(id)}/skill-growth`);
export const getActivity = (id: string) =>
  core<ActivityItem[]>("GET", `${ws(id)}/activity`);

// ---- Later steps: empty or demo until they are built ----

/** Connectors arrive with Global Settings logic (step 12). */
export const getConnectors = (id: string) =>
  core<Connector[]>("GET", `${ws(id)}/connectors`);
/** Apps of one workspace: the catalog, its own logins and what is on. */
export const getWorkspaceApps = (id: string) =>
  core<WorkspaceApp[]>("GET", `${ws(id)}/apps`);
/** This workspace's own MCP servers (made and seen only here). */
export const getWorkspaceMcp = (id: string) =>
  core<LibraryItem[]>("GET", `${ws(id)}/mcp`);
export const getWorkspaceSkills = (id: string) =>
  core<LibraryItem[]>("GET", `${ws(id)}/skills`);
/** A workspace's skills that have a newer copy (Hermes's hub, this machine). */
export async function getSkillUpdates(id: string) {
  try {
    return await core<{ itemId: number; hasUpdate: boolean; detail: string }[]>(
      "GET",
      `${ws(id)}/skills/updates`,
    );
  } catch {
    return [];
  }
}
/** Skill Studio (one read per tab): a skill's versions, the diff between two, its tests. */
export const getSkillVersions = (id: string, itemId: number) =>
  core<SkillVersion[]>("GET", `${ws(id)}/skills/${seg(itemId)}/versions`);
export const getSkillTests = (id: string, itemId: number) =>
  core<SkillTests>("GET", `${ws(id)}/skills/${seg(itemId)}/tests`);
export const getConnectorCatalog = () =>
  core<ConnectorCatalogRow[]>("GET", "/connectors/catalog");

export const getLibrary = (kind?: LibraryKind) =>
  core<LibraryItem[]>(
    "GET",
    kind ? `/library?kind=${encodeURIComponent(kind)}` : "/library",
  );

export async function getAccountLimits(): Promise<AccountLimitView[]> {
  try {
    return await core<AccountLimitView[]>("GET", "/usage/limits");
  } catch {
    return [];
  }
}
/** This workspace's own Telegram bots (never another workspace's). */
export async function getWorkspaceBots(
  workspaceId: string,
): Promise<ChannelConnection[]> {
  try {
    return await core<ChannelConnection[]>(
      "GET",
      `/workspaces/${seg(workspaceId)}/bots`,
    );
  } catch {
    return [];
  }
}

export const getChatAddresses = (id: string, chatId: number) =>
  core<ChatAddress[]>("GET", `${ws(id)}/chats/${seg(chatId)}/addresses`);
export const getBackupStatus = () => core<BackupStatus>("GET", "/backups");

/** Settings → General → Labs: the feature flags (core: actions/flags.py). */
export type FeatureFlag = components["schemas"]["FlagView"];
export const getFlags = () => core<FeatureFlag[]>("GET", "/flags");

export type ErrorIssues = components["schemas"]["ErrorIssues"];
export type ErrorIssue = components["schemas"]["ErrorIssue"];
/** Settings → Errors: every issue, open and fixed (the page filters). */
export const getErrorIssues = () =>
  core<ErrorIssues>("GET", "/errors?status=all");
export const getUsagePrefs = () =>
  core<UsagePrefs>("GET", "/preferences/usage");
export const getTabsOrder = cache(() =>
  core<TabsOrder>("GET", "/preferences/tabs"),
);
export const getOwnerRules = () =>
  core<
    {
      id: number;
      text: string;
      fromWorkspace?: string | null;
      createdAt: string;
    }[]
  >("GET", "/owner-rules");
export type BrainMethod = {
  id: number;
  text: string;
  fromWorkspace?: string | null;
  createdAt: string;
  usedHere: boolean;
};
export const getBrain = () => core<BrainMethod[]>("GET", "/brain");
export const getWorkspaceBrain = (id: string) =>
  core<BrainMethod[]>("GET", `/workspaces/${seg(id)}/brain`);
export const getOwnerTimezone = () =>
  core<{ timezone: string }>("GET", "/preferences/timezone");
export type HermesLimitsShown = components["schemas"]["HermesLimitsOut"];
export const getHermesLimits = () =>
  core<HermesLimitsShown>("GET", "/preferences/hermes-limits");
export type HermesTimeLimits = components["schemas"]["HermesTimeLimits"];
export const getHermesTimeLimits = () =>
  core<HermesTimeLimits>("GET", "/preferences/hermes-time-limits");
export type HermesHelperModels = components["schemas"]["HermesHelperModels"];
export const getHermesHelperModels = () =>
  core<HermesHelperModels>("GET", "/preferences/hermes-helper-models");
export type HermesFallback = components["schemas"]["HermesFallback"];
export const getHermesFallback = () =>
  core<HermesFallback>("GET", "/preferences/hermes-fallback");
export type HermesVoice = components["schemas"]["HermesVoice"];
export const getHermesVoice = () =>
  core<HermesVoice>("GET", "/preferences/hermes-voice");
export type HermesHealth = components["schemas"]["HermesHealth"];
export type SecretsCheck = components["schemas"]["SecretsCheck"];
export type AccessLists = components["schemas"]["AccessLists"];
export type KeyPools = components["schemas"]["KeyPools"];
export const getKeyPools = async (): Promise<KeyPools | null> => {
  try {
    return await core<KeyPools>("GET", "/models/key-pools");
  } catch {
    return null;
  }
};
export type ToolKeys = components["schemas"]["ToolKeys"];
/** Workspace → Keys: the keys Hermes hands to this workspace's tools (null:
 * Hermes isn't answering). Never holds a key, only its name and last four. */
export const getToolKeys = async (
  workspaceId: string,
): Promise<ToolKeys | null> => {
  try {
    return await core<ToolKeys>("GET", `${ws(workspaceId)}/tool-keys`);
  } catch {
    return null;
  }
};
export const getAccessLists = async (
  workspaceId: string,
): Promise<AccessLists> => {
  try {
    return await core<AccessLists>(
      "GET",
      `/workspaces/${encodeURIComponent(workspaceId)}/access-lists`,
    );
  } catch {
    return { deny: [], allow: [] };
  }
};
/** Limits the core keeps (attachments, trash): the web shows these, never its own. */
export const getAppFacts = cache(
  async (): Promise<components["schemas"]["AppFacts"] | null> => {
    try {
      return await core<components["schemas"]["AppFacts"]>("GET", "/app/facts");
    } catch {
      return null;
    }
  },
);
export const getCofounderActionsMode = () =>
  core<{ mode: "direct" | "ask" }>("GET", "/cofounder-actions/mode");
export const getNotificationRules = () =>
  core<NotificationRule[]>("GET", "/preferences/notifications");

/** The devices (his phone, a browser) that get AGOS's own notifications. */
export const getPushDevices = () =>
  core<PushDevice[]>("GET", "/push/subscriptions");

/** Settings → Access → Use AGOS from other devices (null: the core isn't answering). */
export async function getRemoteAccess(): Promise<RemoteAccess | null> {
  try {
    return await core<RemoteAccess>("GET", "/remote-access");
  } catch {
    return null;
  }
}

/** Providers and models come from Hermes (what is really logged in). */
export async function getProviders(): Promise<ProviderConnection[] | null> {
  try {
    return await core<ProviderConnection[]>("GET", "/models/providers");
  } catch {
    return null; // shown as "Hermes isn't answering" in Settings
  }
}
export async function getModelCatalog(): Promise<CatalogProvider[]> {
  // Pages still open when Hermes can't answer; the pickers keep saved choices.
  try {
    return await core<CatalogProvider[]>("GET", "/models/catalog");
  } catch {
    return [];
  }
}

/** The model a new workspace starts on: the shared Hermes home's own model
 * (`model.*`, `agent.reasoning_effort`); null when Hermes has none there or
 * doesn't answer. */
export async function getDefaultModel(): Promise<
  components["schemas"]["ModelSelection"] | null
> {
  try {
    return await core<components["schemas"]["ModelSelection"] | null>(
      "GET",
      "/models/default",
    );
  } catch {
    return null;
  }
}

export type LogPage = components["schemas"]["LogPage"];
export type LogEntry = components["schemas"]["LogEntry"];
export const getWorkspaceLog = (
  id: string,
  filters: {
    level?: string;
    area?: string;
    q?: string;
    before?: string;
    actor?: string;
    since?: string;
    until?: string;
  },
) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters))
    if (value) params.set(key, value);
  const query = params.toString();
  return core<LogPage>("GET", `${ws(id)}/log${query ? `?${query}` : ""}`);
};

// ---- Documentation: the team's rules ------------------------------------------------

export type DocReader = { agent: string; title: string; mode: string };
export type DocFile = {
  path: string;
  size: number;
  updatedAt: number;
  rule: boolean;
  sections: string[];
  readBy: DocReader[];
};
export type DocFinding = {
  kind: "duplicate" | "pointer" | "orphan" | "language";
  where: string;
  detail: string;
  other: string;
};
export type DeletedAgent = {
  id: number;
  name: string;
  title: string;
  at: string;
};
export type DocsIndex = {
  files: DocFile[];
  findings: DocFinding[];
  latinOnly: boolean;
  deletedAgents: DeletedAgent[];
};
export type DocVersion = {
  id: number;
  at: string;
  author: string;
  why: string;
  size: number;
};
export type DocOpen = {
  path: string;
  text: string;
  hash: string;
  sections: string[];
  readBy: DocReader[];
  versions: DocVersion[];
};
export const getDocs = (id: string) => core<DocsIndex>("GET", `${ws(id)}/docs`);
export const getLearned = (id: string) =>
  core<Learned>("GET", `${ws(id)}/learned`);
export const getAutonomy = (id: string) =>
  core<AutonomyView>("GET", `${ws(id)}/autonomy`);
export const getScreen = (id: string) =>
  core<components["schemas"]["ScreenStatus"]>("GET", `${ws(id)}/screen`);
export const getDoc = (id: string, path: string) =>
  core<DocOpen>("GET", `${ws(id)}/docs/file?path=${encodeURIComponent(path)}`);
/** Every card's files (Hermes's attachments) and documents, with their reviews. */
export const getArtifacts = (id: string) =>
  core<Artifacts>("GET", `${ws(id)}/artifacts`);

export type TeamGroups = {
  groups: { id: string; name: string }[];
  teamGroup: string;
};

/** Telegram groups the workspace's bot is in, and its team group (a topic per chat). */
export async function getTeamGroups(workspaceId: string): Promise<TeamGroups> {
  return (
    (await coreOrNull<TeamGroups>(
      `/workspaces/${seg(workspaceId)}/telegram-groups`,
    )) ?? { groups: [], teamGroup: "" }
  );
}

// ---- Step 59 ------------------------------------------------------------------------

/** Settings → Pipelines: the workspace's pipeline rules. */
export const getPipelines = (id: string) =>
  core<PipelineRule[]>("GET", `${ws(id)}/pipelines`);

/** The dev servers / previews a card's worker started (newest first). */
export const getCardServices = (id: string, cardId: string) =>
  core<CardService[]>("GET", `${ws(id)}/kanban/${seg(cardId)}/services`);

/** Settings → Connections: the workspace's MCP token (null until made). */
export const getMcpToken = (id: string) =>
  core<McpToken>("GET", `${ws(id)}/mcp-token`);
