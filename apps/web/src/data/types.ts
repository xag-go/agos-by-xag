import type { components } from "./core-api";

// Real data types come from the core's API contract (generated, never edited
// by hand): `pnpm gen:api` after the core changes.
type S = components["schemas"];

export type ActivityItem = S["ActivityItem"];
export type Automation = S["Automation"];
export type AutomationRun = S["AutomationRun"];
export type AutomationEvent = S["AutomationEvent"];
export type HookCondition = S["HookCondition"];
export type AutomationVariable = S["AutomationVariable"];
export type AutomationRevision = S["AutomationRevision"];
export type AutomationRunGroup = S["AutomationRunGroup"];
/** A folder of the Automations, Skills or Projects list (AGOS-only grouping). */
export type ListFolder = S["Folder"];
export type FolderKind = ListFolder["kind"];
export type TicketPreset = S["TicketPreset"];
export type Heartbeat = S["Heartbeat"];
export type WorkHours = S["WorkHoursView"];
export type DaySpan = S["DaySpan"];
export type OffLine = S["OffLine"];
export type Scorecard = S["Scorecard"];
export type Scorecards = S["Scorecards"];
export type Founder = S["FounderView"];
export type FounderTask = S["FounderTask"];
export type SkillGrowth = S["SkillGrowth"];
export type SkillRequest = S["SkillRequest"];
export type SkillCandidate = S["SkillCandidate"];
export type BoardCounters = S["BoardCounters"];
export type Chat = S["Chat"];
export type RemoteAccess = S["RemoteAccess"];
export type ChatMessage = S["ChatMessage"];
export type ChatAttachment = S["Attachment"];
export type WorkspaceIdentity = S["IdentityView"];
export type AgentMemory = S["MemoryView"];
export type Connector = S["Connector"];
export type BotSetup = S["BotSetupView"];
export type WorkspaceApp = S["WorkspaceApp"];
export type ConnectorCatalogRow = S["CatalogRow"];
export type AppFlow = S["Flow"];
export type ComposioToolkit = S["ComposioToolkit"];
export type ComposioAccount = S["ComposioAccount"];
export type ComposioAuthSetup = S["ComposioAuthSetup"];
export type LibraryItem = S["LibraryItem"];
export type LibraryKind = LibraryItem["kind"];
export type McpTest = S["McpTest"];
export type SkillVersion = S["SkillVersion"];
export type FileDiff = S["FileDiff"];
export type SkillTests = S["SkillTests"];
export type SkillTestRun = S["TestRun"];
export type SkillTestInput = S["TestInput"];
export type GithubTokenState = S["GithubTokenState"];
export type AccountLimitView = S["AccountLimit"];
export type UsagePrefs = S["UsagePrefs"];
export type TabsOrder = S["TabsOrder"];
export type CapabilityRequest = S["CapabilityRequestView"];
export type FolderListing = S["FolderListing"];
export type CofounderAction = S["CofounderActionView"];

export type NotificationRule = S["NotificationRule"];
export type PushDevice = S["PushSubscription"];
export type ChannelConnection = S["ConnectionView"];
export type ChatAddress = S["AddressView"];
export type BackupStatus = S["BackupStatus"];
export type Rehearsal = S["Rehearsal"];
export type ChatTurn = S["ChatTurn"];
export type ChatActivity = S["ChatActivity"];
export type LiveView = S["LiveView"];
export type KanbanBoard = S["KanbanBoard"];
export type KanbanMember = S["KanbanMember"];
export type KanbanCard = S["KanbanCard"];
export type KanbanCardDetail = S["KanbanCardDetail"];
export type LiveTurn = S["LiveTurnView"];
export type Team = S["Team"];
export type Inbox = S["Inbox"];
export type InboxItem = S["InboxItem"];
export type Proposal = S["ProposalView"];
export type Question = S["QuestionView"];
export type KanbanHold = S["KanbanHold"];
export type ReviewFlow = S["ReviewFlow"];
export type ReviewChip = S["ReviewChip"];
export type ReviewWait = S["ReviewWait"];
export type ReviewNote = S["ReviewNote"];
export type ReviewSettings = S["ReviewSettings"];
export type CardDocument = S["CardDocument"];
export type CardDocOpen = S["CardDocOpen"];
export type CardDocAnnotation = S["CardDocAnnotation"];
export type Artifact = S["Artifact"];
export type Artifacts = S["Artifacts"];
export type Worker = S["Worker"];
export type Readiness = S["Readiness"];
export type ReadinessItem = S["ReadinessItem"];
export type VisionView = S["VisionView"];
export type PlanNode = S["PlanNode"];
export type VisionNotes = S["VisionNotes"];
export type Organized = S["Organized"];
export type NotesRevisionText = S["NotesRevisionText"];
export type GoalRef = S["GoalRef"];
export type OrgEntry = S["OrgEntry"];
export type ChatSearchHit = S["SearchHit"];
export type SearchPage = S["SearchPage"];
export type SearchResult = S["SearchResult"];
export type StatusPage = S["StatusPage"];
export type StatusCard = S["StatusCard"];
export type OfficeLook = S["OfficeLook"];
export type OfficeLooks = S["OfficeLooks"];
export type TrashedWorkspace = S["TrashedWorkspace"];
export type Workspace = S["Workspace"];
export type WorkspaceFolder = S["WorkspaceFolderOut"];
export type BotRestart = S["GatewayRestartOut"];

// ---- Parts of later roadmap steps (demo data for now) ----

export type ProviderConnection = {
  id: string;
  name: string;
  cli: {
    tool: string;
    installed: boolean;
    account: string | null;
    loginCommand: string;
  };
  api: {
    last4: string;
    status: string;
    statusAt: string;
    problem: string;
  } | null;
  apiKey: boolean;
  keyEnv?: string | null;
  more?: boolean;
  /** A subscription each workspace signs in to in its own Hermes. */
  perWorkspace?: boolean;
  workspaces?: { id: string; name: string; connected: boolean }[];
};

export type ProviderLogin = {
  provider: string;
  workspace?: string | null;
  status:
    | "idle"
    | "starting"
    | "waiting"
    | "checking"
    | "done"
    | "failed"
    | "cancelled";
  url: string | null;
  userCode: string | null;
  needsCode: boolean;
  message: string;
};

export type CatalogModel = {
  id: string;
  label: string;
  modes: ("cli" | "api")[];
  efforts: string[];
  defaultEffort: string;
};

export type CatalogProvider = {
  id: string;
  label: string;
  models: CatalogModel[];
  /** Hermes's provider name per way in (the core's mapping). */
  hermesProviders?: Record<string, string>;
};

/** The owner's "Suggest hires" card still open on the Co-Founder (Hierarchy). */
export type HiresAsked = S["HiresAsked"];

// Step 56: templates (export / import, ready-made teams, member revisions).
export type ImportPreview = S["ImportPreview"];
export type ImportReport = S["ImportReport"];
export type BundleInput = S["InputOut"];
export type CatalogTeam = S["CatalogTeam"];
export type AgentRevision = S["AgentRevision"];
// Step 59: pipelines, a card's services, link chips, MCP, voice notes.
export type PipelineRule = S["PipelineRule"];
export type CardService = S["CardService"];
export type ExternalObject = S["ExternalObject"];
export type McpToken = S["McpToken"];
