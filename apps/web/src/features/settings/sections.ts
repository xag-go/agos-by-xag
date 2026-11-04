/** Sections with a `group` are listed under that heading in the nav. */
export const settingsSections = [
  {
    slug: "general",
    label: "General",
    description: "Appearance and how AGOS is laid out for you.",
  },
  {
    slug: "rules",
    label: "My rules",
    description:
      "Rules about you that every workspace follows (language, how to ask you, reports). A project's own work stays in that project.",
  },
  {
    slug: "brain",
    label: "Brain",
    description:
      "Ways of working the whole team learned, for every project. Nothing of a project goes in it.",
  },
  {
    slug: "models",
    label: "Models",
    description:
      "Connect providers once for every workspace: subscription login, API key, or both.",
  },
  {
    slug: "helper-models",
    label: "Helper models",
    description:
      "Choose which model does each side job, like looking at pictures or summing up long chats.",
  },
  {
    slug: "connectors",
    label: "Connectors",
    description:
      "Every app and MCP server in one list. Each workspace turns on the ones it needs and signs in with its own account in its own Settings → Connectors; no login or key is shared.",
  },
  {
    slug: "tools",
    label: "Tools",
    description: "Every tool Hermes has, from Hermes's own list.",
  },
  {
    slug: "hermes",
    label: "Hermes settings",
    description:
      "Every setting of Hermes, the engine every workspace runs on: Hermes's own list, its words and its defaults, with each workspace's value. Change one here and it is written into every workspace's Hermes (its Co-Founder and each member).",
  },
  {
    slug: "health",
    label: "Health",
    description:
      "Hermes's own checks of every workspace's engine: its “hermes status” and “hermes doctor”, as Hermes prints them (with the managed scope every workspace shares).",
  },
  {
    slug: "errors",
    label: "Errors",
    description:
      "AGOS's own errors and each workspace's Hermes errors, grouped: how often, when first and last, and on which version. Mark one fixed; if it happens again it opens again and you are told.",
  },
  {
    slug: "usage",
    label: "Usage & limits",
    description: "Account-wide limits, shared by every workspace.",
  },
  {
    slug: "access",
    label: "Access",
    description: "Who can open AGOS, and how to reach it from another device.",
  },
  {
    slug: "notifications",
    label: "Notifications",
    description: "How each kind of event reaches you.",
  },
  {
    slug: "server",
    label: "Server & backup",
    description: "Machine status, backups and disk health.",
  },
] as const;

export type SettingsSlug = (typeof settingsSections)[number]["slug"];

export function groupOf(
  section: (typeof settingsSections)[number],
): string | null {
  return (section as { group?: string }).group ?? null;
}
